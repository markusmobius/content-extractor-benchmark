"""Freeze and build two Go-Trafilatura v2 sources for compare.py without editing them."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prepare import sha256, write_json


OLD_BASELINE = "72dce36bfe95502563533cf68a9050370a3d7081"
MODULE = "github.com/markusmobius/go-trafilatura/v2"


def command_output(command, environment=None):
    return subprocess.run(command, check=True, capture_output=True, env=environment).stdout


def git_output(git, source, *arguments):
    return command_output([git, "-C", str(source), *arguments])


def json_objects(data):
    decoder = json.JSONDecoder()
    text = data.decode("utf-8")
    values = []
    while text.strip():
        text = text.lstrip()
        value, position = decoder.raw_decode(text)
        values.append(value)
        text = text[position:]
    return values


def archive_source(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise ValueError(f"Unsafe archive path: {member.name}")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as reader, path.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
                if member.mode & 0o111:
                    path.chmod(path.stat().st_mode | 0o111)
            else:
                raise ValueError(f"Unsupported archive member: {member.name}")


def file_hashes(source):
    return {path.relative_to(source).as_posix(): sha256(path) for path in sorted(source.rglob("*")) if path.is_file()}


def freeze(source, revision, destination, git):
    destination.mkdir(parents=True, exist_ok=False)
    worktree = revision.upper() == "WORKTREE"
    commit = git_output(git, source, "rev-parse", "--verify", "HEAD^{commit}" if worktree else f"{revision}^{{commit}}").decode().strip()
    if worktree:
        paths = git_output(git, source, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
        for relative in sorted(set(paths) - {""}):
            origin = source / relative
            if origin.is_symlink():
                raise ValueError(f"Source symlinks are not supported by this snapshot builder: {relative}")
            if not origin.exists():
                continue
            if not origin.is_file():
                raise ValueError(f"Source submodules are not supported: {relative}")
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Invalid source path: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
        patch = git_output(git, source, "diff", "HEAD", "--binary").decode("utf-8")
        status = git_output(git, source, "status", "--porcelain=v1", "--untracked-files=all").decode("utf-8")
    else:
        archive_source(git_output(git, source, "-c", "core.autocrlf=false", "archive", "--format=tar", commit), destination)
        patch, status = "", ""
    hashes = file_hashes(destination)
    if not {"go.mod", "go.sum"}.issubset(hashes):
        raise ValueError("Source snapshot does not contain a Go module and checksum file")
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    return {"commit": commit, "requested_revision": revision, "worktree": worktree, "status": status, "patch": patch, "files": hashes, "sha256": fingerprint}


def build_variant(name, arguments, environment, adapter, compiler_version):
    revision = arguments.old_ref if name == "old" else arguments.new_ref
    directory = arguments.output / name
    directory.mkdir()
    source = directory / "source"
    print(f"Freezing {name}: {revision}", flush=True)
    identity = freeze(arguments.source, revision, source, arguments.git)
    modules = json_objects(command_output([arguments.go, "-C", str(source), "list", "-mod=readonly", "-m", "-json", "all"], environment))
    if not modules or modules[0].get("Path") != MODULE or not modules[0].get("Main"):
        raise ValueError(f"{name}: source is not {MODULE}")
    if any(module.get("Replace") for module in modules):
        raise ValueError(f"{name}: dependency replacements are not permitted in this comparison")
    binary = arguments.output / "bin" / (name + (".exe" if os.name == "nt" else ""))
    binary.parent.mkdir(exist_ok=True)
    command = [arguments.go, "-C", str(source), "build", "-mod=readonly", "-trimpath", "-pgo=off", "-buildvcs=false", "-o", str(binary), str(adapter)]
    settings = json.loads(command_output([arguments.go, "-C", str(source), "env", "-json", "GOVERSION", "GOOS", "GOARCH", "GOAMD64", "GOARM", "GOARM64", "GOEXPERIMENT", "CGO_ENABLED", "GOTOOLCHAIN", "GOWORK", "GOFLAGS"], environment))
    print(f"Building {name} with {compiler_version}", flush=True)
    subprocess.run(command, env=environment, check=True)
    if file_hashes(source) != identity["files"]:
        raise ValueError(f"{name}: source or module files changed during the readonly build")
    if identity["worktree"]:
        for relative, expected in identity["files"].items():
            if sha256(arguments.source / relative) != expected:
                raise ValueError(f"Live source changed while building: {relative}; use a new snapshot")
    receipt = {
        "schema_version": 1, "name": name, "source": identity,
        "compiler": compiler_version, "command": command,
        "effective_go_environment": settings,
        "build_environment": {key: environment.get(key) for key in ("GOWORK", "CGO_ENABLED", "GOTOOLCHAIN", "GOOS", "GOARCH", "GOAMD64", "GOFLAGS", "GOMAXPROCS")},
        "modules": modules, "adapter_sha256": sha256(adapter), "binary_sha256": sha256(binary),
    }
    write_json(directory / "build.json", receipt)
    version = identity["commit"] + (f"+worktree.{identity['sha256'][:12]}" if identity["worktree"] else "")
    command = [str(binary.relative_to(arguments.output)), "-focus", arguments.focus]
    if arguments.fallback:
        command.append("-fallback")
    if arguments.comments:
        command.append("-comments")
    return {
        "name": f"{name}-go", "version": version,
        "profile": "native-fallbacks" if arguments.fallback else "core-only",
        "options": {"fallback": arguments.fallback, "focus": arguments.focus, "comments": arguments.comments, "tables": True, "images": False, "links": False, "deduplicate": False, "target_language": ""},
        "command": command, "cwd": ".", "artifacts": [f"{name}/build.json", "adapter.go"],
        "env": {"GOMAXPROCS": "1", "GOGC": "100", "GOMEMLIMIT": "off", "GODEBUG": "", "TZ": "UTC"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Canonical Go-Trafilatura Git checkout, not a copy nested in another Git repo")
    parser.add_argument("--old-ref", default=OLD_BASELINE, help="Old Git revision; default is the saved pre-alignment baseline; use v2.2.1 for release comparison")
    parser.add_argument("--new-ref", default="WORKTREE", help="New revision or WORKTREE including dirty and untracked nonignored files")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "go-trafilatura-comparison")
    parser.add_argument("--go", default="go")
    parser.add_argument("--git", default="git")
    parser.add_argument("--toolchain", default="go1.27.1")
    parser.add_argument("--fallback", action="store_true")
    parser.add_argument("--comments", action="store_true")
    parser.add_argument("--focus", choices=("balanced", "precision", "recall"), default="balanced")
    arguments = parser.parse_args()
    arguments.source = arguments.source.resolve()
    arguments.output = arguments.output.resolve()
    top = Path(git_output(arguments.git, arguments.source, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != arguments.source:
        raise ValueError(f"--source must be its own Git root, found {top}")
    if arguments.output.is_relative_to(arguments.source):
        raise ValueError("Store build snapshots outside the source checkout")
    for executable in ("go", "git"):
        resolved = shutil.which(getattr(arguments, executable))
        if not resolved:
            raise ValueError(f"Executable not found: {getattr(arguments, executable)}")
        setattr(arguments, executable, str(Path(resolved).resolve()))
    environment = os.environ.copy()
    environment.update({"GOWORK": "off", "CGO_ENABLED": "0", "GOTOOLCHAIN": arguments.toolchain, "GOAMD64": "v1", "GOFLAGS": "", "GOMAXPROCS": "1"})
    host = json.loads(command_output([arguments.go, "env", "-json", "GOHOSTOS", "GOHOSTARCH"], environment))
    environment.update({"GOOS": host["GOHOSTOS"], "GOARCH": host["GOHOSTARCH"]})
    compiler = command_output([arguments.go, "version"], environment).decode().strip()
    if arguments.toolchain not in compiler.split():
        raise ValueError(f"Unexpected compiler: {compiler}")
    arguments.output.mkdir(parents=True, exist_ok=False)
    adapter = arguments.output / "adapter.go"
    adapter.write_bytes((ROOT / "tools" / "trafilatura.go.tmpl").read_bytes())
    scrapers = [build_variant(name, arguments, environment, adapter, compiler) for name in ("old", "new")]
    write_json(arguments.output / "compare.json", {"schema_version": 1, "scrapers": scrapers})
    print(f"Ready: python compare.py --config {arguments.output / 'compare.json'} --output results/go-old-new", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        raise SystemExit(str(error)) from error