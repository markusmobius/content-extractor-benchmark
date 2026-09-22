"""Prepare pinned, independently annotated corpora without running extractors."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
from urllib.parse import urlsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / ".cache"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def url_key(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        hostname = parsed.hostname.lower().removeprefix("www.")
        if parsed.port and parsed.port not in (80, 443):
            hostname += f":{parsed.port}"
        return hostname + (parsed.path.rstrip("/") or "/") + (f"?{parsed.query}" if parsed.query else "")
    except ValueError:
        return None


def fetch_source(name, specification, destination):
    source = destination / "sources" / name
    marker = source / ".source.json"
    if marker.exists():
        print(f"Verifying cached {name} source", flush=True)
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved["revision"] != specification["revision"]:
            raise ValueError(f"{name}: cached revision differs; use a new --data directory")
        if specification.get("archive_sha256", saved["archive_sha256"]) != saved["archive_sha256"]:
            raise ValueError(f"{name}: cached archive checksum differs from the registry")
        for index, (relative, expected) in enumerate(saved["files"].items(), start=1):
            if sha256(source / relative) != expected:
                raise ValueError(f"{name}: cached source changed: {relative}")
            if index % 200 == 0:
                print(f"Verified {name}: {index}/{len(saved['files'])} files", flush=True)
        return source, saved
    archive = destination / "archives" / f"{name}-{specification['revision']}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        repository = specification["repository"].removeprefix("https://github.com/")
        address = f"https://codeload.github.com/{repository}/tar.gz/{specification['revision']}"
        temporary = archive.with_suffix(".part")
        print(f"Downloading {name} at {specification['revision']}", flush=True)
        with urlopen(address, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(archive)
    digest = sha256(archive)
    expected = specification.get("archive_sha256")
    if expected and digest != expected:
        raise ValueError(f"{name}: archive checksum mismatch")
    source.mkdir(parents=True, exist_ok=True)
    files = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2 or ".." in parts or PurePosixPath(member.name).is_absolute():
                continue
            relative = PurePosixPath(*parts[1:])
            selected = relative.as_posix() in {
                "LICENSE", "README.md", "README.rst", "evaluate.py", "ground-truth.json", "metadata.json", "data.go"
            } or relative.parts[0] in {"files", "html", "dev", "test"}
            if not selected or not member.isfile():
                continue
            target = source / relative
            if not target.resolve().is_relative_to(source.resolve()):
                raise ValueError(f"Unsafe archive path: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as input_stream, target.open("wb") as output:
                shutil.copyfileobj(input_stream, output)
            files[relative.as_posix()] = sha256(target)
    saved = {"revision": specification["revision"], "archive_sha256": digest, "files": files}
    write_json(marker, saved)
    return source, saved


def store_html(raw, destination):
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"html/{digest}.html"
    path = destination / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256(path) != digest:
            raise ValueError(f"Prepared HTML changed: {relative}")
    else:
        path.write_bytes(raw)
    return {"html_path": relative, "html_sha256": digest}


def prepare_legonews(source, destination, go):
    command = [go, "run", "-mod=readonly", str(ROOT / "tools/export_legonews.go"), "-data", str(source / "data.go")]
    print("Exporting pinned LegoNews annotations", flush=True)
    output = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, encoding="utf-8", timeout=120)
    entries = json.loads(output.stdout)
    print(f"Preparing {len(entries)} LegoNews inputs", flush=True)
    records = []
    for index, entry in enumerate(entries, start=1):
        filename = entry["file"]
        path = source / "files" / filename
        if path.resolve().parent != (source / "files").resolve():
            raise ValueError(f"Invalid LegoNews file: {filename}")
        records.append({
            "id": f"legonews/{filename}", "corpus": "legonews", "split": "standard",
            "page_type": "unclassified", "url": entry.get("url", ""),
            "with": entry.get("with", []), "without": entry.get("without", []),
            "metadata": {field: entry[field] for field in ("title", "authors", "date") if field in entry},
            **store_html(path.read_bytes(), destination),
        })
        if index % 100 == 0:
            print(f"Prepared LegoNews: {index}/{len(entries)}", flush=True)
    return records


def prepare_scrapinghub(source, destination):
    truth = json.loads((source / "ground-truth.json").read_text(encoding="utf-8"))
    records = []
    for index, (identifier, entry) in enumerate(sorted(truth.items()), start=1):
        with gzip.open(source / "html" / f"{identifier}.html.gz", "rb") as stream:
            html = store_html(stream.read(), destination)
        records.append({
            "id": f"scrapinghub/{identifier}", "corpus": "scrapinghub", "split": "standard",
            "page_type": "article", "url": entry.get("url", ""),
            "reference_text": entry["articleBody"], "metadata": {}, **html,
        })
        if index % 100 == 0:
            print(f"Prepared ScrapingHub: {index}/{len(truth)}", flush=True)
    return records


def prepare_wcxb(source, destination):
    records = []
    for split in ("dev", "test"):
        for path in sorted((source / split / "ground-truth").glob("*.json")):
            entry = json.loads(path.read_text(encoding="utf-8"))
            truth = entry["ground_truth"]
            page_type = (entry.get("_internal") or {}).get("page_type", "article")
            if isinstance(page_type, dict):
                page_type = page_type.get("primary", "article")
            with gzip.open(source / split / "html" / f"{path.stem}.html.gz", "rb") as stream:
                html = store_html(stream.read(), destination)
            records.append({
                "id": f"wcxb/{split}/{path.stem}", "corpus": "wcxb", "split": split,
                "page_type": "collection" if page_type == "category" else page_type,
                "url": entry.get("url", ""), "reference_text": truth.get("main_content") or "",
                "with": truth.get("with") or [], "without": truth.get("without") or [],
                "metadata": {
                    "title": truth.get("title"), "authors": truth.get("author"),
                    "date": truth.get("publish_date"),
                },
                **html,
            })
            if len(records) % 100 == 0:
                print(f"Prepared WCXB: {len(records)}", flush=True)
    return records


def mark_overlaps(records):
    seen_html = {}
    seen_url = {}
    overlaps = []
    for record in records:
        matches = {}
        digest = record["html_sha256"]
        address = url_key(record["url"])
        if digest in seen_html:
            matches["html_sha256"] = seen_html[digest]
        if address and address in seen_url:
            matches["normalized_url"] = seen_url[address]
        record["overlaps"] = matches
        record["duplicate_of"] = matches.get("html_sha256") or matches.get("normalized_url")
        if matches:
            overlaps.append({"id": record["id"], "matches": matches})
        seen_html.setdefault(digest, record["id"])
        if address:
            seen_url.setdefault(address, record["id"])
    return overlaps


def prepare(destination, go):
    registry = json.loads((ROOT / "benchmarks.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    source, saved = fetch_source("legonews", registry["sources"]["legonews"], destination)
    datasets = {"legonews": prepare_legonews(source, destination, go)}
    provenance = {"legonews": {
        "data_go_sha256": sha256(source / "data.go"),
        **{field: saved[field] for field in ("revision", "archive_sha256")},
    }}
    for name, loader in (("scrapinghub", prepare_scrapinghub), ("wcxb", prepare_wcxb)):
        source, saved = fetch_source(name, registry["sources"][name], destination)
        print(f"Preparing {name} inputs and annotations", flush=True)
        datasets[name] = loader(source, destination)
        provenance[name] = {field: saved[field] for field in ("revision", "archive_sha256")}
    records = [record for group in datasets.values() for record in group]
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("Corpus identifiers are not unique")
    overlaps = mark_overlaps(records)
    manifest = {"schema_version": 1, "registry_sha256": sha256(ROOT / "benchmarks.json"), "corpora": {}}
    for name, dataset in datasets.items():
        expected = registry["sources"][name]["expected_records"]
        if len(dataset) != expected:
            raise ValueError(f"{name}: expected {expected} records, found {len(dataset)}")
        splits = dict(Counter(record["split"] for record in dataset))
        expected_splits = registry["sources"][name].get("expected_splits")
        if expected_splits and splits != expected_splits:
            raise ValueError(f"{name}: unexpected split counts: {splits}")
        path = destination / f"{name}.json"
        write_json(path, dataset)
        manifest["corpora"][name] = {
            "source": registry["sources"][name], "provenance": provenance[name],
            "records": len(dataset), "splits": splits, "sha256": sha256(path),
            "distinct_html": len({record["html_sha256"] for record in dataset}),
            "overlapping_records": sum(bool(record["duplicate_of"]) for record in dataset),
            "test_without_prior_match": sum(record["split"] == "test" and not record["duplicate_of"] for record in dataset),
            "annotated_metadata": {
                field: sum(bool(record["metadata"].get(field)) for record in dataset)
                for field in ("authors", "title", "date")
            },
        }
        print(f"{registry['sources'][name]['name']}: {len(dataset)} records; splits={splits}", flush=True)
    manifest["distinct_html"] = len({record["html_sha256"] for record in records})
    manifest["overlaps"] = overlaps
    write_json(destination / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--go", default="go", help="Go executable for the standard-library-only LegoNews fixture exporter")
    arguments = parser.parse_args()
    manifest = prepare(arguments.data.resolve(), arguments.go)
    print(f"Prepared {manifest['distinct_html']} distinct HTML byte sequences; provenance: {arguments.data / 'manifest.json'}")


if __name__ == "__main__":
    main()