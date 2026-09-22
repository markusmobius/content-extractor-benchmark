import hashlib
from pathlib import Path
import tempfile
import unittest

from prepare import mark_overlaps, store_html, url_key


class PreparationTests(unittest.TestCase):
    def test_url_keys_do_not_discard_queries_or_path_case(self):
        self.assertEqual(url_key("http://www.example.com/page/#top"), url_key("https://example.com/page"))
        self.assertNotEqual(url_key("https://example.com/Page"), url_key("https://example.com/page"))
        self.assertNotEqual(url_key("https://example.com/?page=1"), url_key("https://example.com/?page=2"))
        self.assertIsNone(url_key("not a URL"))

    def test_cross_split_ids_are_distinct_and_duplicates_remain_auditable(self):
        records = [
            {"id": "wcxb/dev/4011", "html_sha256": "same", "url": "https://example.com/first"},
            {"id": "wcxb/test/4011", "html_sha256": "same", "url": "https://example.com/first"},
            {"id": "wcxb/test/9999", "html_sha256": "other", "url": "https://example.com/second"},
        ]
        ledger = mark_overlaps(records)
        self.assertEqual(len(records), 3)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(records[1]["duplicate_of"], "wcxb/dev/4011")
        self.assertIsNone(records[2]["duplicate_of"])

    def test_url_overlap_detects_changed_html(self):
        records = [
            {"id": "legonews/page", "html_sha256": "old", "url": "http://www.example.com/page"},
            {"id": "wcxb/test/page", "html_sha256": "new", "url": "https://example.com/page/"},
        ]
        mark_overlaps(records)
        self.assertEqual(records[1]["overlaps"], {"normalized_url": "legonews/page"})

    def test_html_storage_preserves_bytes_and_checks_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            raw = b"<html>\xff\r\n</html>"
            record = store_html(raw, destination)
            self.assertEqual(record["html_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual((destination / record["html_path"]).read_bytes(), raw)
            self.assertEqual(record, store_html(raw, destination))
            (destination / record["html_path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                store_html(raw, destination)


if __name__ == "__main__":
    unittest.main()