"""Run the pinned release benchmark and keep only audited JSON summaries."""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark import load_records, read_json, select_records
from compare import CORPORA, load_scrapers, positive_float, process_library, run_comparison, select_workloads
from prepare import DEFAULT_DATA, ROOT, prepare, sha256
from tools.build_releases import load_suite
from tools.publish_results import publish_results


def installed_tool(name, fallback):
    return shutil.which(name) or (str(fallback) if os.name == "nt" and fallback.is_file() else name)


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return number


def publication_date(value):
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use YYYY-MM-DD")


def parse_arguments(argv=None):
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    gnu_runtime = Path("C:/msys64/ucrt64/bin")
    has_gnu = os.name == "nt" and (gnu_runtime / "gcc.exe").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path, help="Reuse a prebuilt compare.json; skip release builds")
    source.add_argument("--build-dir", type=Path, default=ROOT / ".cache" / "releases", help="Reuse or build pinned adapters here (default: .cache/releases)")
    parser.add_argument("--output", type=Path, help="New summary directory (default: results/run-UTC-TIMESTAMP); never overwrite results")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Prepared corpus cache; prepare automatically when missing")
    parser.add_argument("--mode", choices=("speed", "quality"), default="speed", help="speed includes quality and N measured passes; quality skips timing")
    parser.add_argument("--runs", type=positive_integer, default=4, help="Measured full-corpus passes per engine (default: 4)")
    parser.add_argument("--best-passes", type=positive_integer, help="Report the fastest complete shared passes, e.g. 2 with --runs 4; optimistic best-of-N estimate (default: all passes)")
    parser.add_argument("--warmups", type=positive_integer, default=1, help="Full warmup passes before timing (default: 1)")
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--scraper", action="append", help="Select an engine by name; repeat to select a subset")
    parser.add_argument("--corpus", choices=CORPORA, action="append", help="Default: all three corpora, scored separately")
    parser.add_argument("--wcxb-split", choices=("dev", "test"), default="dev")
    parser.add_argument("--limit-per-corpus", type=positive_integer, help="Seeded smoke-test sample; not a full benchmark")
    parser.add_argument("--date", type=publication_date, default=date.today().isoformat(), help="Date in summary filenames (default: today)")
    parser.add_argument("--timeout", type=positive_float, default=600, help="Request timeout in seconds (default: 600)")
    parser.add_argument("--keep-awake", action=argparse.BooleanOptionalAction, default=os.name == "nt", help="Windows wakefulness request, enabled by default on Windows; cannot prevent lid/manual sleep")
    parser.add_argument("--runtime-dir", type=Path, action="append", default=None, help="Prepend a compiler/runtime DLL directory to PATH; repeat as needed")
    parser.add_argument("--go", default=installed_tool("go", program_files / "Go/bin/go.exe"))
    parser.add_argument("--git", default=installed_tool("git", program_files / "Git/cmd/git.exe"))
    parser.add_argument("--cargo", default=installed_tool("cargo", Path.home() / ".cargo/bin/cargo.exe"))
    parser.add_argument("--rustc", default=installed_tool("rustc", Path.home() / ".cargo/bin/rustc.exe"))
    parser.add_argument("--go-toolchain", default="go1.27.1")
    parser.add_argument("--rust-toolchain", default="1.98.1-x86_64-pc-windows-gnu" if has_gnu else "1.98.1")
    parser.add_argument("--list", action="store_true", help="List pinned engines and exit without preparing, building or measuring")
    arguments = parser.parse_args(argv)
    if arguments.best_passes is not None and (arguments.mode != "speed" or arguments.best_passes > arguments.runs):
        parser.error("--best-passes requires speed mode and cannot exceed --runs")
    if arguments.runtime_dir is None:
        arguments.runtime_dir = [gnu_runtime] if has_gnu else []
    return arguments


@contextmanager
def runtime_environment(directories):
    paths = [path.resolve() for path in directories]
    for path in paths:
        if not path.is_dir():
            raise ValueError(f"Runtime directory does not exist: {path}")
    saved = {name: os.environ.get(name) for name in ("PATH", "TZ")}
    try:
        os.environ["PATH"] = os.pathsep.join([*(str(path) for path in paths), saved["PATH"] or ""])
        os.environ["TZ"] = "UTC"
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def release_config(arguments):
    if arguments.config is not None:
        config = arguments.config.resolve()
        if not config.is_file():
            raise ValueError(f"Prebuilt configuration does not exist: {config}")
        return config
    directory = arguments.build_dir.resolve()
    suite = ROOT / "release-suite.json"
    entries = load_suite(suite, arguments.scraper)
    config = directory / "compare.json"
    if not config.is_file():
        if directory.exists():
            raise ValueError(f"Build directory exists without a complete compare.json: {directory}. Choose a new --build-dir.")
        command = [sys.executable, "-B", str(ROOT / "tools/build_releases.py"), "--output", str(directory)]
        for name in ("go", "git", "cargo", "rustc", "go_toolchain", "rust_toolchain"):
            command.extend(["--" + name.replace("_", "-"), getattr(arguments, name)])
        for name in arguments.scraper or []:
            command.extend(["--scraper", name])
        subprocess.run(command, check=True)
    registry = read_json(config)
    releases = {item["name"]: item.get("release") for item in registry["scrapers"]}
    if registry.get("suite_sha256") != sha256(suite) or any(releases.get(entry["name"]) != entry for entry in entries):
        raise ValueError(f"Cached builds do not match the selected release pins: {directory}. Choose a new --build-dir or an explicit --config.")
    return config


def check_sleep_events(started, finished):
    result = {"started_utc": started.isoformat(), "finished_utc": finished.isoformat()}
    if sys.platform != "win32":
        return {**result, "status": "unavailable", "reason": "Automatic sleep-event checks are Windows-only; review host conditions separately."}
    shell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if shell is None:
        return {**result, "status": "unavailable", "reason": "PowerShell is unavailable for the Windows sleep-event check."}
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$filter = @{{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = @(42, 107, 506, 507); StartTime = ([DateTimeOffset]::Parse('{started.isoformat()}')).LocalDateTime; EndTime = ([DateTimeOffset]::Parse('{finished.isoformat()}')).LocalDateTime }}
try {{ $events = @(Get-WinEvent -FilterHashtable $filter -ErrorAction Stop) }}
catch {{
    if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') {{ throw }}
    $events = @()
}}
$values = @($events | ForEach-Object {{ @{{ time_utc = $_.TimeCreated.ToUniversalTime().ToString('o'); event_id = $_.Id; message = $_.Message }} }})
ConvertTo-Json -InputObject $values -Depth 3 -Compress
"""
    try:
        process = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
        events = json.loads(process.stdout.lstrip("\ufeff"))
        if not isinstance(events, list):
            raise ValueError("Unexpected event-log response")
        return {**result, "status": "interrupted" if events else "no_sleep_events", "events": events}
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        return {**result, "status": "unavailable", "reason": f"Windows sleep-event check failed ({type(error).__name__}); review the System event log."}


def run_benchmark(arguments):
    process_library()
    destination = (arguments.output or ROOT / "results" / datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-%f")).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    raw = destination / "raw"
    with runtime_environment(arguments.runtime_dir):
        try:
            config = release_config(arguments)
            scrapers = load_scrapers(config, arguments.scraper)
            data = arguments.data.resolve()
            if not (data / "manifest.json").is_file():
                print("Preparing pinned benchmark inputs", flush=True)
                prepare(data, arguments.go)
            records, _ = load_records(data)
            records = select_workloads(select_records(records, arguments.wcxb_split), arguments.corpus or CORPORA,
                                       arguments.limit_per_corpus, arguments.seed)
            if not records:
                raise ValueError("No benchmark inputs selected")
            print(f"Engines: {', '.join(scraper['name'] for scraper in scrapers)}", flush=True)
            print(f"Pages: {len(records)}; mode: {arguments.mode}; measured passes: {arguments.runs if arguments.mode == 'speed' else 0}", flush=True)
            print(f"Summaries: {destination}", flush=True)
            if arguments.best_passes is not None:
                print(f"Reported speed: best {arguments.best_passes} of {arguments.runs} complete shared passes; optimistic estimate, all pass totals retained.", flush=True)
            if arguments.limit_per_corpus is not None:
                print("SMOKE TEST: this is a sampled run, not a full benchmark.", flush=True)
            if arguments.mode == "speed":
                print("Keep the machine awake with the lid open; avoid other heavy work. Power status is diagnostic, not an eligibility gate.", flush=True)
            comparison = argparse.Namespace(
                config=config, output=raw, data=data, scraper=arguments.scraper,
                corpus=arguments.corpus, wcxb_split=arguments.wcxb_split, upstream_records=False,
                mode=arguments.mode, timing="page", runs=arguments.runs, warmups=arguments.warmups,
                memory_runs=1, sample_ms=10, seed=arguments.seed, timeout=arguments.timeout,
                cpu=None, limit_per_corpus=arguments.limit_per_corpus, publication_date=arguments.date,
                keep_awake=arguments.keep_awake,
            )
            report = run_comparison(comparison)
            host_check = None
            if arguments.mode == "speed":
                print("Checking host sleep events outside measurement timers", flush=True)
                host_check = check_sleep_events(datetime.fromisoformat(report["created_utc"]), datetime.now(timezone.utc))
            publish_results(raw, destination, arguments.date, records, discard_raw=True,
                            host_check=host_check, best_passes=arguments.best_passes)
            if host_check is not None:
                if host_check["status"] == "interrupted":
                    print("WARNING: sleep/resume events detected. Performance is marked INVALID; quality scores remain usable.", flush=True)
                else:
                    print(f"Sleep check: {host_check['status']}. Timings remain unreviewed; inspect pass variation before making speed claims.", flush=True)
            for path in sorted(destination.glob("*.json")):
                print(f"Saved: {path}", flush=True)
            print("Finished. Raw predictions and timings removed.", flush=True)
            return destination
        finally:
            if raw.exists():
                shutil.rmtree(raw)


def main(argv=None):
    arguments = parse_arguments(argv)
    if arguments.list:
        for entry in load_suite(ROOT / "release-suite.json"):
            print(f"{entry['name']}  {entry['tag']}")
        return
    run_benchmark(arguments)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Cancelled; temporary raw data removed.") from None
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error