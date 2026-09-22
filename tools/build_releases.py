"""Build isolated, commit-verified Go/Rust release adapters for compare.py."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prepare import sha256, write_json
from tools.build_go_trafilatura import archive_source, command_output, file_hashes, git_output, json_objects


RUNTIME = {"GOMAXPROCS": "1", "GOGC": "100", "GOMEMLIMIT": "off", "GODEBUG": "", "TZ": "UTC"}


def load_suite(path, names=None):
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1 or not registry.get("scrapers"):
        raise ValueError("Release suite requires schema_version 1 and scrapers")
    seen = set()
    for entry in registry["scrapers"]:
        name = entry["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in seen:
            raise ValueError(f"Invalid or duplicate release name: {name}")
        seen.add(name)
        if entry["language"] not in ("go", "rust") or entry["engine"] not in ("trafilatura", "domdistiller", "readability"):
            raise ValueError(f"Unsupported release adapter: {name}")
        if not re.fullmatch(r"[0-9a-f]{40}", entry["commit"]) or not re.fullmatch(r"v\d+\.\d+\.\d+", entry["tag"]):
            raise ValueError(f"Release requires an exact commit and version tag: {name}")
        if not entry["repository"].startswith("https://github.com/"):
            raise ValueError(f"Release requires an HTTPS GitHub source: {name}")
    if names and set(names) - seen:
        raise ValueError(f"Unknown release names: {sorted(set(names) - seen)}")
    return [entry for entry in registry["scrapers"] if not names or entry["name"] in names]


def go_adapter(entry):
    data = (ROOT / "tools" / f"{entry['engine']}.go.tmpl").read_bytes()
    if entry["engine"] == "trafilatura":
        data = data.replace(b'"github.com/markusmobius/go-trafilatura/v2"', json.dumps(entry["module"]).encode("utf-8"))
    return data


def snapshot(entry, directory, git):
    repository = directory / "repository"
    source = directory / "source"
    subprocess.run([git, "clone", "--quiet", "--no-checkout", "--depth", "1", "--branch", entry["tag"], entry["repository"] + ".git", str(repository)], check=True)
    commit = git_output(git, repository, "rev-parse", "HEAD^{commit}").decode().strip()
    if commit != entry["commit"]:
        raise ValueError(f"{entry['name']}: tag moved or the pinned commit is wrong: {commit}")
    print(f"Verified tag; exporting {entry['name']} source", flush=True)
    archive_source(git_output(git, repository, "-c", "core.autocrlf=false", "archive", "--format=tar", commit), source)
    hashes = file_hashes(source)
    return source, {"repository": entry["repository"], "tag": entry["tag"], "commit": commit, "files": hashes, "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def build_go(entry, source, directory, binary, arguments, environment):
    environment = {**environment, **RUNTIME, "GOWORK": "off", "CGO_ENABLED": "0", "GOTOOLCHAIN": arguments.go_toolchain, "GOAMD64": "v1", "GOFLAGS": "", "GOEXPERIMENT": ""}
    host = json.loads(command_output([arguments.go, "env", "-json", "GOHOSTOS", "GOHOSTARCH"], environment))
    environment.update({"GOOS": host["GOHOSTOS"], "GOARCH": host["GOHOSTARCH"]})
    compiler = command_output([arguments.go, "version"], environment).decode().strip()
    if arguments.go_toolchain not in compiler.split():
        raise ValueError(f"Unexpected Go compiler: {compiler}")
    print(f"Resolving {entry['name']} original Go module graph", flush=True)
    modules = json_objects(command_output([arguments.go, "-C", str(source), "list", "-mod=readonly", "-m", "-json", "all"], environment))
    main = [module for module in modules if module.get("Main")]
    if len(main) != 1 or main[0]["Path"] != entry["module"] or any(module.get("Replace") for module in modules):
        raise ValueError(f"{entry['name']}: unexpected module identity or dependency replacements")
    adapter = directory / "adapter.go"
    adapter.write_bytes(go_adapter(entry))
    command = [arguments.go, "-C", str(source), "build", "-mod=readonly", "-trimpath", "-pgo=off", "-buildvcs=false", "-o", str(binary), str(adapter)]
    print(f"Compiling {entry['name']}", flush=True)
    subprocess.run(command, env=environment, check=True)
    settings = json.loads(command_output([arguments.go, "-C", str(source), "env", "-json", "GOVERSION", "GOOS", "GOARCH", "GOAMD64", "GOARM", "GOARM64", "GOEXPERIMENT", "CGO_ENABLED", "GOTOOLCHAIN", "GOWORK", "GOFLAGS"], environment))
    return {"compiler": compiler, "command": command, "environment": settings, "modules": modules, "adapter_sha256": sha256(adapter)}, []


def build_rust(entry, source, directory, binary, arguments, environment):
    environment = {**environment, "TZ": "UTC", "RUSTFLAGS": "", "CARGO_ENCODED_RUSTFLAGS": "", "CARGO_BUILD_JOBS": "1", "CARGO_NET_GIT_FETCH_WITH_CLI": "true"}
    for key in list(environment):
        if key.startswith("CARGO_PROFILE_RELEASE_") or key in ("CARGO_BUILD_TARGET", "CARGO_TARGET_DIR", "CARGO_BUILD_RUSTFLAGS"):
            del environment[key]
    manifest = tomllib.loads((source / "Cargo.toml").read_text(encoding="utf-8"))
    if manifest["package"]["name"] != entry["package"] or manifest["package"]["version"] != entry["tag"][1:]:
        raise ValueError(f"{entry['name']}: package name or version differs from the release")
    cargo = [arguments.cargo, f"+{arguments.rust_toolchain}"]
    compiler = command_output([arguments.rustc, f"+{arguments.rust_toolchain}", "-vV"], environment).decode().strip()
    cargo_version = command_output([*cargo, "--version"], environment).decode().strip()
    example = "benchmark" if entry["engine"] == "trafilatura" else "benchmark_suite"
    adapter = source / "examples" / f"{example}.rs"
    if entry["engine"] != "trafilatura":
        adapter.parent.mkdir(exist_ok=True)
        if adapter.exists():
            raise ValueError(f"Refusing to overwrite a published example: {adapter}")
        adapter.write_bytes((ROOT / "tools" / f"{entry['engine']}.rs.tmpl").read_bytes())
    print(f"Resolving {entry['name']} locked Cargo graph", flush=True)
    metadata = json.loads(command_output([*cargo, "metadata", "--locked", "--format-version", "1", "--manifest-path", str(source / "Cargo.toml")], environment))
    if any(package.get("source") is None and package["id"] != metadata["resolve"]["root"] for package in metadata["packages"]):
        raise ValueError(f"{entry['name']}: local path dependencies are not permitted")
    target = arguments.output / "cargo-target"
    command = [*cargo, "build", "--locked", "--release", "--example", example, "--manifest-path", str(source / "Cargo.toml"), "--target-dir", str(target)]
    subprocess.run(command, env=environment, check=True)
    shutil.copy2(target / "release" / "examples" / (example + (".exe" if os.name == "nt" else "")), binary)
    return {
        "compiler": compiler, "cargo": cargo_version, "toolchain": arguments.rust_toolchain, "command": command,
        "profile": manifest.get("profile", {}).get("release", {}),
        "environment": {key: value for key, value in environment.items() if key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_JOBS", "TZ") or key.startswith("CARGO_TARGET_")},
        "cargo_metadata": metadata, "adapter_sha256": sha256(adapter),
    }, ["--jsonl"] if entry["engine"] == "trafilatura" else []


def build_release(entry, arguments):
    print(f"Building {entry['name']} from {entry['tag']} at {entry['commit']}", flush=True)
    directory = arguments.output / entry["name"]
    directory.mkdir()
    source, identity = snapshot(entry, directory, arguments.git)
    binary = directory / ("extract.exe" if os.name == "nt" else "extract")
    environment = os.environ.copy()
    builder = build_go if entry["language"] == "go" else build_rust
    build, command_arguments = builder(entry, source, directory, binary, arguments, environment)
    for path, expected in identity["files"].items():
        if sha256(source / path) != expected:
            raise ValueError(f"Published source changed during build: {entry['name']}/{path}")
    receipt = {"schema_version": 1, "name": entry["name"], "source": identity, **build, "binary_sha256": sha256(binary), "builder_sha256": sha256(Path(__file__))}
    write_json(directory / "build.json", receipt)
    options = {"input": "native-reader", "metadata": "native-only"}
    if entry["engine"] == "trafilatura":
        options.update({"fallback": False, "focus": "balanced", "comments": False, "tables": True, "images": False, "links": False, "deduplicate": False, "target_language": ""})
    elif entry["engine"] == "domdistiller":
        options["pagination"] = False
    else:
        options.update({"parser": "default", "publication_date": True, "naive_date_timezone": "UTC"})
    return {
        "name": entry["name"], "version": entry["tag"], "profile": "core-only" if entry["engine"] == "trafilatura" else "standalone",
        "options": options, "command": [str(binary.relative_to(arguments.output)), *command_arguments],
        "cwd": ".", "artifacts": [f"{entry['name']}/build.json"], "env": RUNTIME,
        "release": entry, "build_receipt": f"{entry['name']}/build.json",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "release-suite.json")
    parser.add_argument("--output", type=Path, required=True, help="New isolated build directory; never overwrite previous binaries")
    parser.add_argument("--scraper", action="append", help="Build a subset of the pinned releases")
    parser.add_argument("--go", default="go")
    parser.add_argument("--git", default="git")
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--go-toolchain", default="go1.27.1")
    parser.add_argument("--rust-toolchain", default="1.98.1")
    arguments = parser.parse_args()
    entries = load_suite(arguments.suite, arguments.scraper)
    for executable in ("git", *(name for name in ("go", "cargo", "rustc") if any(entry["language"] == ("go" if name == "go" else "rust") for entry in entries))):
        resolved = shutil.which(getattr(arguments, executable))
        if not resolved:
            raise ValueError(f"Executable not found: {getattr(arguments, executable)}")
        setattr(arguments, executable, str(Path(resolved).resolve()))
    arguments.output = arguments.output.resolve()
    arguments.output.mkdir(parents=True, exist_ok=False)
    scrapers = [build_release(entry, arguments) for entry in entries]
    write_json(arguments.output / "compare.json", {"schema_version": 1, "suite_sha256": sha256(arguments.suite), "scrapers": scrapers})
    print(f"Ready: python compare.py --config {arguments.output / 'compare.json'} --output results/release-comparison --mode speed --runs 4", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        raise SystemExit(str(error)) from error