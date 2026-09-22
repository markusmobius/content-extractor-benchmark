import importlib.util
from pathlib import Path
import unittest

from evaluate import (
    author_units, legonews_metrics, metadata_metrics, scrapinghub_metrics,
    scrapinghub_page, snippet_counts, wcxb_metrics, wcxb_page,
)


class MetricTests(unittest.TestCase):
    def test_legonews_preserves_case_and_whitespace(self):
        result = snippet_counts("Wanted text\nnext", ["Wanted text", "wanted", "text next"], ["next", "ads"])
        self.assertEqual(result, {
            "true_positives": 1, "false_negatives": 2,
            "false_positives": 1, "true_negatives": 1,
        })
        metrics = legonews_metrics([result])
        self.assertEqual(metrics["f1"], 0.4)

    def test_legonews_empty_prediction_is_not_dropped(self):
        metrics = legonews_metrics([snippet_counts("", ["article"], ["advert"])])
        self.assertEqual(metrics["false_negatives"], 1)
        self.assertEqual(metrics["true_negatives"], 1)
        self.assertEqual(metrics["f1"], 0.0)

    def test_scrapinghub_shingles_are_ordered_and_case_sensitive(self):
        self.assertEqual(scrapinghub_page("one two three four", "one two three four")["matched"], 1)
        self.assertEqual(scrapinghub_page("four three two one", "one two three four")["matched"], 0)
        self.assertEqual(scrapinghub_page("One two three four", "one two three four")["matched"], 0)
        self.assertEqual(scrapinghub_page("one two", "one two")["matched"], 1)

    def test_scrapinghub_averages_precision_and_recall_before_f1(self):
        pages = [
            {"matched": 1, "predicted": 1, "expected": 4, "accuracy": 0},
            {"matched": 1, "predicted": 4, "expected": 1, "accuracy": 0},
        ]
        self.assertEqual(scrapinghub_metrics(pages)["f1"], 0.625)

    def test_scrapinghub_empty_prediction_precision_uses_upstream_denominator(self):
        pages = [scrapinghub_page("one", "one"), scrapinghub_page("", "two")]
        metrics = scrapinghub_metrics(pages)
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertEqual(metrics["precision_pages"], 1)
        self.assertAlmostEqual(metrics["f1"], 2 / 3)
        self.assertEqual(scrapinghub_metrics([pages[1]])["f1"], 0.0)

    def test_wcxb_counts_repetition_but_ignores_order_and_case(self):
        self.assertEqual(wcxb_page("TWO one", "one two")["f1"], 1.0)
        self.assertAlmostEqual(wcxb_page("one one two two", "one two")["f1"], 2 / 3)
        self.assertEqual(wcxb_page("", "one")["f1"], 0.0)
        self.assertEqual(wcxb_page("", "")["f1"], 1.0)

    def test_wcxb_macro_f1_is_not_f1_of_macro_precision_recall(self):
        pages = [
            wcxb_page("one", "one two three four"),
            wcxb_page("one two three four", "one"),
        ]
        self.assertEqual(wcxb_metrics(pages)["f1"], 0.4)

    def test_missing_metadata_labels_are_not_negative_labels(self):
        result = metadata_metrics([
            ({}, {"authors": ["Somebody"], "title": "A title"}),
            ({"authors": None}, {"authors": ["Somebody"]}),
            ({"authors": ["Alice"]}, {}),
        ])
        self.assertEqual(result["authors"]["annotated"], 1)
        self.assertEqual(result["authors"]["unannotated"], 2)
        self.assertEqual(result["authors"]["false_positives"], 0)
        self.assertEqual(result["authors"]["false_negatives"], 1)
        self.assertIsNone(result["title"]["exact_match"])

    def test_authors_are_order_independent_without_fuzzy_name_merging(self):
        result = metadata_metrics([
            ({"authors": [" Alice ", "Bob"]}, {"authors": ["bob", "alice", "Eve"]}),
        ])["authors"]
        self.assertEqual(result["true_positives"], 2)
        self.assertEqual(result["false_positives"], 1)
        self.assertEqual(result["exact_match"], 0.0)
        self.assertEqual(author_units("Alice and Bob"), {"alice and bob"})
        self.assertEqual(author_units("Smith, Jane"), {"smith, jane"})

    def test_metadata_normalization_and_field_scores(self):
        result = metadata_metrics([
            ({"title": "A  Title", "authors": ["Jos\u00e9"], "date": "2026-01-02"},
             {"title": "a title", "authors": ["Jose\u0301"], "date": "2026-01-03"}),
        ])
        self.assertEqual(result["title"]["exact_match"], 1.0)
        self.assertEqual(result["authors"]["exact_match"], 1.0)
        self.assertEqual(result["date"]["exact_match"], 0.0)


class UpstreamMetricTests(unittest.TestCase):
    def load_upstream(self, name):
        path = Path(__file__).parent / ".cache" / "sources" / name / "evaluate.py"
        if not path.exists():
            self.skipTest("Run prepare.py for pinned upstream evaluator checks")
        specification = importlib.util.spec_from_file_location(f"upstream_{name}", path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def test_scrapinghub_matches_pinned_evaluator(self):
        upstream = self.load_upstream("scrapinghub")
        cases = [
            ("one two three four five", "one two three four"),
            ("", "missing article"),
            ("alpha beta", "alpha beta"),
            ("Mixed Case", "mixed case"),
            ("a a a a a a", "a a a a"),
        ]
        expected = upstream.metrics_from_tp_fp_fns([
            upstream.string_shingle_matching(reference, predicted) for predicted, reference in cases
        ])
        actual = scrapinghub_metrics([scrapinghub_page(predicted, reference) for predicted, reference in cases])
        for field in ("precision", "recall", "f1"):
            self.assertAlmostEqual(actual[field], expected[field], places=14)

    def test_wcxb_matches_pinned_evaluator(self):
        upstream = self.load_upstream("wcxb")
        for predicted, reference in [
            ("one one two", "TWO one"), ("", "article"), ("", ""),
            ("one", ""), ("\u00e9lan X_1", "\u00c9LAN x_1"),
        ]:
            expected = upstream.word_f1(predicted, reference)
            actual = wcxb_page(predicted, reference)
            self.assertEqual(tuple(actual[field] for field in ("precision", "recall", "f1")), expected)


if __name__ == "__main__":
    unittest.main()