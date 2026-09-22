"""Build the released unified Go worker and pair it with a verified Rust worker."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare import load_scrapers
from prepare import sha256, write_json
from tools.build_releases import RUNTIME, build_go, load_suite, snapshot


GO_RELEASES = ("go-readabilityV2-0.6.0", "go-domdistiller-1.0.0", "go-trafilatura-2.2.2")
RUST_RELEASES = {
    "rust-readability-v2": {"version": "0.6.2", "repository": "rust-readability", "commit": "7180c261cff311794b1b75ff3eae2a2bc63fd1c8"},
    "rust-domdistiller": {"version": "1.0.1", "repository": "rust-domdistiller", "commit": "e95bff0cea7f7b9639abe04a8531b220b3ee4a6e"},
    "rust-trafilatura": {"version": "2.2.3", "repository": "rust-trafilatura", "commit": "bbc95a6bbf67ed881cb42c0a830154f061bedbbe"},
}


def go_engine_identities(modules, entries):
    modules = {module["Path"]: module for module in modules}
    identities = {}
    for entry in entries:
        module = modules[entry["module"]]
        identity = dict(entry)
        if not module.get("Main"):
            information = json.loads(Path(module["GoMod"]).with_suffix(".info").read_text(encoding="utf-8"))
            origin = information.get("Origin", {})
            if information.get("Version") != module["Version"] or origin.get("Hash") != entry["commit"] or origin.get("URL") != entry["repository"]:
                raise ValueError(f"Unified Go dependency differs from the pinned release: {entry['name']}")
            identity.update({"resolved_module_version": module["Version"], "sum": module["Sum"], "go_mod_sum": module["GoModSum"], "origin": origin})
        identities[entry["engine"]] = identity
    return identities


def validate_rust_receipt(receipt):
    if receipt.get("versions") != {name: release["version"] for name, release in RUST_RELEASES.items()}:
        raise ValueError("Rust worker does not contain the requested six-engine suite releases")
    root = receipt.get("sources", {}).get("rust-trafilatura", {})
    if root.get("commit") != RUST_RELEASES["rust-trafilatura"]["commit"] or root.get("reference") not in ("v2.2.3", RUST_RELEASES["rust-trafilatura"]["commit"]):
        raise ValueError("Rust worker must use the exact released Trafilatura source")
    for name, release in RUST_RELEASES.items():
        packages = [package for package in receipt["cargo_metadata"]["packages"] if package["name"] == name]
        expected = None if name == "rust-trafilatura" else f"git+https://github.com/markusmobius/{release['repository']}?tag=v{release['version']}#{release['commit']}"
        if len(packages) != 1 or packages[0]["version"] != release["version"] or packages[0]["source"] != expected:
            raise ValueError(f"Rust worker dependency differs from the pinned release: {name}")


def rust_worker(config, name):
    worker, = load_scrapers(config.resolve(), [name])
    receipts = [Path(path) for path in worker["artifacts_sha256"] if Path(path).name == "build.json"]
    if len(receipts) != 1:
        raise ValueError("Rust worker requires exactly one build.json receipt")
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    validate_rust_receipt(receipt)
    if receipt["binary_sha256"] != sha256(Path(worker["command"][0])) or receipt["adapter_sha256"] != sha256(ROOT / "tools" / "unified.rs.tmpl"):
        raise ValueError("Rust binary or adapter differs from the verified split build")
    options = worker["options"]
    if any(options.get(key) is not False for key in ("trafilatura_fallback", "comments", "pagination")):
        raise ValueError("Rust worker requires fallback/comments/pagination disabled")
    return {**{key: worker[key] for key in ("version", "profile", "options", "command", "cwd", "env")},
            "name": "rust", "artifacts": list(worker["artifacts_sha256"])}


def build(arguments):
    rust = rust_worker(arguments.rust_config, arguments.rust_worker)
    entries = load_suite(ROOT / "release-suite.json", GO_RELEASES)
    entry, = [entry for entry in entries if entry["engine"] == "trafilatura"]
    arguments.output.mkdir(parents=True, exist_ok=False)
    directory = arguments.output / "go"
    directory.mkdir()
    source, identity = snapshot(entry, directory, arguments.git)
    binary = directory / ("unified.exe" if os.name == "nt" else "unified")
    build, _ = build_go(entry, source, directory, binary, arguments, os.environ.copy(), ROOT / "tools" / "unified.go.tmpl")
    engines = go_engine_identities(build["modules"], entries)
    adapter = directory / "adapter.go"
    test_adapter = directory / "adapter_test.go"
    shutil.copy2(ROOT / "tools" / "unified_test.go.tmpl", test_adapter)
    environment = {**os.environ, **RUNTIME, **build["environment"]}
    checks = [
        [arguments.go, "-C", str(source), "mod", "verify"],
        [arguments.go, "-C", str(source), "test", "-mod=readonly", "-count=1", str(adapter), str(test_adapter)],
        [arguments.go, "-C", str(source), "vet", "-mod=readonly", str(adapter), str(test_adapter)],
    ]
    for command in checks:
        subprocess.run(command, env=environment, check=True)
    for relative, expected in identity["files"].items():
        if sha256(source / relative) != expected:
            raise ValueError(f"Go build changed release source: {relative}")
    versions = {entry["module"]: entry["tag"][1:] for entry in entries}
    receipt = {"schema_version": 1, "name": "go", "source": identity, "versions": versions,
               "engine_releases": engines, **build, "binary_sha256": sha256(binary),
               "test_adapter_sha256": sha256(test_adapter), "validation_commands": checks,
               "builder_sha256": sha256(Path(__file__)), "shared_builder_sha256": sha256(ROOT / "tools" / "build_releases.py"),
               "dependency_profile": "All three engines use the unchanged Go-Trafilatura v2.2.2 module graph; DomDistiller's pseudo-version resolves to the v1.0.0 release commit."}
    write_json(directory / "build.json", receipt)
    go = {"name": "go", "version": "; ".join(f"{name}={version}" for name, version in sorted(versions.items())),
          "profile": "shared-DOM/native-split", "command": [str(binary)], "cwd": ".", "env": RUNTIME,
          "artifacts": [str(directory / "build.json"), str(adapter), str(test_adapter)],
          "options": {"engines": versions, "trafilatura_fallback": False, "comments": False, "tables": True,
                      "pagination": False, "metadata": "native-only", "naive_date_timezone": "UTC",
                      "decode": "go-shiori/dom.Parse", "parser": "golang.org/x/net/html-single-shared-input",
                      "garbage_collection": "GOGC=100; no forced per-call collection"}}
    write_json(arguments.output / "compare.json", {"schema_version": 1, "scrapers": [go, rust]})
    print(f"Ready: {arguments.output / 'compare.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-config", type=Path, required=True, help="Config produced by build_split_rust.py --candidate-ref v2.2.3")
    parser.add_argument("--rust-worker", default="candidate")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--go", default="go")
    parser.add_argument("--git", default="git")
    parser.add_argument("--go-toolchain", default="go1.27.1")
    arguments = parser.parse_args()
    arguments.output = arguments.output.resolve()
    for name in ("go", "git"):
        located = shutil.which(getattr(arguments, name))
        if not located:
            raise ValueError(f"Executable not found: {getattr(arguments, name)}")
        setattr(arguments, name, str(Path(located).resolve()))
    build(arguments)


if __name__ == "__main__":
    main()