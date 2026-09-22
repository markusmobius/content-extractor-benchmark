import importlib.util
import io
import json
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from compare import (
    PageProcess, balanced_orders, check_artifacts, distribution, execute, export_results, load_scrapers,
    mean_page_time, prediction_digest, process_library, run_comparison, select_workloads,
)
from prepare import sha256, store_html
from run_benchmark import check_sleep_events, parse_arguments as benchmark_arguments, release_config, run_benchmark
from test_benchmark import fixture
from tools.build_go_trafilatura import archive_source, json_objects
from tools.build_releases import go_adapter, load_suite
from tools.publish_results import audit_run, publish_results, select_best_passes


class ComparisonTests(unittest.TestCase):
    def test_best_passes_are_shared_complete_and_leave_all_totals_intact(self):
        names = ["first", "second"]
        workloads = {"legonews": {"pages": 2}, "wcxb": {"pages": 1}}
        durations = [(0.002, 0.008), (0.008, 0.002), (0.001, 0.020), (0.020, 0.001)]
        report = {
            "kind": "performance", "timing": "page", "workloads": workloads,
            "scrapers": [{"name": name} for name in names], "page_timing": {"timed_passes": 4},
            "performance_validity": {"status": "unreviewed"}, "audit": {"timed_passes": 4},
            "runs": [
                {"phase": "speed", "corpus": corpus, "scraper": name, "round": round_index,
                 "stable": True, "pages": workload["pages"], "elapsed_seconds": seconds * workload["pages"]}
                for round_index, times in enumerate(durations, start=1)
                for name, seconds in zip(names, times)
                for corpus, workload in workloads.items()
            ],
        }
        original = json.dumps(report, sort_keys=True)
        result = select_best_passes(report, 2)
        self.assertEqual(result["pass_selection"]["selected_rounds"], [1, 2])
        self.assertEqual(result["pass_selection"]["excluded_rounds"], [3, 4])
        self.assertEqual([entry["round"] for entry in result["pass_selection"]["ranking"]], [1, 2, 3, 4])
        self.assertEqual(result["runs"], report["runs"])
        self.assertEqual(result["audit"], report["audit"])
        self.assertEqual(result["performance_validity"], report["performance_validity"])
        self.assertEqual(json.dumps(report, sort_keys=True), original)
        for name in names:
            self.assertEqual(result["overall_speed"][name]["page_observations"], 6)
            self.assertAlmostEqual(result["overall_speed"][name]["mean_ms_per_page"], 5.0)
            self.assertEqual(result["summary"]["legonews"][name]["pass_seconds"]["samples"], 2)
        for count in (0, 5):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "count"):
                select_best_passes(report, count)
        with self.assertRaisesRegex(ValueError, "every engine"):
            select_best_passes({**report, "runs": report["runs"][:-1]}, 2)
        unstable = [{**sample, "stable": False} for sample in report["runs"]]
        with self.assertRaisesRegex(ValueError, "stable"):
            select_best_passes({**report, "runs": unstable}, 2)

    def test_benchmark_cli_checks_windows_sleep_without_confusing_query_failure(self):
        started = datetime(2026, 9, 21, 10, tzinfo=timezone.utc)
        finished = datetime(2026, 9, 21, 11, tzinfo=timezone.utc)
        for events in ([], [{"event_id": 507, "time_utc": "2026-09-21T10:30:00Z", "message": "Lid"}]):
            with self.subTest(events=events), patch("run_benchmark.sys.platform", "win32"), \
                    patch("run_benchmark.shutil.which", return_value="powershell.exe"), \
                    patch("run_benchmark.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(events))) as command:
                result = check_sleep_events(started, finished)
                self.assertEqual(result["status"], "interrupted" if events else "no_sleep_events")
                self.assertEqual(result["events"], events)
                self.assertIn(started.isoformat(), command.call_args.args[0][-1])
        with patch("run_benchmark.sys.platform", "win32"), \
                patch("run_benchmark.shutil.which", return_value="powershell.exe"), \
                patch("run_benchmark.subprocess.run", side_effect=OSError("unavailable")):
            self.assertEqual(check_sleep_events(started, finished)["status"], "unavailable")
        with patch("run_benchmark.sys.platform", "linux"):
            self.assertEqual(check_sleep_events(started, finished)["status"], "unavailable")

    def test_benchmark_cli_defaults_and_invalid_pass_count(self):
        arguments = benchmark_arguments([])
        self.assertEqual((arguments.mode, arguments.runs, arguments.warmups), ("speed", 4, 1))
        self.assertIsNone(arguments.best_passes)
        self.assertIsNone(arguments.limit_per_corpus)
        with patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                benchmark_arguments(["--runs", "0"])
            with self.assertRaises(SystemExit):
                benchmark_arguments(["--date", "20260921"])
            for options in (["--best-passes", "0"], ["--best-passes", "5"], ["--mode", "quality", "--best-passes", "2"]):
                with self.subTest(options=options), self.assertRaises(SystemExit):
                    benchmark_arguments(options)

    def test_benchmark_cli_rejects_incomplete_or_mismatched_build_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = benchmark_arguments(["--build-dir", directory])
            with self.assertRaisesRegex(ValueError, "without a complete"):
                release_config(arguments)
            (Path(directory) / "compare.json").write_text(json.dumps({"scrapers": [], "suite_sha256": "changed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "do not match"):
                release_config(arguments)

    def test_benchmark_cli_builds_once_and_reuses_verified_pins(self):
        suite = Path(__file__).parent / "release-suite.json"
        entry = load_suite(suite)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "builds"
            arguments = benchmark_arguments(["--build-dir", str(output), "--scraper", entry["name"]])

            def build(command, check):
                self.assertTrue(check)
                self.assertEqual(command[:2], [sys.executable, "-B"])
                self.assertEqual(Path(command[2]).name, "build_releases.py")
                self.assertEqual(command[-2:], ["--scraper", entry["name"]])
                output.mkdir()
                (output / "compare.json").write_text(json.dumps({
                    "suite_sha256": sha256(suite),
                    "scrapers": [{"name": entry["name"], "release": entry}],
                }), encoding="utf-8")

            with patch("run_benchmark.subprocess.run", side_effect=build) as builder:
                config = release_config(arguments)
                self.assertEqual(config, output / "compare.json")
                self.assertEqual(release_config(arguments), config)
            builder.assert_called_once()

    def test_release_suite_pins_all_seven_requested_versions(self):
        entries = load_suite(Path(__file__).parent / "release-suite.json")
        self.assertEqual([(entry["name"], entry["tag"]) for entry in entries], [
            ("go-trafilatura-2.0.0", "v2.0.0"),
            ("go-trafilatura-2.2.2", "v2.2.2"),
            ("go-domdistiller-1.0.0", "v1.0.0"),
            ("go-readabilityV2-0.6.0", "v0.6.0"),
            ("rust-trafilatura-2.2.2", "v2.2.2"),
            ("rust-domdistiller-1.0.0", "v1.0.0"),
            ("rust-readability-0.6.1", "v0.6.1"),
        ])
        self.assertEqual(len({entry["commit"] for entry in entries}), 7)
        self.assertEqual(load_suite(Path(__file__).parent / "release-suite.json", [entries[0]["name"]]), entries[:1])

    def test_old_and_current_trafilatura_use_identical_adapter_logic(self):
        entries = load_suite(Path(__file__).parent / "release-suite.json")
        old, current = (go_adapter(entry) for entry in entries[:2])
        self.assertIn(b'"github.com/markusmobius/go-trafilatura"', old)
        self.assertEqual(old.replace(b'"github.com/markusmobius/go-trafilatura"', b'"github.com/markusmobius/go-trafilatura/v2"'), current)

    def test_module_graph_uses_structured_concatenated_json(self):
        values = json_objects(b'{"Path":"main","Main":true}\n {"Path":"dependency","Version":"v1"}\n')
        self.assertEqual([value["Path"] for value in values], ["main", "dependency"])

    def test_source_archive_rejects_path_traversal_and_links(self):
        for name, member_type in (("../outside", tarfile.REGTYPE), ("linked", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w:") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = member_type
                    member.linkname = "outside" if member_type == tarfile.SYMTYPE else ""
                    archive.addfile(member)
                with self.assertRaises(ValueError):
                    archive_source(data.getvalue(), Path(directory))

    def test_order_is_balanced_reproducible_and_not_factorial(self):
        names = ["old", "new", "third"]
        orders = balanced_orders(names, 6, 42)
        self.assertEqual(orders, balanced_orders(names, 6, 42))
        for order in orders:
            self.assertEqual(sorted(order), sorted(names))
        for position in range(3):
            for name in names:
                self.assertEqual(sum(order[position] == name for order in orders), 2)
        self.assertEqual(len(balanced_orders(list(map(str, range(20))), 8, 42)), 8)

    def test_two_scrapers_have_four_positions_each_in_eight_rounds(self):
        orders = balanced_orders(["old", "new"], 8, 42)
        self.assertEqual(sum(order[0] == "old" for order in orders), 4)
        self.assertEqual(sum(order[0] == "new" for order in orders), 4)

    def test_seven_scrapers_four_passes_keep_all_reproducible_orders(self):
        names = [f"engine-{index}" for index in range(7)]
        for page in range(10):
            orders = balanced_orders(names, 4, f"20260921:speed:{page}")
            self.assertEqual(len(orders), 4)
            self.assertEqual(orders, balanced_orders(names, 4, f"20260921:speed:{page}"))
            self.assertTrue(all(sorted(order) == names for order in orders))

    def test_samples_are_reproducible_not_a_prefix(self):
        records = [{"id": f"{corpus}/{index}", "corpus": corpus} for corpus in ("legonews", "wcxb") for index in range(100)]
        selected = select_workloads(records, ("legonews", "wcxb"), 5, 42)
        self.assertEqual(selected, select_workloads(records, ("legonews", "wcxb"), 5, 42))
        self.assertEqual(len(selected), 10)
        self.assertNotEqual(selected[:5], records[:5])
        self.assertEqual(select_workloads(records, ("wcxb",), None, 42), records[100:])

    def test_stability_uses_scored_metadata_not_author_order(self):
        first = {"page": {"text": "article", "metadata": {"authors": ["Alice", "Bob"], "title": "Title"}}}
        second = {"page": {"text": "article", "metadata": {"authors": ["Bob", "Alice"], "title": " Title "}}}
        self.assertEqual(prediction_digest(first), prediction_digest(second))
        second["page"]["text"] = "article changed"
        self.assertNotEqual(prediction_digest(first), prediction_digest(second))

    def test_distribution_retains_count_and_range(self):
        self.assertEqual(distribution([4, 1, 2, 3]), {"samples": 4, "median": 2.5, "minimum": 1, "maximum": 4})
        self.assertIsNone(distribution([]))

    def test_mean_page_time_weights_pages_and_passes(self):
        values = [{"pages": 2, "elapsed_seconds": 0.006}, {"pages": 1, "elapsed_seconds": 0.009}]
        self.assertEqual(mean_page_time(values), {"page_observations": 3, "total_seconds": 0.015, "mean_ms_per_page": 5.0})
        self.assertIsNone(mean_page_time([])["mean_ms_per_page"])

    def test_incomplete_comparisons_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "incomplete"):
                export_results(Path(directory), {"complete": False}, "2026-09-21")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_config_requires_identifiable_unique_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compare.json"
            definition = {"name": "python", "version": sys.version, "profile": "test", "options": {}, "command": [sys.executable]}
            path.write_text(json.dumps({"schema_version": 1, "scrapers": [definition]}), encoding="utf-8")
            scrapers = load_scrapers(path)
            self.assertEqual(len(scrapers), 1)
            self.assertEqual(len(scrapers[0]["artifacts_sha256"]), 1)
            with self.assertRaisesRegex(ValueError, "Unknown scraper"):
                load_scrapers(path, ["missing"])
            path.write_text(json.dumps({"schema_version": 1, "scrapers": [definition, definition]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate scraper"):
                load_scrapers(path)

    def test_release_receipt_is_embedded_and_bound_to_binary_and_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {"commit": "a" * 40, "tag": "v1.0.0"}
            receipt = {"source": source, "binary_sha256": sha256(Path(sys.executable))}
            (root / "build.json").write_text(json.dumps(receipt), encoding="utf-8")
            config = root / "config.json"
            definition = {
                "name": "release", "version": "v1.0.0", "profile": "standalone", "options": {},
                "command": [sys.executable], "artifacts": ["build.json"], "build_receipt": "build.json", "release": source,
            }
            config.write_text(json.dumps({"schema_version": 1, "scrapers": [definition]}), encoding="utf-8")
            self.assertEqual(load_scrapers(config)[0]["build_receipt"], receipt)
            receipt["binary_sha256"] = "changed"
            (root / "build.json").write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from executable"):
                load_scrapers(config)

    def test_selected_scrapers_do_not_require_unselected_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compare.json"
            selected = {"name": "selected", "version": "test", "profile": "test", "options": {}, "command": [sys.executable]}
            unavailable = {**selected, "name": "unavailable", "command": ["./not-built-yet"]}
            path.write_text(json.dumps({"schema_version": 1, "scrapers": [selected, unavailable]}), encoding="utf-8")
            self.assertEqual([item["name"] for item in load_scrapers(path, ["selected"])], ["selected"])
            with self.assertRaisesRegex(ValueError, "build the executable"):
                load_scrapers(path)


@unittest.skipUnless(importlib.util.find_spec("psutil"), "Optional performance dependency is not installed")
class ProcessComparisonTests(unittest.TestCase):
    def prepare(self, directory, names=("old-2.2.1", "new-2.2.2"), program=None):
        root = Path(directory)
        records = [{**fixture(f"{corpus}/page", corpus, "dev" if corpus == "wcxb" else "standard"), **store_html(b"<p>one two</p>", root)} for corpus in ("legonews", "scrapinghub", "wcxb")]
        program = program or (
            "import json,sys\n"
            "allocation=bytearray(8*1024*1024)\n"
            "for line in sys.stdin:\n"
            " request=json.loads(line)\n"
            " assert set(request)=={'id','url','html_path'}\n"
            " print(json.dumps({'id':request['id'],'text':'one two','metadata':{'authors':['Alice'],'title':'Title','date':'2026-01-02'}}),flush=True)\n"
        )
        config = root / "config.json"
        config.write_text(json.dumps({"schema_version": 1, "scrapers": [
            {"name": name, "version": "test", "profile": "test", "options": {}, "command": [sys.executable, "-B", "-c", program]}
            for name in names
        ]}), encoding="utf-8")
        manifest = {"registry_sha256": "registry", "corpora": {corpus: {"sha256": corpus} for corpus in ("legonews", "scrapinghub", "wcxb")}}
        arguments = SimpleNamespace(config=config, output=root / "results", data=root, scraper=None, wcxb_split="dev", upstream_records=False, corpus=None, limit_per_corpus=None, seed=42, mode="all", runs=2, memory_runs=1, warmups=1, cpu=None, timeout=10, sample_ms=1)
        return arguments, records, manifest

    def test_end_to_end_counts_memory_identity_and_versioned_output_names(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory)
            with patch("compare.load_records", return_value=(records, manifest)):
                report = run_comparison(arguments)
            self.assertTrue(report["complete"])
            self.assertEqual(len(report["runs"]), 24)
            self.assertEqual(len(list(arguments.output.glob("*.jsonl"))), 26)
            for corpus in ("legonews", "scrapinghub", "wcxb"):
                for name in ("old-2.2.1", "new-2.2.2"):
                    summary = report["summary"][corpus][name]
                    self.assertEqual(summary["batch_seconds"]["samples"], 2)
                    self.assertEqual(summary["sampled_peak_tree_rss_bytes"]["samples"], 1)
                    self.assertGreater(summary["sampled_peak_tree_rss_bytes"]["median"], 0)
            self.assertTrue(all(item["stable"] for item in report["runs"]))
            self.assertTrue(all(item["memory"] is None for item in report["runs"] if item["phase"] == "speed"))
            self.assertTrue((arguments.output / "quality-old-2.2.1.jsonl").is_file())
            self.assertIn("Title Exact | Date Exact", (arguments.output / "REPORT.md").read_text())
            with patch("compare.load_records", return_value=(records, manifest)):
                with self.assertRaises(FileExistsError):
                    run_comparison(arguments)

    def test_quality_only_exports_audited_summary_and_discards_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory)
            arguments.mode = "quality"
            with patch("compare.load_records", return_value=(records, manifest)):
                report = run_comparison(arguments)
            destination = Path(directory) / "published"
            audit = publish_results(arguments.output, destination, "2026-09-21", records, discard_raw=True)
            self.assertEqual(audit["observations"], 6)
            self.assertEqual(audit["timed_observations"], 0)
            self.assertTrue(audit["scores_recomputed"])
            self.assertFalse(arguments.output.exists())
            self.assertEqual([path.name for path in destination.iterdir()], ["quality_2026_09_21.json"])
            summary = json.loads((destination / "quality_2026_09_21.json").read_text(encoding="utf-8"))
            for name, quality in summary["quality"].items():
                for corpus, evaluation in quality["evaluations"].items():
                    self.assertNotIn("per_page", evaluation)
                    self.assertEqual(evaluation["overall"], report["quality"][name]["evaluations"][corpus]["overall"])

    def test_benchmark_cli_runs_both_modes_and_keeps_only_summaries(self):
        for mode in ("quality", "speed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                arguments, records, manifest = self.prepare(directory)
                command = benchmark_arguments([
                    "--config", str(arguments.config), "--data", directory,
                    "--output", str(arguments.output), "--mode", mode,
                    "--date", "2026-09-21", "--no-keep-awake",
                ] + (["--best-passes", "2"] if mode == "speed" else []))
                with patch("run_benchmark.prepare") as preparation, \
                        patch("run_benchmark.load_records", return_value=(records, manifest)), \
                    patch("run_benchmark.check_sleep_events", return_value={"status": "interrupted", "events": [{"event_id": 507}]}) as sleep_check, \
                        patch("compare.load_records", return_value=(records, manifest)):
                    destination = run_benchmark(command)
                preparation.assert_called_once_with(Path(directory).resolve(), command.go)
                self.assertFalse((destination / "raw").exists())
                self.assertEqual(len(list(destination.iterdir())), 1 if mode == "quality" else 2)
                quality = json.loads((destination / "quality_2026_09_21.json").read_text(encoding="utf-8"))
                self.assertTrue(quality["audit"]["scores_recomputed"])
                self.assertEqual(quality["audit"]["timed_observations"], 0 if mode == "quality" else 24)
                if mode == "speed":
                    sleep_check.assert_called_once()
                    performance = json.loads((destination / "performance_2026_09_21.json").read_text(encoding="utf-8"))
                    self.assertEqual(performance["performance_validity"]["status"], "invalid")
                    self.assertEqual(performance["environment"]["sleep_check"]["events"], [{"event_id": 507}])
                    self.assertEqual(performance["pass_selection"]["reported_passes"], 2)
                    self.assertEqual(performance["audit"]["timed_passes"], 4)
                    self.assertEqual(len(performance["runs"]), 30)
                    for scraper in performance["scrapers"]:
                        selected = [sample for sample in performance["runs"] if sample["phase"] == "speed"
                                    and sample["scraper"] == scraper["name"] and sample["round"] in performance["pass_selection"]["selected_rounds"]]
                        self.assertEqual(performance["overall_speed"][scraper["name"]], mean_page_time(selected))
                        self.assertEqual(performance["overall_speed"][scraper["name"]]["page_observations"], 6)
                else:
                    sleep_check.assert_not_called()
                with self.assertRaises(FileExistsError):
                    run_benchmark(command)

    def test_benchmark_cli_removes_raw_data_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory, program="raise SystemExit(2)")
            command = benchmark_arguments([
                "--config", str(arguments.config), "--data", directory,
                "--output", str(arguments.output), "--no-keep-awake",
            ])
            with patch("run_benchmark.prepare"), \
                    patch("run_benchmark.load_records", return_value=(records, manifest)), \
                    patch("compare.load_records", return_value=(records, manifest)):
                with self.assertRaisesRegex(ValueError, "JSON line"):
                    run_benchmark(command)
            self.assertEqual(list(arguments.output.iterdir()), [])

    def test_changed_output_is_retained_and_stops_comparison(self):
        program = (
            "import json,pathlib,sys\n"
            "marker=pathlib.Path('called')\n"
            "text='changed' if marker.exists() else 'one two'\n"
            "marker.touch()\n"
            "for line in sys.stdin:\n"
            " request=json.loads(line)\n"
            " print(json.dumps({'id':request['id'],'text':text}))\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory, ("unstable",), program)
            arguments.mode = "speed"
            with patch("compare.load_records", return_value=(records, manifest)):
                with self.assertRaisesRegex(ValueError, "output differs"):
                    run_comparison(arguments)
            report = json.loads((arguments.output / "comparison.json").read_text())
            self.assertFalse(report["complete"])
            self.assertEqual(len(report["runs"]), 1)
            self.assertFalse(report["runs"][0]["stable"])
            self.assertIsNone(report["summary"]["legonews"]["unstable"]["batch_seconds"])

    def test_timeout_kills_process_and_keeps_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, _ = self.prepare(directory, ("timeout",), "while True: pass")
            scraper = load_scrapers(arguments.config)[0]
            with self.assertRaises(subprocess.TimeoutExpired):
                execute(scraper, b"", records, Path(directory) / "timeout", 0.1, process_library())
            self.assertTrue((Path(directory) / "timeout.stderr").is_file())

    def test_persistent_adapter_flushes_before_eof_and_keeps_its_process(self):
        program = (
            "import json,os,sys\n"
            "count=0\n"
            "for line in sys.stdin:\n"
            " count+=1\n"
            " request=json.loads(line)\n"
            " print(json.dumps({'id':request['id'],'text':'one two','pid':os.getpid(),'count':count}),flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, _ = self.prepare(directory, ("persistent",), program)
            scraper = load_scrapers(arguments.config)[0]
            with PageProcess(scraper, Path(directory) / "session", 5, process_library()) as worker:
                responses = []
                for record in records:
                    timing, prediction = worker.exchange((json.dumps({"id": record["id"]}) + "\n").encode(), record)
                    self.assertGreater(timing["elapsed_seconds"], 0)
                    responses.append(prediction[record["id"]])
                self.assertEqual([response["count"] for response in responses], [1, 2, 3])
                interpreter_pids = {response["pid"] for response in responses}
                self.assertEqual(len(interpreter_pids), 1)
                self.assertTrue(interpreter_pids <= {worker.process.pid, *(child.pid for child in worker.process.children(recursive=True))})
            self.assertEqual(worker.process.returncode, 0)

    def test_page_timing_keeps_both_processes_and_pairs_every_page_four_times(self):
        program = (
            "import json,os,sys\n"
            "count=0\n"
            "for line in sys.stdin:\n"
            " count+=1\n"
            " request=json.loads(line)\n"
            " print(json.dumps({'id':request['id'],'text':'one two','pid':os.getpid(),'count':count}),flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory, program=program)
            arguments.mode, arguments.timing, arguments.runs = "speed", "page", 4
            arguments.publication_date = "2026-09-21"
            with patch("compare.load_records", return_value=(records, manifest)):
                report = run_comparison(arguments)
            self.assertTrue(report["complete"])
            self.assertEqual(len(report["runs"]), 30)
            samples = [json.loads(line) for line in (arguments.output / "page-timings.jsonl").read_text().splitlines()]
            self.assertEqual(len(samples), 30)
            for index in range(0, len(samples), 2):
                pair = samples[index:index + 2]
                self.assertEqual(pair[0]["id"], pair[1]["id"])
                self.assertNotEqual(pair[0]["scraper"], pair[1]["scraper"])
                self.assertEqual([sample["position"] for sample in pair], [1, 2])
            names = [scraper["name"] for scraper in report["scrapers"]]
            for name in names:
                output = arguments.output / report["page_timing"]["processes"][name]["output"]
                responses = [json.loads(line) for line in output.read_text().splitlines()]
                self.assertEqual(len({response["pid"] for response in responses}), 1)
                self.assertEqual([response["count"] for response in responses], list(range(1, 16)))
                timed = [sample for sample in samples if sample["phase"] == "speed" and sample["scraper"] == name]
                self.assertEqual(report["overall_speed"][name]["page_observations"], 12)
                self.assertAlmostEqual(report["overall_speed"][name]["mean_ms_per_page"], sum(sample["elapsed_seconds"] for sample in timed) * 1000 / 12)
                for record in records:
                    self.assertEqual(sum(sample["position"] == 1 for sample in timed if sample["id"] == record["id"]), 2)
            self.assertIn("Mean (ms/page)", (arguments.output / "REPORT.md").read_text())
            quality = json.loads((arguments.output / "quality_2026_09_21.json").read_text())
            performance = json.loads((arguments.output / "performance_2026_09_21.json").read_text())
            self.assertEqual(quality["quality"], report["quality"])
            self.assertEqual(performance["overall_speed"], report["overall_speed"])
            self.assertEqual(performance["runs"], report["runs"])
            self.assertEqual(performance["page_timing"]["observations_sha256"], report["page_timing"]["observations_sha256"])
            self.assertEqual(quality["comparison_sha256"], performance["comparison_sha256"])
            self.assertEqual(len(report["page_timing"]["pass_diagnostics"]), 5)
            self.assertTrue(report["page_timing"]["complete_position_balance"])
            self.assertTrue(all(set(item["process_cpu_seconds"]) == set(names) for item in report["page_timing"]["pass_diagnostics"]))
            self.assertNotIn("overall_speed", quality)
            self.assertNotIn("quality", performance)
            published = Path(directory) / "published"
            audit = publish_results(arguments.output, published, "2026-09-21", records)
            self.assertEqual(audit["observations"], 30)
            self.assertEqual(audit["timed_observations"], 24)
            self.assertTrue(audit["scores_recomputed"])
            exported = json.loads((published / "performance_2026_09_21.json").read_text(encoding="utf-8"))
            self.assertEqual(exported["overall_speed"], performance["overall_speed"])
            self.assertEqual(exported["runs"], performance["runs"])
            self.assertFalse(exported["raw_data_included"])
            self.assertEqual(exported["performance_validity"]["status"], "unreviewed")
            self.assertNotIn("observations", exported["page_timing"])
            self.assertNotIn("evidence", exported)
            exported_quality = json.loads((published / "quality_2026_09_21.json").read_text(encoding="utf-8"))
            self.assertEqual(exported_quality["comparison_sha256"], exported["comparison_sha256"])
            self.assertEqual(len(list(published.iterdir())), 2)
            for name in names:
                self.assertNotIn("output", exported_quality["quality"][name])
                self.assertNotIn("output", exported["page_timing"]["processes"][name])
                for corpus, evaluation in exported_quality["quality"][name]["evaluations"].items():
                    self.assertNotIn("per_page", evaluation)
                    self.assertEqual(evaluation["overall"], report["quality"][name]["evaluations"][corpus]["overall"])
            with self.assertRaises(FileExistsError):
                publish_results(arguments.output, published, "2026-09-21", records)
            with self.assertRaisesRegex(ValueError, "outside"):
                publish_results(arguments.output, arguments.output / "nested", "2026-09-21", records, discard_raw=True)
            samples[0]["position"] = 7
            log_path = arguments.output / "page-timings.jsonl"
            original_log = log_path.read_text(encoding="utf-8")
            log_path.write_text("".join(json.dumps(sample) + "\n" for sample in samples), encoding="utf-8")
            report["page_timing"]["observations_sha256"] = sha256(log_path)
            with self.assertRaisesRegex(ValueError, "schedule"):
                audit_run(arguments.output, report, records)
            log_path.write_text(original_log, encoding="utf-8")
            compact = Path(directory) / "compact"
            reason = "Host suspended during a measured pass."
            publish_results(arguments.output, compact, "2026-09-21", records,
                            discard_raw=True, performance_invalid_reason=reason)
            self.assertFalse(arguments.output.exists())
            self.assertEqual(len(list(compact.iterdir())), 2)
            interrupted = json.loads((compact / "performance_2026_09_21.json").read_text(encoding="utf-8"))
            self.assertEqual(interrupted["performance_validity"], {"status": "invalid", "reason": reason})
            self.assertEqual(interrupted["runs"], performance["runs"])
            self.assertEqual(json.loads((compact / "quality_2026_09_21.json").read_text(encoding="utf-8")), exported_quality)

    def test_persistent_timeout_reaps_the_process(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, _ = self.prepare(directory, ("blocked",), "import sys; sys.stdin.read()")
            scraper = load_scrapers(arguments.config)[0]
            with self.assertRaises(subprocess.TimeoutExpired):
                with PageProcess(scraper, Path(directory) / "session", 0.2, process_library()) as worker:
                    worker.exchange(b"{}\n", records[0])
            self.assertIsNotNone(worker.process.returncode)
            self.assertFalse(worker.thread.is_alive())

    def test_page_speed_retains_separate_memory_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory)
            arguments.timing, arguments.runs = "page", 1
            with patch("compare.load_records", return_value=(records, manifest)):
                report = run_comparison(arguments)
            self.assertTrue(report["complete"])
            memory_runs = [item for item in report["runs"] if item["phase"] == "memory"]
            self.assertEqual(len(memory_runs), 6)
            self.assertTrue(all(item["memory"]["samples"] > 0 and item["stable"] for item in memory_runs))
            self.assertTrue(all(item["memory"] is None for item in report["runs"] if item["phase"] == "speed"))

    def test_persistent_output_changes_leave_an_incomplete_report(self):
        program = (
            "import json,sys\n"
            "count=0\n"
            "for line in sys.stdin:\n"
            " count+=1\n"
            " request=json.loads(line)\n"
            " print(json.dumps({'id':request['id'],'text':str(count)}),flush=True)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, manifest = self.prepare(directory, program=program)
            arguments.mode, arguments.timing, arguments.runs = "speed", "page", 4
            with patch("compare.load_records", return_value=(records, manifest)):
                with self.assertRaisesRegex(ValueError, "Persistent output differs"):
                    run_comparison(arguments)
            report = json.loads((arguments.output / "comparison.json").read_text())
            self.assertFalse(report["complete"])
            self.assertTrue(all(not item["stable"] for item in report["failed_page"]))
            self.assertTrue(all(result["mean_ms_per_page"] is None for result in report["overall_speed"].values()))

    def test_persistent_extra_response_at_eof_is_rejected(self):
        program = "import sys; sys.stdin.read(); print('extra',flush=True)"
        with tempfile.TemporaryDirectory() as directory:
            arguments, _, _ = self.prepare(directory, ("extra",), program)
            scraper = load_scrapers(arguments.config)[0]
            with self.assertRaisesRegex(ValueError, "unexpected response"):
                with PageProcess(scraper, Path(directory) / "session", 5, process_library()):
                    pass

    def test_memory_cleanup_does_not_hide_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, records, _ = self.prepare(directory, ("timeout",), "while True: pass")
            scraper = load_scrapers(arguments.config)[0]
            with patch("compare.MemorySampler") as sampler:
                sampler.return_value.finish.side_effect = ValueError("no observations")
                with self.assertRaises(subprocess.TimeoutExpired) as failure:
                    execute(scraper, b"", records, Path(directory) / "timeout", 0.1, process_library(), memory_interval=0.01)
            self.assertIn("no observations", failure.exception.__notes__[0])

    def test_invalid_responses_and_nonzero_exit_are_not_successful_runs(self):
        programs = (
            ("pass", "missing"),
            ('print(\'{"id":"legonews/page","text":"one two"}\\n{"id":"legonews/page","text":"one two"}\')', "duplicate response"),
            ('print(\'{"id":"unexpected","text":"one two"}\')', "extra"),
            ('print(\'{"id":"legonews/page","text":"one two","text":"other"}\')', "Duplicate JSON key"),
            ("import sys; print('failure', file=sys.stderr); sys.exit(7)", "exited 7"),
        )
        for program, expected in programs:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                arguments, records, _ = self.prepare(directory, ("invalid",), program)
                scraper = load_scrapers(arguments.config)[0]
                with self.assertRaisesRegex(ValueError, expected):
                    execute(scraper, b"", records[:1], Path(directory) / "invalid", 10, process_library())
                self.assertTrue((Path(directory) / "invalid.jsonl").is_file())
                self.assertTrue((Path(directory) / "invalid.stderr").is_file())

    def test_changed_build_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments, _, _ = self.prepare(directory)
            receipt = Path(directory) / "receipt.json"
            receipt.write_text("{}")
            config = json.loads(arguments.config.read_text())
            config["scrapers"][0]["artifacts"] = ["receipt.json"]
            arguments.config.write_text(json.dumps(config))
            scraper = load_scrapers(arguments.config)[0]
            receipt.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                check_artifacts(scraper)


if __name__ == "__main__":
    unittest.main()