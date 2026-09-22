import json
from pathlib import Path
import sys
import tempfile
import unittest

from benchmark import (
    input_digest, require_provenance, run_extractor, score,
    select_records, unique_object, validate_predictions,
)
from prepare import store_html


def fixture(identifier, corpus, split="standard", duplicate=None):
    return {
        "id": identifier, "corpus": corpus, "split": split, "duplicate_of": duplicate,
        "page_type": "article", "url": "https://example.com/",
        "with": ["one two"], "without": ["advert"], "reference_text": "one two",
        "metadata": {"authors": ["Alice"], "title": "Title", "date": "2026-01-02"},
    }


class BenchmarkTests(unittest.TestCase):
    def test_holdout_removes_known_overlap_and_uses_split_qualified_ids(self):
        records = [
            fixture("legonews/page", "legonews"),
            fixture("wcxb/dev/1", "wcxb", "dev"),
            fixture("wcxb/test/1", "wcxb", "test", "wcxb/dev/1"),
            fixture("wcxb/test/2", "wcxb", "test"),
        ]
        self.assertEqual([record["id"] for record in select_records(records, "test")], ["legonews/page", "wcxb/test/2"])
        self.assertEqual(len(select_records(records, "test", upstream=True)), 3)

    def test_missing_extra_and_duplicate_predictions_are_not_silent(self):
        records = [fixture("legonews/page", "legonews")]
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_predictions({}, records)
        with self.assertRaisesRegex(ValueError, "extra"):
            validate_predictions({"legonews/page": {"text": ""}, "extra": {"text": ""}}, records)
        with self.assertRaisesRegex(ValueError, "empty text"):
            validate_predictions({"legonews/page": {"text": "article", "error": "failed"}}, records)

    def test_four_scores_remain_separate_and_metadata_counts_only_annotations(self):
        records = [fixture("legonews/page", "legonews"), fixture("scrapinghub/page", "scrapinghub"), fixture("wcxb/dev/1", "wcxb", "dev")]
        predictions = {record["id"]: {"text": "one two", "metadata": record["metadata"]} for record in records}
        reports = score(records, predictions)
        self.assertEqual(set(reports), {"legonews", "scrapinghub", "wcxb", "metadata"})
        for name in ("legonews", "scrapinghub", "wcxb"):
            self.assertEqual(reports[name]["overall"]["f1"], 1.0)
        self.assertEqual(reports["metadata"]["overall"]["authors"]["annotated"], 2)
        predictions["wcxb/dev/1"] = {"text": "", "error": "rejected"}
        reports = score(records, predictions)
        self.assertEqual(reports["wcxb"]["errors"], 1)
        self.assertEqual(reports["wcxb"]["overall"]["f1"], 0.0)
        self.assertEqual(reports["metadata"]["overall"]["authors"]["false_negatives"], 1)

    def test_imported_duplicate_json_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key: page"):
            json.loads('{"predictions":{"page":{"text":""},"page":{"text":"x"}}}', object_pairs_hook=unique_object)

    def test_provenance_rejects_different_inputs_or_profiles(self):
        records = [{**fixture("legonews/page", "legonews"), "html_sha256": "html"}]
        manifest = {"registry_sha256": "registry", "corpora": {"legonews": {"sha256": "annotations"}}}
        envelope = {
            "name": "extractor", "version": "revision", "profile": "core-only", "options": {},
            "benchmark": {
                "registry_sha256": "registry", "corpora_sha256": {"legonews": "annotations"},
                "input_sha256": input_digest(records), "wcxb_split": "dev", "upstream_records": False,
            },
        }
        require_provenance(envelope, manifest, records, "dev", False)
        with self.assertRaisesRegex(ValueError, "provenance differs"):
            require_provenance(envelope, manifest, records, "test", False)
        envelope["profile"] = ""
        with self.assertRaisesRegex(ValueError, "requires profile"):
            require_provenance(envelope, manifest, records, "dev", False)

    def test_serial_adapter_receives_only_inputs_and_requires_complete_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            record = {**fixture("legonews/page", "legonews"), **store_html(b"<p>article</p>", destination)}
            program = (
                "import json,sys; "
                "requests=[json.loads(line) for line in sys.stdin]; "
                "assert all(set(item)=={'id','url','html_path'} for item in requests); "
                "[print(json.dumps({'id':item['id'],'text':'article'})) for item in requests]"
            )
            predictions = run_extractor([sys.executable, "-B", "-c", program], [record], destination, 30)
            self.assertEqual(predictions, {"legonews/page": {"text": "article"}})
            with self.assertRaisesRegex(ValueError, "missing"):
                run_extractor([sys.executable, "-B", "-c", "pass"], [record], destination, 30)


if __name__ == "__main__":
    unittest.main()