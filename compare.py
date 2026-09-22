"""Compare JSONL scrapers on quality, warm per-page speed, and process memory."""

import argparse
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time

from benchmark import (
    extractor_input, input_digest, load_records, parse_predictions, read_json,
    score, select_records,
)
from evaluate import author_units, normalized
from prepare import DEFAULT_DATA, ROOT, sha256, write_json


CORPORA = ("legonews", "scrapinghub", "wcxb")
TIMING_SCOPE = (
    "Fresh-process batch wall time: launch, runtime/model initialization, input JSONL, "
    "HTML file reads, parsing, extraction, metadata, rendering, output JSONL and exit. "
    "Excludes build, input verification, output validation and quality scoring. "
    "Filesystem cache is warmed; this is not DOM-only or cold-start latency."
)
PAGE_TIMING_SCOPE = (
    "Persistent-process per-page request wall time: sending/flushing one JSONL request "
    "through receiving its complete response, including IPC, HTML file reads, parsing, "
    "extraction, metadata and rendering. All scrapers finish the same page serially "
    "before advancing, in seeded per-page order balanced across complete schedule blocks. "
    "Processes stay alive through full-corpus warmup and all timed passes. "
    "Excludes startup, warmup, validation, scoring and controller bookkeeping. "
    "Mean milliseconds/page = summed timed request seconds * 1000 / page observations. "
    "Not DOM-only time; co-resident runtimes and background GC can still affect timing."
)
MEMORY_SCOPE = (
    "Sampled maximum sum of RSS for the scraper process and live descendants, "
    "in separate fresh-process runs. Includes runtime/models/file buffers; excludes "
    "the controller. Sampling can miss short peaks; shared pages can be counted "
    "in more than one process. Not allocated bytes, heap size, or exact OS peak RSS."
)


def process_library():
    try:
        return importlib.import_module("psutil")
    except ImportError as error:
        raise ValueError("Install performance dependencies: python -m pip install -r requirements-performance.txt") from error


@contextmanager
def keep_awake(enabled):
    if not enabled:
        yield
        return
    if os.name != "nt":
        raise ValueError("--keep-awake uses the Windows execution-state API; use your OS power controls on other platforms")
    import ctypes
    function = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
    function.argtypes = [ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    previous = function(0x80000003)
    if not previous:
        raise OSError(ctypes.get_last_error(), "Cannot request Windows system/display wakefulness")
    try:
        yield
    finally:
        if not function(previous):
            raise OSError(ctypes.get_last_error(), "Cannot restore Windows execution state")


def power_status(library):
    battery = library.sensors_battery() if hasattr(library, "sensors_battery") else None
    return {"percent": battery.percent, "plugged_in": battery.power_plugged} if battery else None


def load_scrapers(path, names=None):
    config = read_json(path)
    if not isinstance(config, dict) or config.get("schema_version") != 1 or not isinstance(config.get("scrapers"), list) or not config["scrapers"]:
        raise ValueError("Comparison config requires schema_version 1 and a nonempty scrapers array")
    scrapers = []
    seen = set()
    for definition in config["scrapers"]:
        if not isinstance(definition, dict):
            raise ValueError("Each scraper definition must be an object")
        name = definition.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in seen:
            raise ValueError(f"Invalid or duplicate scraper name: {name!r}")
        seen.add(name)
        if names and name not in names:
            continue
        for field in ("version", "profile"):
            if not isinstance(definition.get(field), str) or not definition[field].strip():
                raise ValueError(f"{name}: requires {field}")
        if not isinstance(definition.get("options"), dict):
            raise ValueError(f"{name}: requires explicit options object")
        command = definition.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError(f"{name}: command must be a nonempty array, not a shell string")
        environment = definition.get("env", {})
        if not isinstance(environment, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()):
            raise ValueError(f"{name}: env must contain string values")
        if not isinstance(definition.get("cwd", "."), str):
            raise ValueError(f"{name}: cwd must be a path string")
        cwd = (path.parent / definition.get("cwd", ".")).resolve()
        if not cwd.is_dir():
            raise ValueError(f"{name}: working directory is missing: {cwd}")
        command = [part.replace("{exe}", ".exe" if os.name == "nt" else "") for part in command]
        executable = Path(command[0])
        if executable.is_absolute() or "/" in command[0] or "\\" in command[0]:
            executable = (cwd / executable).resolve()
        else:
            located = shutil.which(command[0], path=environment.get("PATH", os.environ.get("PATH")))
            if not located:
                raise ValueError(f"{name}: executable not found: {command[0]}")
            executable = Path(located).resolve()
        if not executable.is_file():
            raise ValueError(f"{name}: build the executable first: {executable}")
        command[0] = str(executable)
        artifacts = definition.get("artifacts", [])
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise ValueError(f"{name}: artifacts must list adapter scripts/build receipt paths")
        identities = {}
        for artifact in [executable, *((cwd / item).resolve() for item in artifacts)]:
            if not artifact.is_file():
                raise ValueError(f"{name}: missing identity artifact: {artifact}")
            identities[str(artifact)] = sha256(artifact)
        scraper = {
            "name": name, "version": definition["version"], "profile": definition["profile"],
            "options": definition["options"], "command": command, "cwd": str(cwd),
            "env": environment, "artifacts_sha256": identities,
        }
        if "build_receipt" in definition:
            receipt_path = (cwd / definition["build_receipt"]).resolve()
            if str(receipt_path) not in identities:
                raise ValueError(f"{name}: build receipt must be a hashed artifact")
            receipt = read_json(receipt_path)
            release = definition.get("release", {})
            if receipt.get("binary_sha256") != identities[str(executable)] or receipt.get("source", {}).get("commit") != release.get("commit"):
                raise ValueError(f"{name}: build receipt differs from executable or release commit")
            if receipt["source"].get("tag") != definition["version"] or release.get("tag") != definition["version"]:
                raise ValueError(f"{name}: build receipt differs from release version")
            scraper.update({"release": release, "build_receipt": receipt})
        scrapers.append(scraper)
    if names:
        unknown = set(names) - seen
        if unknown:
            raise ValueError(f"Unknown scraper names: {sorted(unknown)}")
        scrapers = [scraper for scraper in scrapers if scraper["name"] in names]
    return scrapers


def check_artifacts(scraper):
    for path, expected in scraper["artifacts_sha256"].items():
        if sha256(Path(path)) != expected:
            raise ValueError(f"Scraper artifact changed during comparison: {path}")


def balanced_orders(names, rounds, seed):
    if not names or rounds < 0 or len(set(names)) != len(names):
        raise ValueError("Schedule requires unique scraper names and nonnegative rounds")
    generator = random.Random(seed)
    orders = []
    while len(orders) < rounds:
        base = list(names)
        generator.shuffle(base)
        block = [base[index:] + base[:index] for index in range(len(base))]
        block.extend([list(reversed(order)) for order in block[:]])
        generator.shuffle(block)
        orders.extend(block)
    return orders[:rounds]


def select_workloads(records, corpora, limit, seed):
    selected = []
    for corpus in CORPORA:
        if corpus not in corpora:
            continue
        candidates = [record for record in records if record["corpus"] == corpus]
        if limit is not None and len(candidates) > limit:
            generator = random.Random(f"{seed}:{corpus}")
            indices = sorted(generator.sample(range(len(candidates)), limit))
            candidates = [candidates[index] for index in indices]
        selected.extend(candidates)
    return selected


def prediction_digest(predictions):
    values = {
        identifier: {
            "text": item["text"], "error": item.get("error", ""),
            "authors": sorted(author_units(item.get("metadata", {}).get("authors"))),
            "title": normalized(item.get("metadata", {}).get("title") or ""),
            "date": normalized(item.get("metadata", {}).get("date") or ""),
        }
        for identifier, item in predictions.items()
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


class MemorySampler:
    def __init__(self, process, library, interval):
        self.process = process
        self.library = library
        self.interval = interval
        self.peak = 0
        self.samples = 0
        self.failures = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        try:
            members = [self.process, *self.process.children(recursive=True)]
        except self.library.NoSuchProcess:
            return
        total = 0
        observed = False
        for member in members:
            try:
                total += member.memory_info().rss
                observed = True
            except self.library.NoSuchProcess:
                continue
            except self.library.AccessDenied as error:
                self.failures.append(str(error))
        if observed:
            self.peak = max(self.peak, total)
            self.samples += 1

    def run(self):
        try:
            self.sample()
            while not self.stopped.wait(self.interval):
                self.sample()
        except Exception as error:
            self.failures.append(str(error))

    def start(self):
        self.thread.start()

    def finish(self):
        self.stopped.set()
        self.thread.join()
        if self.failures or not self.samples:
            raise ValueError(f"Memory observation incomplete: samples={self.samples}, errors={self.failures}")
        return {"sampled_peak_tree_rss_bytes": self.peak, "samples": self.samples, "sample_interval_ms": self.interval * 1000}


def kill_process_tree(process, library):
    try:
        children = process.children(recursive=True)
    except library.NoSuchProcess:
        children = []
    for member in [*reversed(children), process]:
        try:
            member.kill()
        except library.NoSuchProcess:
            pass
    process.wait()
    library.wait_procs(children, timeout=5)


def execute(scraper, payload, records, prefix, timeout, library, memory_interval=None):
    check_artifacts(scraper)
    environment = os.environ.copy()
    environment.update(scraper["env"])
    output_path = Path(f"{prefix}.jsonl")
    error_path = Path(f"{prefix}.stderr")
    process = None
    sampler = None
    measurement = None
    with output_path.open("wb") as output, error_path.open("wb") as errors:
        wall_start = time.time_ns()
        monotonic_start = time.perf_counter_ns()
        try:
            process = library.Popen(
                scraper["command"], cwd=scraper["cwd"], env=environment,
                stdin=subprocess.PIPE, stdout=output, stderr=errors,
            )
            if memory_interval is not None:
                sampler = MemorySampler(process, library, memory_interval)
                sampler.start()
            process.communicate(input=payload, timeout=timeout)
            elapsed = (time.perf_counter_ns() - monotonic_start) / 1e9
            wall_elapsed = (time.time_ns() - wall_start) / 1e9
        except BaseException as error:
            if process is not None:
                try:
                    kill_process_tree(process, library)
                except Exception as cleanup_error:
                    error.add_note(f"Process cleanup also failed: {cleanup_error}")
            if sampler is not None:
                try:
                    sampler.finish()
                except Exception as sampling_error:
                    error.add_note(f"Memory observation also failed: {sampling_error}")
            raise
        else:
            if sampler is not None:
                measurement = sampler.finish()
    if process.returncode:
        raise ValueError(f"{scraper['name']} exited {process.returncode}; see {error_path}")
    if abs(wall_elapsed - elapsed) > max(1.0, elapsed * 0.05):
        raise ValueError("Wall and monotonic clocks diverged; possible sleep/clock change. Keep the partial run, then rerun awake.")
    predictions = parse_predictions(output_path.read_text(encoding="utf-8"), records)
    result = {
        "elapsed_seconds": elapsed, "wall_seconds": wall_elapsed, "pages": len(records),
        "pages_per_second": len(records) / elapsed,
        "prediction_digest": prediction_digest(predictions),
        "output": output_path.name, "output_sha256": sha256(output_path),
        "stderr": error_path.name, "memory": measurement,
    }
    return result, predictions


def distribution(values):
    return {"samples": len(values), "median": statistics.median(values), "minimum": min(values), "maximum": max(values)} if values else None


class PageProcess:
    def __init__(self, scraper, prefix, timeout, library):
        self.scraper = scraper
        self.prefix = prefix
        self.timeout = timeout
        self.library = library
        self.requests = queue.Queue()
        self.responses = queue.Queue()
        self.process = None

    def __enter__(self):
        check_artifacts(self.scraper)
        self.output_path = Path(f"{self.prefix}.jsonl")
        self.error_path = Path(f"{self.prefix}.stderr")
        self.output = self.output_path.open("wb")
        self.errors = self.error_path.open("wb")
        environment = {**os.environ, **self.scraper["env"]}
        try:
            self.process = self.library.Popen(
                self.scraper["command"], cwd=self.scraper["cwd"], env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
            )
            self.thread = threading.Thread(target=self.work, daemon=True)
            self.thread.start()
        except BaseException:
            self.output.close()
            self.errors.close()
            if self.process is not None:
                kill_process_tree(self.process, self.library)
            raise
        return self

    def work(self):
        try:
            while True:
                payload = self.requests.get()
                if payload is None:
                    self.process.stdin.close()
                    self.responses.put({"raw": self.process.stdout.read()})
                    return
                wall_start = time.time_ns()
                started = time.perf_counter_ns()
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                raw = self.process.stdout.readline()
                elapsed = (time.perf_counter_ns() - started) / 1e9
                wall_elapsed = (time.time_ns() - wall_start) / 1e9
                self.responses.put({"raw": raw, "elapsed_seconds": elapsed, "wall_seconds": wall_elapsed})
        except BaseException as error:
            self.responses.put(error)

    def receive(self):
        try:
            result = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            raise subprocess.TimeoutExpired(self.scraper["command"], self.timeout) from error
        if isinstance(result, BaseException):
            raise result
        self.output.write(result["raw"])
        return result

    def exchange(self, payload, record):
        self.requests.put(payload)
        result = self.receive()
        if not result["raw"].endswith(b"\n"):
            raise ValueError(f"{self.scraper['name']}: expected a flushed JSON line for {record['id']}; see {self.error_path}")
        if abs(result["wall_seconds"] - result["elapsed_seconds"]) > max(1.0, result["elapsed_seconds"] * 0.05):
            raise ValueError("Wall and monotonic clocks diverged during a page request; rerun awake")
        predictions = parse_predictions(result["raw"].decode("utf-8"), [record])
        result.pop("raw")
        return result, predictions

    def __exit__(self, error_type, error, traceback):
        self.requests.put(None)
        try:
            if error_type is None:
                remaining = self.receive()["raw"]
                self.process.wait(timeout=self.timeout)
                if self.process.returncode:
                    raise ValueError(f"{self.scraper['name']} exited {self.process.returncode}; see {self.error_path}")
                if remaining:
                    raise ValueError(f"{self.scraper['name']}: unexpected response after the last page")
            else:
                kill_process_tree(self.process, self.library)
        except BaseException as cleanup_error:
            kill_process_tree(self.process, self.library)
            if error is None:
                raise
            error.add_note(f"Process cleanup also failed: {cleanup_error}")
        finally:
            self.thread.join(timeout=self.timeout)
            for stream in (self.process.stdin, self.process.stdout, self.output, self.errors):
                try:
                    stream.close()
                except OSError:
                    pass


def run_page_comparison(arguments, scrapers, records, groups, inputs, report, library):
    names = [scraper["name"] for scraper in scrapers]
    references = {name: {} for name in names}
    quality_predictions = {name: {} for name in names}
    phases = {"warmup": arguments.warmups, "speed": arguments.runs}
    schedules = {
        phase: {record["id"]: balanced_orders(names, count, f"{arguments.seed}:{phase}:{record['id']}") for record in records}
        for phase, count in phases.items()
    }
    log_path = arguments.output / "page-timings.jsonl"
    report["page_timing"] = {
        "warmup_passes": arguments.warmups, "timed_passes": arguments.runs,
        "observations": log_path.name, "processes": {}, "pass_diagnostics": [],
        "position_balance_passes": 2 * len(names),
        "complete_position_balance": arguments.runs % (2 * len(names)) == 0,
        "schedule": "Per-page seeded balanced_orders; page order is fixed; actual order is retained with every observation.",
    }
    with ExitStack() as stack:
        stack.enter_context(keep_awake(getattr(arguments, "keep_awake", False)))
        log = stack.enter_context(log_path.open("w", encoding="utf-8"))
        workers = {
            scraper["name"]: stack.enter_context(PageProcess(scraper, arguments.output / f"session-{scraper['name']}", arguments.timeout, library))
            for scraper in scrapers
        }
        report["page_timing"]["processes"] = {
            name: {"pid": worker.process.pid, "output": worker.output_path.name, "stderr": worker.error_path.name}
            for name, worker in workers.items()
        }
        checkpoint(arguments.output, report)
        for phase, count in phases.items():
            for round_index in range(1, count + 1):
                pass_started = time.perf_counter()
                cpu_started = {name: worker.process.cpu_times() for name, worker in workers.items()}
                power_before = power_status(library)
                totals = {
                    (corpus, name): {"phase": phase, "corpus": corpus, "round": round_index, "scraper": name, "elapsed_seconds": 0.0, "wall_seconds": 0.0, "pages": 0, "stable": True, "memory": None}
                    for corpus in groups for name in names
                }
                print(f"Paired {phase}: pass {round_index}/{count}, {len(records)} pages", flush=True)
                for page_index, record in enumerate(records, start=1):
                    identifier = record["id"]
                    order = schedules[phase][identifier][round_index - 1]
                    observations = []
                    for position, name in enumerate(order, start=1):
                        timing, predictions = workers[name].exchange(inputs[identifier], record)
                        digest = prediction_digest(predictions)
                        if phase == "warmup" and round_index == 1:
                            references[name][identifier] = digest
                            quality_predictions[name].update(predictions)
                        timing.update({"id": identifier, "corpus": record["corpus"], "phase": phase, "round": round_index, "page_index": page_index, "position": position, "scraper": name, "pid": workers[name].process.pid, "stable": digest == references[name][identifier]})
                        observations.append(timing)
                        total = totals[record["corpus"], name]
                        total["elapsed_seconds"] += timing["elapsed_seconds"]
                        total["wall_seconds"] += timing["wall_seconds"]
                        total["pages"] += 1
                    for observation in observations:
                        log.write(json.dumps(observation) + "\n")
                    if any(not observation["stable"] for observation in observations):
                        report["failed_page"] = observations
                        raise ValueError(f"Persistent output differs from quality reference on {identifier}; comparison incomplete")
                    if page_index % 100 == 0 or page_index == len(records):
                        log.flush()
                        for worker in workers.values():
                            worker.output.flush()
                        print(f"Paired {phase}: pass {round_index}/{count}, pages {page_index}/{len(records)}", flush=True)
                cpu_finished = {name: worker.process.cpu_times() for name, worker in workers.items()}
                report["page_timing"]["pass_diagnostics"].append({
                    "phase": phase, "round": round_index, "wall_seconds": time.perf_counter() - pass_started,
                    "process_cpu_seconds": {
                        name: (cpu_finished[name].user + cpu_finished[name].system) - (cpu_started[name].user + cpu_started[name].system)
                        for name in names
                    },
                    "power_before": power_before, "power_after": power_status(library),
                })
                if phase == "warmup" and round_index == 1:
                    for name, predictions in quality_predictions.items():
                        path = arguments.output / f"quality-{name}.jsonl"
                        with path.open("w", encoding="utf-8") as output:
                            for identifier, prediction in predictions.items():
                                output.write(json.dumps({"id": identifier, **prediction}, ensure_ascii=False) + "\n")
                        report["quality"][name] = {"output": path.name, "output_sha256": sha256(path), "prediction_digest": prediction_digest(predictions), "evaluations": score(records, predictions)}
                for total in totals.values():
                    total["pages_per_second"] = total["pages"] / total["elapsed_seconds"]
                    report["runs"].append(total)
                for scraper in scrapers:
                    check_artifacts(scraper)
                checkpoint(arguments.output, report)
    report["page_timing"]["observations_sha256"] = sha256(log_path)
    for session in report["page_timing"]["processes"].values():
        session["output_sha256"] = sha256(arguments.output / session["output"])
    return {
        name: {corpus: prediction_digest({record["id"]: predictions[record["id"]] for record in group}) for corpus, group in groups.items()}
        for name, predictions in quality_predictions.items()
    }


def mean_page_time(runs):
    pages = sum(item["pages"] for item in runs)
    seconds = math.fsum(item["elapsed_seconds"] for item in runs)
    return {"page_observations": pages, "total_seconds": seconds, "mean_ms_per_page": seconds * 1000 / pages if pages else None}


def summarize(report):
    summary = {}
    for corpus in report["workloads"]:
        summary[corpus] = {}
        for scraper in report["scrapers"]:
            name = scraper["name"]
            speed = [item for item in report["runs"] if item["phase"] == "speed" and item["corpus"] == corpus and item["scraper"] == name and item["stable"]]
            memory = [item["memory"]["sampled_peak_tree_rss_bytes"] for item in report["runs"] if item["phase"] == "memory" and item["corpus"] == corpus and item["scraper"] == name and item["stable"]]
            time_key = "pass_seconds" if report.get("timing") == "page" else "batch_seconds"
            summary[corpus][name] = {time_key: distribution([item["elapsed_seconds"] for item in speed]), **mean_page_time(speed), "sampled_peak_tree_rss_bytes": distribution(memory)}
    return summary


def markdown_report(report):
    lines = ["# Scraper Comparison", "", f"Status: **{'complete' if report['complete'] else 'incomplete'}**. Mode: `{report['mode']}`.", ""]
    if report.get("error"):
        lines.extend([f"Failure: {report['error']}", ""])
    if report["selection"]["limit_per_corpus"] is not None:
        lines.extend(["**Smoke/sample run, not the full standard benchmarks.**", ""])
    lines.extend(["## Identity", "", "| Scraper | Version | Profile |", "| --- | --- | --- |"])
    for scraper in report["scrapers"]:
        lines.append(f"| {scraper['name']} | {scraper['version'].replace('|', '/')} | {scraper['profile']} |")
    lines.extend(["", "## Quality", "", "Scores remain separate. Errors are LegoNews / ScrapingHub / WCXB counts and remain in the scores.", "", "| Scraper | LegoNews F1 | ScrapingHub F1 | WCXB F1 | Errors |", "| --- | ---: | ---: | ---: | --- |"])
    for name, quality in report["quality"].items():
        evaluations = quality["evaluations"]
        cells = [f"{evaluations[corpus]['overall']['f1']:.5%}" if evaluations[corpus]["pages"] else "n/a" for corpus in CORPORA]
        cells.append(" / ".join(str(evaluations[corpus]["errors"]) for corpus in CORPORA))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Metadata", "", "Exact matches / annotated pages. Missing metadata labels are unknown, not negatives; per-corpus results are in the JSON report.", "", "| Scraper | Author Exact | Author F1 | Title Exact | Date Exact |", "| --- | ---: | ---: | ---: | ---: |"])
    for name, quality in report["quality"].items():
        fields = quality["evaluations"]["metadata"]["overall"]
        cells = [f"{fields[field]['correct']}/{fields[field]['annotated']} ({fields[field]['exact_match']:.2%})" if fields[field]["annotated"] else "n/a" for field in ("authors", "title", "date")]
        cells.insert(1, f"{fields['authors']['f1']:.5%}" if fields["authors"]["annotated"] else "n/a")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Performance", "", report["timing_scope"], "", MEMORY_SCOPE, "", "Speed and memory use different runs. Speedup is the first scraper's mean milliseconds/page divided by the row's mean. Overall means are weighted by page observations, not equally by corpus.", "", "| Corpus | Pages | Scraper | Mean (ms/page) | Pass Total Range (ms) | Speedup | Median Sampled Peak RSS (MiB) |", "| --- | ---: | --- | ---: | --- | ---: | ---: |"])
    baseline = report["scrapers"][0]["name"]
    for corpus, scrapers in report["summary"].items():
        baseline_speed = scrapers[baseline]["mean_ms_per_page"]
        for name, result in scrapers.items():
            speed = result.get("pass_seconds") or result.get("batch_seconds")
            memory = result["sampled_peak_tree_rss_bytes"]
            cells = [f"{result['mean_ms_per_page']:.3f}", f"{speed['minimum'] * 1000:.2f}..{speed['maximum'] * 1000:.2f}", f"{baseline_speed / result['mean_ms_per_page']:.3f}x" if baseline_speed else "n/a"] if speed else ["n/a"] * 3
            cells.append(f"{memory['median'] / 1048576:.2f}" if memory else "n/a")
            lines.append(f"| {corpus} | {report['workloads'][corpus]['pages']} | {name} | " + " | ".join(cells) + " |")
    lines.extend(["", "| All Selected Pages | Timed Page Observations | Mean (ms/page) |", "| --- | ---: | ---: |"])
    for name, result in report["overall_speed"].items():
        mean = f"{result['mean_ms_per_page']:.3f}" if result["mean_ms_per_page"] is not None else "n/a"
        lines.append(f"| {name} | {result['page_observations']} | {mean} |")
    lines.extend(["", "See `comparison.json` for every sample, schedule, environment, options, artifact hashes, errors and metadata denominators. Do not pool this run with historical timings. Clock checks cannot detect every suspension or host disturbance.", ""])
    return "\n".join(lines)


def checkpoint(directory, report):
    report["summary"] = summarize(report)
    report["overall_speed"] = {
        scraper["name"]: mean_page_time([item for item in report["runs"] if item["phase"] == "speed" and item["scraper"] == scraper["name"] and item["stable"]])
        for scraper in report["scrapers"]
    }
    write_json(directory / "comparison.json", report)
    (directory / "REPORT.md").write_text(markdown_report(report), encoding="utf-8")


def export_results(directory, report, publication_date):
    if not report["complete"]:
        raise ValueError("Cannot publish an incomplete comparison")
    stamp = date.fromisoformat(publication_date).strftime("%Y_%m_%d")
    common = {
        "schema_version": 1, "benchmark_date": publication_date,
        "run_created_utc": report["created_utc"],
        "comparison_sha256": sha256(directory / "comparison.json"),
        **{key: report[key] for key in ("benchmark", "selection", "workloads", "scrapers", "controller_sha256", "config_sha256")},
    }
    write_json(directory / f"quality_{stamp}.json", {
        **common, "kind": "quality", "quality": report["quality"],
        "scope": "Three separate text scores; metadata is a separate annotated-field evaluation. Errors remain in the scores. No combined text F1.",
    })
    if any(item["phase"] == "speed" for item in report["runs"]):
        write_json(directory / f"performance_{stamp}.json", {
            **common, "kind": "performance",
            **{key: report[key] for key in ("timing", "timing_scope", "environment", "summary", "overall_speed", "runs")},
            "page_timing": report.get("page_timing"), "schedules": report["schedules"],
            "scope": "Only within-run comparisons. Overall latency is weighted by all timed page observations; no samples are discarded or pooled with other runs.",
        })


def run_comparison(arguments):
    library = process_library()
    publication_date = getattr(arguments, "publication_date", None)
    if publication_date is not None and date.fromisoformat(publication_date).isoformat() != publication_date:
        raise ValueError("Publication date must be YYYY-MM-DD")
    page_speed = getattr(arguments, "timing", "batch") == "page" and arguments.mode in ("all", "speed")
    if page_speed and arguments.warmups < 1:
        raise ValueError("Persistent page timing requires at least one complete warmup pass")
    scrapers = load_scrapers(arguments.config.resolve(), arguments.scraper)
    all_records, manifest = load_records(arguments.data)
    selected = select_records(all_records, arguments.wcxb_split, arguments.upstream_records)
    records = select_workloads(selected, arguments.corpus or CORPORA, arguments.limit_per_corpus, arguments.seed)
    if not records:
        raise ValueError("No benchmark inputs selected")
    payload = extractor_input(records, arguments.data).encode("utf-8")
    request_lines = payload.splitlines(keepends=True)
    inputs = {record["id"]: line for record, line in zip(records, request_lines, strict=True)}
    groups = {corpus: [record for record in records if record["corpus"] == corpus] for corpus in CORPORA}
    groups = {corpus: group for corpus, group in groups.items() if group}
    payloads = {corpus: b"".join(inputs[record["id"]] for record in group) for corpus, group in groups.items()}
    arguments.output.mkdir(parents=True, exist_ok=False)
    names = [scraper["name"] for scraper in scrapers]
    by_name = {scraper["name"]: scraper for scraper in scrapers}
    phases = {"warmup": arguments.warmups}
    if arguments.mode in ("all", "speed"):
        phases["speed"] = arguments.runs
    if arguments.mode in ("all", "memory"):
        phases["memory"] = arguments.memory_runs
    if arguments.mode == "quality":
        phases = {}
    if page_speed:
        phases = {"memory": arguments.memory_runs} if arguments.mode == "all" else {}
    schedules = {phase: balanced_orders(names, count, arguments.seed + index) for index, (phase, count) in enumerate(phases.items())}
    report = {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(), "complete": False,
        "mode": arguments.mode, "scrapers": scrapers, "config_sha256": sha256(arguments.config),
        "benchmark": {
            "registry_sha256": manifest["registry_sha256"], "input_sha256": input_digest(records),
            "corpora_sha256": {name: entry["sha256"] for name, entry in manifest["corpora"].items()},
            "sources": {name: entry.get("source", {}) for name, entry in manifest["corpora"].items()},
            "provenance": {name: entry.get("provenance", {}) for name, entry in manifest["corpora"].items()},
        },
        "selection": {"wcxb_split": arguments.wcxb_split, "upstream_records": arguments.upstream_records, "limit_per_corpus": arguments.limit_per_corpus, "seed": arguments.seed},
        "environment": {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(), "logical_cpus": library.cpu_count(), "physical_cpus": library.cpu_count(logical=False), "total_memory_bytes": library.virtual_memory().total, "python": sys.version, "psutil": library.__version__, "cpu": arguments.cpu, "inherited_runtime_settings": {key: os.environ.get(key) for key in ("GOMAXPROCS", "GOGC", "GOMEMLIMIT", "GODEBUG", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "TZ")}},
        "controller_sha256": {name: sha256(ROOT / name) for name in ("compare.py", "benchmark.py", "evaluate.py", "prepare.py")},
        "timing": "page" if page_speed else "batch", "timing_scope": PAGE_TIMING_SCOPE if page_speed else TIMING_SCOPE, "memory_scope": MEMORY_SCOPE, "schedules": schedules,
        "workloads": {corpus: {"pages": len(group), "input_sha256": input_digest(group), "ids": [record["id"] for record in group]} for corpus, group in groups.items()},
        "quality": {}, "runs": [],
    }
    report["environment"]["keep_awake_requested"] = getattr(arguments, "keep_awake", False)
    report["environment"]["power_at_start"] = power_status(library)
    references = {}
    controller = library.Process()
    saved_affinity = None
    try:
        if arguments.cpu is not None:
            if not hasattr(controller, "cpu_affinity"):
                raise ValueError("CPU affinity is unavailable on this platform; omit --cpu")
            saved_affinity = controller.cpu_affinity()
            if arguments.cpu not in saved_affinity:
                raise ValueError(f"CPU {arguments.cpu} is not in available affinity {saved_affinity}")
            controller.cpu_affinity([arguments.cpu])
        report["environment"]["affinity"] = controller.cpu_affinity() if hasattr(controller, "cpu_affinity") else None
        checkpoint(arguments.output, report)
        if page_speed:
            references = run_page_comparison(arguments, scrapers, records, groups, inputs, report, library)
        for scraper in ([] if page_speed else scrapers):
            name = scraper["name"]
            print(f"Quality: {name}, {len(records)} pages", flush=True)
            result, predictions = execute(scraper, payload, records, arguments.output / f"quality-{name}", arguments.timeout, library)
            report["quality"][name] = {"output": result["output"], "output_sha256": result["output_sha256"], "prediction_digest": result["prediction_digest"], "evaluations": score(records, predictions)}
            references[name] = {corpus: prediction_digest({record["id"]: predictions[record["id"]] for record in group}) for corpus, group in groups.items()}
            checkpoint(arguments.output, report)
        for corpus, group in groups.items():
            for phase, orders in schedules.items():
                for round_index, order in enumerate(orders, start=1):
                    for position, name in enumerate(order, start=1):
                        print(f"{phase}: {corpus}, round {round_index}/{len(orders)}, {name}", flush=True)
                        prefix = arguments.output / f"{phase}-{corpus}-{round_index:03d}-{name}"
                        result, _ = execute(by_name[name], payloads[corpus], group, prefix, arguments.timeout, library, arguments.sample_ms / 1000 if phase == "memory" else None)
                        result.update({"phase": phase, "corpus": corpus, "round": round_index, "position": position, "scraper": name})
                        result["stable"] = result["prediction_digest"] == references[name][corpus]
                        report["runs"].append(result)
                        checkpoint(arguments.output, report)
                        if not result["stable"]:
                            raise ValueError(f"{name}: {phase} output differs from quality reference on {corpus}; run retained as incomplete")
        for scraper in scrapers:
            check_artifacts(scraper)
        report["complete"] = True
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["error_notes"] = getattr(error, "__notes__", [])
        raise
    finally:
        if saved_affinity is not None:
            controller.cpu_affinity(saved_affinity)
        report["environment"]["power_at_end"] = power_status(library)
        checkpoint(arguments.output, report)
    if publication_date is not None:
        export_results(arguments.output, report, publication_date)
    print(f"Comparison complete: {arguments.output / 'REPORT.md'}", flush=True)
    return report


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing runs are never overwritten")
    parser.add_argument("--publication-date", help="Also export quality_YYYY_MM_DD.json and measured performance_YYYY_MM_DD.json after a successful run")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--scraper", action="append", help="Select a named scraper; repeat for any subset")
    parser.add_argument("--corpus", choices=CORPORA, action="append", help="Default: all three corpora, scored separately")
    parser.add_argument("--wcxb-split", choices=("dev", "test"), default="dev")
    parser.add_argument("--upstream-records", action="store_true")
    parser.add_argument("--mode", choices=("all", "quality", "speed", "memory"), default="all")
    parser.add_argument("--timing", choices=("page", "batch"), default="page", help="Default: paired pages in persistent warm processes; batch restarts each scraper")
    parser.add_argument("--runs", type=int, default=4, help="Tunable timed full-data passes per scraper; default 4")
    parser.add_argument("--memory-runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1, help="Discarded full-data warmup passes; page timing keeps the processes alive")
    parser.add_argument("--seed", type=int, default=20260919)
    parser.add_argument("--sample-ms", type=positive_float, default=10)
    parser.add_argument("--timeout", type=positive_float, default=600, help="Deadline per page request/shutdown, or per batch process, seconds")
    parser.add_argument("--cpu", type=int, help="Pin controller and inherited child affinity to one available logical CPU")
    parser.add_argument("--keep-awake", action="store_true", help="Temporarily request Windows system/display wakefulness during persistent page passes")
    parser.add_argument("--limit-per-corpus", type=int, help="Seeded random smoke/sample subset; never labeled a full benchmark")
    arguments = parser.parse_args()
    if arguments.runs < 1 or arguments.memory_runs < 1 or arguments.warmups < 0 or (arguments.limit_per_corpus is not None and arguments.limit_per_corpus < 1):
        parser.error("Runs and limits must be positive; warmups must be nonnegative")
    run_comparison(arguments)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error