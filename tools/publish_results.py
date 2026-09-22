"""Audit a completed quality or paired run and export summaries without raw observations."""

import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark import input_digest, load_records, parse_predictions, read_json, score, select_records
from compare import CORPORA, balanced_orders, export_results, mean_page_time, prediction_digest, select_workloads, summarize
from prepare import DEFAULT_DATA, sha256, write_json


def artifact(directory, name, expected=None):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError(f"Missing or unsafe evidence path: {name}")
    if expected is not None and sha256(path) != expected:
        raise ValueError(f"Evidence checksum differs: {name}")
    return path


def audit_predictions(directory, report, name, inputs, records):
    quality = report["quality"][name]
    path = artifact(directory, quality["output"], quality["output_sha256"])
    predictions = parse_predictions(path.read_text(encoding="utf-8"), inputs)
    if prediction_digest(predictions) != quality["prediction_digest"]:
        raise ValueError(f"Quality digest differs: {name}")
    if records is not None and score(records, predictions) != quality["evaluations"]:
        raise ValueError(f"Quality scores differ from saved predictions: {name}")
    return predictions


def audit_run(directory, report, records=None):
    if not report["complete"]:
        raise ValueError("Publication audit requires a complete comparison")
    names = [scraper["name"] for scraper in report["scrapers"]]
    inputs = [{"id": identifier, "corpus": corpus} for corpus in CORPORA if corpus in report["workloads"] for identifier in report["workloads"][corpus]["ids"]]
    if not inputs or len({record["id"] for record in inputs}) != len(inputs) or len(set(names)) != len(names):
        raise ValueError("Comparison contains missing or duplicate input/scraper identities")
    if records is not None and [record["id"] for record in records] != [record["id"] for record in inputs]:
        raise ValueError("Scoring records differ from measured inputs")
    if report["mode"] == "quality":
        if report["runs"]:
            raise ValueError("A quality-only report cannot contain measured passes")
        for name in names:
            audit_predictions(directory, report, name, inputs, records)
        return {
            "passed": True, "pages": len(inputs), "engines": len(names),
            "warmup_passes": 0, "timed_passes": 0,
            "observations": len(inputs) * len(names), "timed_observations": 0,
            "scores_recomputed": records is not None,
            "scope": "All prediction IDs, output hashes and quality scores verified; quality-only run, no timing measurements.",
        }
    if report["timing"] != "page":
        raise ValueError("Publication audit requires a quality-only or persistent-page comparison")
    timing = report["page_timing"]
    phases = {"warmup": timing["warmup_passes"], "speed": timing["timed_passes"]}
    if any(count < 1 for count in phases.values()):
        raise ValueError("Both full warmup and timed passes are required")
    log = artifact(directory, timing["observations"], timing["observations_sha256"])
    totals = defaultdict(list)
    positions = {name: [0] * len(names) for name in names}
    observations = 0
    with log.open(encoding="utf-8") as stream:
        for phase, count in phases.items():
            schedules = {record["id"]: balanced_orders(names, count, f"{report['selection']['seed']}:{phase}:{record['id']}") for record in inputs}
            for round_index in range(1, count + 1):
                for page_index, record in enumerate(inputs, start=1):
                    order = schedules[record["id"]][round_index - 1]
                    for position, name in enumerate(order, start=1):
                        line = stream.readline()
                        if not line:
                            raise ValueError("Page observations are incomplete")
                        sample = json.loads(line)
                        expected = {
                            "id": record["id"], "corpus": record["corpus"], "phase": phase,
                            "round": round_index, "page_index": page_index, "position": position,
                            "scraper": name, "pid": timing["processes"][name]["pid"], "stable": True,
                        }
                        if any(sample.get(key) != value for key, value in expected.items()):
                            raise ValueError(f"Page schedule, process or stability differs: {record['id']}, {phase}, {round_index}, {name}")
                        if any(not isinstance(sample.get(key), (int, float)) or not math.isfinite(sample[key]) or sample[key] < 0 for key in ("elapsed_seconds", "wall_seconds")):
                            raise ValueError("Invalid request timing")
                        totals[phase, record["corpus"], round_index, name].append(sample["elapsed_seconds"])
                        observations += 1
                        if phase == "speed":
                            positions[name][position - 1] += 1
        if stream.read():
            raise ValueError("Unexpected extra page observations")
    runs = [item for item in report["runs"] if item["phase"] in phases]
    if len(runs) != len(totals):
        raise ValueError("Pass totals are incomplete or duplicated")
    verified = set()
    for run in runs:
        key = run["phase"], run["corpus"], run["round"], run["scraper"]
        samples = totals.get(key, [])
        if key in verified or not run["stable"] or run["pages"] != len(samples) or not math.isclose(run["elapsed_seconds"], math.fsum(samples), rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError(f"Pass total differs from raw observations: {key}")
        verified.add(key)
    for name in names:
        measured = mean_page_time([item for item in runs if item["phase"] == "speed" and item["scraper"] == name])
        if report["overall_speed"][name] != measured:
            raise ValueError(f"Page-weighted mean differs: {name}")
        predictions = audit_predictions(directory, report, name, inputs, records)
        reference = {identifier: prediction_digest({identifier: prediction}) for identifier, prediction in predictions.items()}
        session = timing["processes"][name]
        path = artifact(directory, session["output"], session["output_sha256"])
        with path.open(encoding="utf-8") as stream:
            for _ in range(sum(phases.values())):
                for record in inputs:
                    line = stream.readline()
                    if not line or prediction_digest(parse_predictions(line, [record])) != reference[record["id"]]:
                        raise ValueError(f"Session prediction differs: {name}, {record['id']}")
            if stream.read():
                raise ValueError(f"Unexpected extra session responses: {name}")
    return {
        "passed": True, "pages": len(inputs), "engines": len(names),
        "warmup_passes": phases["warmup"], "timed_passes": phases["speed"],
        "observations": observations, "timed_observations": phases["speed"] * len(inputs) * len(names),
        "position_counts": positions, "scores_recomputed": records is not None,
        "scope": "All page IDs, schedules, positions, persistent PIDs, pass totals, weighted means, output hashes and repeated scored predictions verified; no trimming.",
    }


def select_best_passes(report, count):
    if report.get("kind") != "performance" or report.get("timing") != "page":
        raise ValueError("Best-pass selection requires a persistent-page performance summary")
    measured_passes = report["page_timing"]["timed_passes"]
    if not isinstance(count, int) or not 1 <= count <= measured_passes:
        raise ValueError("Best-pass count must be between one and the number of measured passes")
    names = [scraper["name"] for scraper in report["scrapers"]]
    expected = {(corpus, name) for corpus in report["workloads"] for name in names}
    measured = [sample for sample in report["runs"] if sample["phase"] == "speed"]
    if {sample["round"] for sample in measured} != set(range(1, measured_passes + 1)):
        raise ValueError("Best-pass selection requires all measured rounds")
    ranking = []
    for round_index in range(1, measured_passes + 1):
        samples = [sample for sample in measured if sample["round"] == round_index]
        if len(samples) != len(expected) or {(sample["corpus"], sample["scraper"]) for sample in samples} != expected:
            raise ValueError("Best-pass selection requires every engine and corpus in each round")
        if any(not sample["stable"] or sample["pages"] != report["workloads"][sample["corpus"]]["pages"]
               or not math.isfinite(sample["elapsed_seconds"]) or sample["elapsed_seconds"] < 0 for sample in samples):
            raise ValueError("Best-pass selection requires complete stable passes with valid timings")
        ranking.append({"round": round_index, "total_request_seconds": math.fsum(sample["elapsed_seconds"] for sample in samples)})
    ranking.sort(key=lambda entry: (entry["total_request_seconds"], entry["round"]))
    selected = sorted(entry["round"] for entry in ranking[:count])
    reported = [sample for sample in measured if sample["round"] in selected]
    selected_report = {**report, "runs": [sample for sample in report["runs"] if sample["phase"] != "speed"] + reported}
    return {
        **report, "summary": summarize(selected_report),
        "overall_speed": {name: mean_page_time([sample for sample in reported if sample["scraper"] == name]) for name in names},
        "pass_selection": {
            "method": "fastest_shared_complete_passes", "measured_passes": measured_passes,
            "reported_passes": count, "selected_rounds": selected,
            "excluded_rounds": [round_index for round_index in range(1, measured_passes + 1) if round_index not in selected],
            "ranking_metric": "Summed request wall seconds across all engines and corpora; ties use original round order.",
            "ranking": ranking,
            "caveat": "Best-of-N selection is an optimistic estimate, not the all-pass average. The same complete passes are used for every engine; all original pass totals and the full-run audit remain unchanged.",
        },
        "scope": "Only within-run comparisons. Reported latency is weighted by pages in the selected fastest complete shared passes. No within-pass observations are dropped, no CPU time is substituted, and no measurements from other runs are pooled. All original pass totals remain in runs.",
    }


def publish_results(directory, destination, publication_date, records=None, discard_raw=False, performance_invalid_reason=None, host_check=None, best_passes=None):
    directory, destination = directory.resolve(), destination.resolve()
    if discard_raw and (destination.is_relative_to(directory) or ROOT.is_relative_to(directory)):
        raise ValueError("Summary output must be outside the raw run directory before discarding it")
    stamp = date.fromisoformat(publication_date).strftime("%Y_%m_%d")
    report = read_json(directory / "comparison.json")
    if best_passes is not None and (report["timing"] != "page" or not 1 <= best_passes <= report["page_timing"]["timed_passes"]):
        raise ValueError("Best-pass selection requires page timing and a count within the measured passes")
    names = [f"quality_{stamp}.json"]
    if any(item["phase"] == "speed" for item in report["runs"]):
        names.append(f"performance_{stamp}.json")
    if any((destination / name).exists() for name in names):
        raise FileExistsError("Dated result files already exist; refusing to overwrite published summaries")
    audit = audit_run(directory, report, records)
    for name, expected in report["controller_sha256"].items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"Measured harness source changed before publication: {name}")
    export_results(directory, report, publication_date)
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        value = read_json(directory / name)
        if value["kind"] == "performance":
            if host_check is not None:
                value["environment"]["sleep_check"] = host_check
                if host_check["status"] == "interrupted" and not performance_invalid_reason:
                    performance_invalid_reason = "Windows sleep/resume events were recorded during this run. Wall-time measurements are invalid for speed comparisons; no samples were trimmed or replaced with CPU time."
            value["performance_validity"] = {
                "status": "invalid" if performance_invalid_reason else "unreviewed",
                "reason": performance_invalid_reason or "Data audit passed; host interruptions and timing conditions still require review.",
            }
            if best_passes is not None:
                value = select_best_passes(value, best_passes)
        for quality in value.get("quality", {}).values():
            quality.pop("output", None)
            for evaluation in quality["evaluations"].values():
                evaluation.pop("per_page", None)
        timing = value.get("page_timing")
        if timing is not None:
            timing.pop("observations", None)
            timing["schedule"] = "Per-page seeded balanced_orders with fixed page order; actual orders and persistent PIDs were audited before export. Raw observations are not included."
            for session in timing["processes"].values():
                session.pop("output", None)
                session.pop("stderr", None)
        write_json(destination / name, {
            **value, "audit": audit, "raw_data_included": False,
            "retention": "Aggregate scores, per-pass totals, diagnostics, provenance and audit counts only. No per-page predictions, timing logs or evidence archive; hashes identify the audited transient data.",
        })
    if discard_raw:
        shutil.rmtree(directory)
    print(json.dumps({"files": names, "raw_run_discarded": discard_raw, "audit": audit}, indent=2), flush=True)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT, help="Local publication directory; no network upload is performed")
    parser.add_argument("--date", required=True, help="Publication label YYYY-MM-DD")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--discard-raw", action="store_true", help="Remove the raw run directory only after the audited summaries have been written outside it")
    parser.add_argument("--performance-invalid-reason", help="Mark timings invalid with this reason while retaining all aggregate measurements and quality scores")
    parser.add_argument("--best-passes", type=int, help="Report this many fastest complete shared passes; retain all original totals (default: all passes)")
    arguments = parser.parse_args()
    report = read_json(arguments.run / "comparison.json")
    records, manifest = load_records(arguments.data)
    selection = report["selection"]
    records = select_workloads(select_records(records, selection["wcxb_split"], selection["upstream_records"]), report["workloads"], selection["limit_per_corpus"], selection["seed"])
    if report["benchmark"]["input_sha256"] != input_digest(records) or report["benchmark"]["registry_sha256"] != manifest["registry_sha256"]:
        raise ValueError("Prepared inputs differ from the measured run")
    if report["benchmark"]["corpora_sha256"] != {name: entry["sha256"] for name, entry in manifest["corpora"].items()}:
        raise ValueError("Prepared annotations differ from the measured run")
    publish_results(arguments.run.resolve(), arguments.output.resolve(), arguments.date, records,
                    discard_raw=arguments.discard_raw, performance_invalid_reason=arguments.performance_invalid_reason,
                    best_passes=arguments.best_passes)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error)) from error