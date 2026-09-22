"""Compare persistent unified workers with native parsing and extraction timers."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil

from benchmark import extractor_input, input_digest, load_records, parse_predictions, read_json, score, select_records, unique_object
from compare import CORPORA, PageProcess, balanced_orders, check_artifacts, keep_awake, load_scrapers, mean_page_time, power_status, prediction_digest, process_library, select_workloads
from prepare import DEFAULT_DATA, ROOT, sha256, write_json
from run_benchmark import check_sleep_events


ENGINES = ("readability", "domdistiller", "trafilatura")
STAGES = ("parse", *ENGINES)


def decode_response(raw, record, order):
    response = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    if response.get("id") != record["id"] or response.get("engine_order") != order:
        raise ValueError("Worker response ID or engine order differs from the request")
    if response.get("error"):
        raise ValueError(f"Worker input failure on {record['id']}: {response['error']}")
    timings = response.get("seconds", {})
    if set(timings) != set(STAGES) or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in timings.values()):
        raise ValueError("Worker requires four finite nonnegative native timings")
    outputs = response.get("predictions", {})
    if set(outputs) != set(ENGINES):
        raise ValueError("Worker requires a prediction from every engine")
    predictions = {
        engine: parse_predictions(json.dumps({"id": record["id"], **outputs[engine]}), [record])
        for engine in ENGINES
    }
    return timings, predictions


class SplitProcess(PageProcess):
    def exchange_split(self, payload, record, order):
        self.requests.put(payload)
        result = self.receive()
        if not result["raw"].endswith(b"\n"):
            raise ValueError("Worker response must be a flushed JSON line")
        return decode_response(result["raw"], record, order)


def stage_summary(runs, names, selected_rounds):
    return {
        name: {
            stage: mean_page_time([
                sample for sample in runs
                if sample["phase"] == "speed" and sample["worker"] == name
                and sample["stage"] == stage and sample["round"] in selected_rounds
            ]) for stage in STAGES
        } for name in names
    }


def paired_regressions(report, names, maximum_regression):
    pairs = {}
    for engine in ENGINES:
        previous = report["overall"][names[0]][engine]["total_seconds"]
        candidate = report["overall"][names[1]][engine]["total_seconds"]
        previous_all = report["all_passes"][names[0]][engine]["total_seconds"]
        candidate_all = report["all_passes"][names[1]][engine]["total_seconds"]
        per_pass = []
        for repeat in range(1, report["pass_selection"]["measured_passes"] + 1):
            totals = {name: math.fsum(sample["elapsed_seconds"] for sample in report["runs"]
                                     if sample["phase"] == "speed" and sample["worker"] == name
                                     and sample["stage"] == engine and sample["round"] == repeat) for name in names}
            per_pass.append({"round": repeat, "candidate_over_baseline": totals[names[1]] / totals[names[0]]})
        pairs[engine] = {
            "baseline": names[0], "candidate": names[1],
            "candidate_over_baseline": candidate / previous,
            "all_passes_candidate_over_baseline": candidate_all / previous_all,
            "per_pass": per_pass,
            "maximum_regression_fraction": maximum_regression,
            "within_limit": candidate / previous <= 1 + maximum_regression and candidate_all / previous_all <= 1 + maximum_regression,
        }
    return pairs


def run_split(arguments):
    if arguments.runs < 1 or arguments.warmups < 1 or not 1 <= arguments.best_passes <= arguments.runs:
        raise ValueError("Require positive runs/warmups and best-passes within measured runs")
    scrapers = load_scrapers(arguments.config.resolve())
    names = [scraper["name"] for scraper in scrapers]
    records, manifest = load_records(arguments.data)
    records = select_workloads(select_records(records), CORPORA, arguments.limit_per_corpus, arguments.seed)
    inputs = {request["id"]: request for request in map(json.loads, extractor_input(records, arguments.data).splitlines())}
    if not records:
        raise ValueError("No selected benchmark inputs")
    library = process_library()
    arguments.output.mkdir(parents=True, exist_ok=False)
    raw = arguments.output / "raw"
    raw.mkdir()
    report = {
        "schema_version": 1, "kind": "split-performance", "complete": False,
        "created_utc": datetime.now(timezone.utc).isoformat(), "workers": scrapers,
        "config_sha256": sha256(arguments.config),
        "controller_sha256": {name: sha256(ROOT / name) for name in ("split_compare.py", "compare.py", "benchmark.py", "evaluate.py", "prepare.py")},
        "benchmark": {"input_sha256": input_digest(records), "registry_sha256": manifest["registry_sha256"], "corpora": manifest["corpora"]},
        "selection": {"pages": len(records), "seed": arguments.seed, "limit_per_corpus": arguments.limit_per_corpus, "split": "dev"},
        "timing_scope": {
            "parse": "Native wall time for in-memory charset decoding and one shared HTML parse, after the entire file read has completed.",
            "extraction": "Native wall time for one engine including required working copies/conversions, extraction, native metadata, plain-text rendering and destruction of temporary article trees. Trafilatura fallback is always off.",
            "excluded": "File opening/reading, worker startup, request decoding, IPC, response JSON serialization, controller validation and quality scoring.",
        },
        "environment": {"platform": platform.platform(), "processor": platform.processor(), "logical_cpus": library.cpu_count(), "power_before": power_status(library)},
        "workloads": {corpus: {"pages": sum(record["corpus"] == corpus for record in records), "input_sha256": input_digest([record for record in records if record["corpus"] == corpus])} for corpus in CORPORA},
        "runs": [], "pass_diagnostics": [], "quality": {}, "output_differences": {engine: [] for engine in ENGINES},
        "raw_data_included": False,
    }
    report["build_receipts"] = {}
    for scraper in scrapers:
        receipts = [Path(path) for path in scraper["artifacts_sha256"] if Path(path).name == "build.json"]
        if len(receipts) == 1:
            receipt = read_json(receipts[0])
            if receipt.get("binary_sha256") != sha256(Path(scraper["command"][0])):
                raise ValueError("Split build receipt does not match worker binary")
            report["build_receipts"][scraper["name"]] = receipt
    references = {name: {engine: {} for engine in ENGINES} for name in names}
    quality = {name: {engine: {} for engine in ENGINES} for name in names}
    observation_hash = hashlib.sha256()
    observations = 0
    phases = {"warmup": arguments.warmups, "speed": arguments.runs}
    try:
        with ExitStack() as stack:
            stack.enter_context(keep_awake(arguments.keep_awake))
            workers = {scraper["name"]: stack.enter_context(SplitProcess(scraper, raw / scraper["name"], arguments.timeout, library)) for scraper in scrapers}
            report["processes"] = {name: worker.process.pid for name, worker in workers.items()}
            for phase, count in phases.items():
                for repeat in range(1, count + 1):
                    totals = {(name, corpus, stage): [] for name in names for corpus in CORPORA for stage in STAGES}
                    positions = {name: [0] * len(names) for name in names}
                    engine_positions = {engine: [0] * len(ENGINES) for engine in ENGINES}
                    cpu_before = {name: worker.process.cpu_times() for name, worker in workers.items()}
                    print(f"Split {phase}: pass {repeat}/{count}, {len(records)} pages", flush=True)
                    for page_index, record in enumerate(records, 1):
                        identifier = record["id"]
                        worker_order = balanced_orders(names, count, f"{arguments.seed}:{phase}:workers:{identifier}")[repeat - 1]
                        engine_order = balanced_orders(list(ENGINES), count, f"{arguments.seed}:{phase}:engines:{identifier}")[repeat - 1]
                        payload = (json.dumps({**inputs[identifier], "engine_order": engine_order}) + "\n").encode("utf-8")
                        for position, engine in enumerate(engine_order):
                            engine_positions[engine][position] += 1
                        for position, name in enumerate(worker_order):
                            seconds, predictions = workers[name].exchange_split(payload, record, engine_order)
                            positions[name][position] += 1
                            for engine in ENGINES:
                                digest = prediction_digest(predictions[engine])
                                if phase == "warmup" and repeat == 1:
                                    references[name][engine][identifier] = digest
                                    quality[name][engine].update(predictions[engine])
                                if references[name][engine][identifier] != digest:
                                    raise ValueError(f"Unstable {name}/{engine} output on {identifier}")
                            for stage, elapsed in seconds.items():
                                totals[name, record["corpus"], stage].append(elapsed)
                            observation_hash.update(json.dumps({"id": identifier, "phase": phase, "round": repeat, "worker": name, "position": position, "engine_order": engine_order, "seconds": seconds}, sort_keys=True).encode("utf-8"))
                            observations += 1
                        if page_index % 100 == 0 or page_index == len(records):
                            print(f"Split {phase}: pass {repeat}/{count}, pages {page_index}/{len(records)}", flush=True)
                    for (name, corpus, stage), values in totals.items():
                        if values:
                            report["runs"].append({"worker": name, "corpus": corpus, "stage": stage, "phase": phase, "round": repeat, "pages": len(values), "elapsed_seconds": math.fsum(values)})
                    cpu_after = {name: worker.process.cpu_times() for name, worker in workers.items()}
                    report["pass_diagnostics"].append({
                        "phase": phase, "round": repeat, "worker_positions": positions, "engine_positions": engine_positions,
                        "process_cpu_seconds": {name: cpu_after[name].user + cpu_after[name].system - cpu_before[name].user - cpu_before[name].system for name in names},
                        "power_after": power_status(library),
                    })
                    for scraper in scrapers:
                        check_artifacts(scraper)
            for name in names:
                report["quality"][name] = {}
                for engine in ENGINES:
                    evaluations = score(records, quality[name][engine])
                    for evaluation in evaluations.values():
                        evaluation.pop("per_page", None)
                    report["quality"][name][engine] = {"evaluations": evaluations, "prediction_digest": prediction_digest(quality[name][engine])}
            for engine in ENGINES:
                report["output_differences"][engine] = [record["id"] for record in records if len({references[name][engine][record["id"]] for name in names}) != 1]
        ranking = sorted(range(1, arguments.runs + 1), key=lambda repeat: (math.fsum(sample["elapsed_seconds"] for sample in report["runs"] if sample["phase"] == "speed" and sample["stage"] != "parse" and sample["round"] == repeat), repeat))
        selected = sorted(ranking[:arguments.best_passes])
        report["pass_selection"] = {"measured_passes": arguments.runs, "reported_passes": arguments.best_passes, "selected_rounds": selected, "ranking": ranking, "metric": "Combined extraction wall time across all workers, engines and corpora; identical full rounds for every row."}
        report["overall"] = stage_summary(report["runs"], names, selected)
        report["all_passes"] = stage_summary(report["runs"], names, list(range(1, arguments.runs + 1)))
        if len(names) == 2:
            report["paired_extraction"] = paired_regressions(report, names, arguments.maximum_regression)
        report["audit"] = {"passed": True, "observations": observations, "timed_observations": len(records) * len(names) * arguments.runs, "timings_per_observation": 4, "warmup_passes": arguments.warmups, "timed_passes": arguments.runs, "observations_sha256": observation_hash.hexdigest(), "scope": "Every input checksum, response ID, engine order, four timers, complete pass, repeated scored prediction and executable identity checked; quality scores recomputed. All pass totals retained."}
        report["complete"] = True
        report["environment"]["power_after"] = power_status(library)
        report["environment"]["sleep_check"] = check_sleep_events(datetime.fromisoformat(report["created_utc"]), datetime.now(timezone.utc))
        write_json(arguments.output / "split-performance.json", report)
        lines = ["# Split Parsing and Extraction", "", "| Worker | Engine | Parse ms/page (shared) | Extraction ms/page |", "| --- | --- | ---: | ---: |"]
        for name in names:
            for engine in ENGINES:
                lines.append(f"| {name} | {engine} | {report['overall'][name]['parse']['mean_ms_per_page']:.6f} | {report['overall'][name][engine]['mean_ms_per_page']:.6f} |")
        lines.extend(["", f"Selected complete passes: {selected}; all measured passes remain in the JSON.", "Parsing is charged once per worker/page, not once per engine."])
        (arguments.output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines), flush=True)
        return report
    finally:
        shutil.rmtree(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--best-passes", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--maximum-regression", type=float, default=0.05)
    parser.add_argument("--limit-per-corpus", type=int)
    parser.add_argument("--keep-awake", action=argparse.BooleanOptionalAction, default=os.name == "nt")
    run_split(parser.parse_args())


if __name__ == "__main__":
    main()