"""Run and score LegoNews, ScrapingHub, WCXB, and Metadata independently."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from evaluate import (
    author_units, legonews_metrics, metadata_metrics, normalized,
    scrapinghub_metrics, scrapinghub_page, snippet_counts, wcxb_metrics, wcxb_page,
)
from prepare import DEFAULT_DATA, ROOT, sha256, write_json


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def load_records(directory):
    manifest = read_json(directory / "manifest.json")
    if manifest["registry_sha256"] != sha256(ROOT / "benchmarks.json"):
        raise ValueError("Benchmark definitions changed; rerun prepare.py")
    records = []
    for name in ("legonews", "scrapinghub", "wcxb"):
        path = directory / f"{name}.json"
        if sha256(path) != manifest["corpora"][name]["sha256"]:
            raise ValueError(f"Prepared annotations changed: {name}; rerun prepare.py")
        records.extend(read_json(path))
    return records, manifest


def select_records(records, split="dev", upstream=False):
    return [
        record for record in records
        if (record["corpus"] != "wcxb" or record["split"] == split)
        and (upstream or not record.get("duplicate_of"))
    ]


def validate_predictions(predictions, records):
    if not isinstance(predictions, dict):
        raise ValueError("predictions must be an object keyed by benchmark record ID")
    expected = {record["id"] for record in records}
    actual = set(predictions)
    if actual != expected:
        raise ValueError(
            f"Prediction IDs differ: {len(expected - actual)} missing, {len(actual - expected)} extra. "
            "Include errors as empty text; do not drop failed pages."
        )
    for identifier, prediction in predictions.items():
        if not isinstance(prediction, dict) or not isinstance(prediction.get("text"), str):
            raise ValueError(f"{identifier}: prediction requires a text string")
        if not isinstance(prediction.get("error", ""), str):
            raise ValueError(f"{identifier}: error must be a string")
        if prediction.get("error") and prediction["text"]:
            raise ValueError(f"{identifier}: failed extraction must have empty text")
        metadata = prediction.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"{identifier}: metadata must be an object")
        author_units(metadata.get("authors"))
        for field in ("title", "date"):
            normalized(metadata.get(field) or "")


def score_text(name, records, predictions):
    rows = []
    by_type = defaultdict(list)
    for record in records:
        text = predictions[record["id"]]["text"]
        if name == "legonews":
            metrics = snippet_counts(text, record["with"], record["without"])
        elif name == "scrapinghub":
            metrics = scrapinghub_page(text, record["reference_text"])
        else:
            metrics = wcxb_page(text, record["reference_text"])
        rows.append({"id": record["id"], "page_type": record["page_type"], **metrics})
        by_type[record["page_type"]].append(metrics)
    aggregate = {
        "legonews": legonews_metrics,
        "scrapinghub": scrapinghub_metrics,
        "wcxb": wcxb_metrics,
    }[name]
    return {
        "pages": len(records),
        "errors": sum(bool(predictions[record["id"]].get("error")) for record in records),
        "empty_outputs": sum(not predictions[record["id"]]["text"] for record in records),
        "overall": aggregate(rows),
        "per_type": {page_type: {"pages": len(values), **aggregate(values)} for page_type, values in sorted(by_type.items())},
        "per_page": rows,
    }


def score_metadata(records, predictions):
    groups = defaultdict(list)
    page_rows = []
    for record in records:
        if record["corpus"] not in ("legonews", "wcxb"):
            continue
        pair = (record["metadata"], predictions[record["id"]].get("metadata", {}))
        groups[record["corpus"]].append(pair)
        page_rows.append({"id": record["id"], "corpus": record["corpus"], "fields": metadata_metrics([pair])})
    return {
        "annotation_policy": "Nonempty supplied annotations only; unannotated is not a negative label.",
        "per_corpus": {name: metadata_metrics(pairs) for name, pairs in sorted(groups.items())},
        "overall": metadata_metrics([pair for pairs in groups.values() for pair in pairs]),
        "per_page": page_rows,
    }


def score(records, predictions):
    validate_predictions(predictions, records)
    reports = {
        name: score_text(name, [record for record in records if record["corpus"] == name], predictions)
        for name in ("legonews", "scrapinghub", "wcxb")
    }
    reports["metadata"] = score_metadata(records, predictions)
    return reports


def input_digest(records):
    identities = [{"id": record["id"], "html_sha256": record["html_sha256"]} for record in records]
    return hashlib.sha256(json.dumps(identities, sort_keys=True).encode("utf-8")).hexdigest()


def extractor_input(records, directory):
    requests = []
    print(f"Verifying {len(records)} extractor inputs", flush=True)
    for index, record in enumerate(records, start=1):
        path = (directory / record["html_path"]).resolve()
        if not path.is_relative_to(directory.resolve()) or sha256(path) != record["html_sha256"]:
            raise ValueError(f"HTML input changed: {record['id']}")
        requests.append(json.dumps({"id": record["id"], "url": record["url"], "html_path": str(path)}))
        if index % 100 == 0:
            print(f"Verified extractor inputs: {index}/{len(records)}", flush=True)
    return "\n".join(requests) + "\n"


def parse_predictions(output, records):
    predictions = {}
    for line in output.splitlines():
        prediction = json.loads(line, object_pairs_hook=unique_object)
        if not isinstance(prediction, dict):
            raise ValueError("Extractor responses must be JSON objects")
        identifier = prediction.pop("id", None)
        if not isinstance(identifier, str) or identifier in predictions:
            raise ValueError(f"Invalid or duplicate response ID: {identifier!r}")
        predictions[identifier] = prediction
    validate_predictions(predictions, records)
    return predictions


def run_extractor(command, records, directory, timeout):
    requests = extractor_input(records, directory)
    print(f"Running extractor on {len(records)} inputs", flush=True)
    process = subprocess.run(
        command, input=requests, capture_output=True,
        encoding="utf-8", timeout=timeout, check=False,
    )
    if process.stderr:
        print(process.stderr, file=sys.stderr, end="")
    if process.returncode:
        raise ValueError(f"Extractor exited with status {process.returncode}; no complete run saved")
    return parse_predictions(process.stdout, records)


def require_provenance(envelope, manifest, records, split, upstream):
    for field in ("name", "version", "profile"):
        if not isinstance(envelope.get(field), str) or not envelope[field].strip():
            raise ValueError(f"Prediction envelope requires {field}")
    if not isinstance(envelope.get("options"), dict):
        raise ValueError("Prediction envelope requires an options object")
    expected = {
        "registry_sha256": manifest["registry_sha256"],
        "corpora_sha256": {name: entry["sha256"] for name, entry in manifest["corpora"].items()},
        "input_sha256": input_digest(records),
        "wcxb_split": split,
        "upstream_records": upstream,
    }
    if envelope.get("benchmark") != expected:
        raise ValueError("Prediction benchmark provenance differs from the selected inputs")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "evaluate", "inputs"):
        command_parser = subparsers.add_parser(action)
        command_parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
        command_parser.add_argument("--wcxb-split", choices=("dev", "test"), default="dev")
        command_parser.add_argument("--upstream-records", action="store_true", help="Retain duplicates for upstream comparison, not held-out claims")
        command_parser.add_argument("--output", type=Path, required=True)
        if action == "evaluate":
            command_parser.add_argument("--predictions", type=Path, required=True)
        if action == "run":
            command_parser.add_argument("--name", required=True)
            command_parser.add_argument("--version", required=True, help="Exact extractor release or source revision")
            command_parser.add_argument("--profile", required=True, help="For example core-only or native-fallbacks")
            command_parser.add_argument("--options", default="{}", help="Extractor options as a JSON object")
            command_parser.add_argument("--timeout", type=float, default=3600, help="Extractor-process timeout in seconds")
            command_parser.add_argument("--command", nargs=argparse.REMAINDER, required=True)
    arguments = parser.parse_args()
    all_records, manifest = load_records(arguments.data)
    records = select_records(all_records, arguments.wcxb_split, arguments.upstream_records)
    provenance = {
        "registry_sha256": manifest["registry_sha256"],
        "corpora_sha256": {name: entry["sha256"] for name, entry in manifest["corpora"].items()},
        "input_sha256": input_digest(records),
        "wcxb_split": arguments.wcxb_split,
        "upstream_records": arguments.upstream_records,
    }
    if arguments.action == "inputs":
        write_json(arguments.output, {
            "benchmark": provenance,
            "inputs": [{"id": record["id"], "url": record["url"], "html_path": str((arguments.data / record["html_path"]).resolve())} for record in records],
        })
        print(f"Wrote {len(records)} label-free inputs to {arguments.output}")
        return
    if arguments.action == "run":
        if not arguments.command:
            parser.error("--command requires an extractor executable")
        envelope = {
            "schema_version": 1, "name": arguments.name, "version": arguments.version,
            "profile": arguments.profile, "options": json.loads(arguments.options, object_pairs_hook=unique_object),
            "command": arguments.command, "benchmark": provenance,
        }
        require_provenance(envelope, manifest, records, arguments.wcxb_split, arguments.upstream_records)
        envelope["predictions"] = run_extractor(arguments.command, records, arguments.data, arguments.timeout)
        write_json(arguments.output, envelope)
        print(f"Saved {len(records)} predictions to {arguments.output}")
        return
    envelope = read_json(arguments.predictions)
    require_provenance(envelope, manifest, records, arguments.wcxb_split, arguments.upstream_records)
    reports = score(records, envelope["predictions"])
    output = {
        "schema_version": 1, "benchmark": provenance,
        "extractor": {field: envelope[field] for field in ("name", "version", "profile", "options")},
        "predictions_sha256": sha256(arguments.predictions),
        "sources": {name: entry["source"] for name, entry in manifest["corpora"].items()},
        "evaluations": reports,
    }
    write_json(arguments.output, output)
    for name in ("legonews", "scrapinghub", "wcxb"):
        report = reports[name]
        print(f"{name}: pages={report['pages']} errors={report['errors']} F1={report['overall']['f1']:.6f}")
    authors = reports["metadata"]["overall"]["authors"]
    print(f"metadata: author annotations={authors['annotated']} exact_match={authors['exact_match']} F1={authors['f1']}")
    print(f"Four separate evaluations written to {arguments.output}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error