"""Build isolated old/new unified Rust workers without changing release tags."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prepare import sha256, write_json
from tools.build_go_trafilatura import archive_source, command_output, file_hashes, git_output


def snapshot(repository, destination, reference, git):
    commit = git_output(git, repository, "rev-parse", f"{reference or 'HEAD'}^{{commit}}").decode().strip()
    archive_source(git_output(git, repository, "archive", "--format=tar", commit), destination)
    if reference is None:
        changed = git_output(git, repository, "ls-files", "-z", "--modified", "--others", "--exclude-standard").decode().split("\0")
        for relative in filter(None, changed):
            source = repository / relative
            if "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            target = destination / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()
    hashes = file_hashes(destination)
    return {"commit": commit, "reference": reference or "WORKTREE", "files": hashes, "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def source_configuration(manifest, directory):
    configuration = []
    for package, repository in (("rust-readability-v2", "rust-readability"), ("rust-domdistiller", "rust-domdistiller")):
        dependency = manifest["dependencies"][package]
        if "git" in dependency:
            configuration.extend(["--config", f'patch.{json.dumps(dependency["git"])}.{package}.path={json.dumps(str((directory / repository).resolve()))}'])
        elif dependency.get("path") != f"../{repository}":
            raise ValueError(f"Worktree comparison requires a sibling path or Git dependency: {package}")
    return configuration


def build(arguments):
    arguments.output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, "RUSTFLAGS": "", "CARGO_ENCODED_RUSTFLAGS": "", "CARGO_BUILD_JOBS": "1", "CARGO_NET_GIT_FETCH_WITH_CLI": "true"}
    for key in list(environment):
        if key.startswith("CARGO_PROFILE_RELEASE_") or key in ("CARGO_TARGET_DIR", "CARGO_BUILD_RUSTFLAGS", "CARGO_BUILD_TARGET"):
            del environment[key]
    cargo = [arguments.cargo, "+" + arguments.toolchain]
    scrapers = []
    for label, reference in (("previous", arguments.previous_ref), ("candidate", arguments.candidate_ref)):
        directory = arguments.output / label
        directory.mkdir()
        source = directory / "rust-trafilatura"
        identities = {"rust-trafilatura": snapshot(arguments.sources / "rust-trafilatura", source, reference, arguments.git)}
        if label == "candidate" and reference is None:
            for name in ("rust-readability", "rust-domdistiller"):
                identities[name] = snapshot(arguments.sources / name, directory / name, None, arguments.git)
        adapter = source / "examples" / "benchmark_split.rs"
        adapter.write_bytes((ROOT / "tools" / "unified.rs.tmpl").read_bytes())
        decoder = source / "examples" / "input_encoding"
        shutil.copytree(source / "src" / "encoding", decoder)
        shutil.copy2(source / "src" / "encoding.rs", decoder / "mod.rs")
        manifest_path = source / "Cargo.toml"
        manifest = manifest_path.read_text(encoding="utf-8")
        parsed_manifest = tomllib.loads(manifest)
        worker_cargo = [*cargo, *(source_configuration(parsed_manifest, directory) if label == "candidate" and reference is None else [])]
        manifest_path.write_text(manifest.replace("[features]\n", "[features]\nbenchmark-shared-input = []\n", 1), encoding="utf-8")
        target = arguments.target_dir.resolve() if arguments.target_dir else arguments.output / "target"
        command = [*worker_cargo, "build", *(["--locked"] if reference is not None else []), *(["--offline"] if arguments.offline else []), "--release", "--example", "benchmark_split", "--manifest-path", str(manifest_path), "--target-dir", str(target)]
        if label == "candidate":
            command.extend(["--features", "benchmark-shared-input"])
        print(f"Building {label} unified Rust worker", flush=True)
        subprocess.run(command, env=environment, check=True)
        binary = directory / ("unified.exe" if os.name == "nt" else "unified")
        shutil.copy2(target / "release" / "examples" / ("benchmark_split.exe" if os.name == "nt" else "benchmark_split"), binary)
        metadata = json.loads(command_output([*worker_cargo, "metadata", "--locked", "--offline", "--format-version", "1", "--manifest-path", str(manifest_path), *(["--features", "benchmark-shared-input"] if label == "candidate" else [])], environment))
        versions = {package["name"]: package["version"] for package in metadata["packages"] if package["name"] in ("rust-readability-v2", "rust-domdistiller", "rust-trafilatura")}
        receipt = {"sources": identities, "versions": versions, "command": command, "cargo_metadata": metadata, "adapter_sha256": sha256(adapter), "binary_sha256": sha256(binary), "manifest_sha256": sha256(manifest_path), "profile": tomllib.loads(manifest)["profile"]["release"], "compiler": command_output([arguments.rustc, "+" + arguments.toolchain, "-vV"], environment).decode().strip()}
        for name, identity in identities.items():
            for relative, expected in identity["files"].items():
                if relative not in ("Cargo.toml", "Cargo.lock") and sha256(directory / name / relative) != expected:
                    raise ValueError(f"Build modified library source: {name}/{relative}")
        write_json(directory / "build.json", receipt)
        scrapers.append({"name": label, "version": "; ".join(f"{name}={version}" for name, version in sorted(versions.items())), "profile": "shared-DOM/native-split", "options": {"engines": versions, "trafilatura_fallback": False, "comments": False, "pagination": False, "allocator": "mimalloc", "decode": "native-trafilatura-reader", "parser": "readability-html5-single-shared-input"}, "command": [str(binary)], "cwd": ".", "env": {"TZ": "UTC"}, "artifacts": [str(directory / "build.json"), str(adapter)]})
    write_json(arguments.output / "compare.json", {"schema_version": 1, "scrapers": scrapers})
    print(f"Ready: {arguments.output / 'compare.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT.parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--previous-ref", default="v2.2.2")
    parser.add_argument("--candidate-ref", help="Exact Trafilatura tag/commit and its locked dependencies; omit to snapshot all three working trees")
    parser.add_argument("--offline", action="store_true", help="Require all Cargo dependencies to be cached")
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--git", default="git")
    parser.add_argument("--toolchain", default="1.98.1-x86_64-pc-windows-gnu" if os.name == "nt" else "1.98.1")
    arguments = parser.parse_args()
    arguments.output = arguments.output.resolve()
    arguments.sources = arguments.sources.resolve()
    build(arguments)


if __name__ == "__main__":
    main()