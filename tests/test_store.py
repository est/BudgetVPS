import tempfile
import unittest
from pathlib import Path

from scraper.sites import SITES
from scraper.store import read_site, write_site


class StoreTest(unittest.TestCase):
    def test_round_trip(self):
        site = SITES["dedirock"]
        products = {
            "36": {"pid": 36, "name": "A", "status": "active"},
            "40": {"pid": 40, "name": "B", "status": "out_of_stock"},
        }
        stats = {"scanned": 3, "skipped": 2, "active": 1, "out_of_stock": 1}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dedirock.ndjson"
            write_site(path, site, stats, {1, 2, 3}, products, "2026-11-12T00:00:00Z")
            self.assertTrue(path.exists())

            store = read_site(path)
        self.assertEqual(store["meta"]["site"], "dedirock")
        self.assertEqual(store["meta"]["name"], "DediRock")
        self.assertEqual(store["meta"]["stats"], stats)
        self.assertEqual(store["missing"], [1, 2, 3])
        self.assertEqual(set(store["products"]), {"36", "40"})
        self.assertEqual(store["products"]["36"]["type"], "product")
        self.assertEqual(store["products"]["36"]["name"], "A")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = read_site(Path(tmp) / "nope.ndjson")
        self.assertEqual(store["products"], {})
        self.assertEqual(store["missing"], [])

    def test_lines_are_one_object_each(self):
        site = SITES["racknerd"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "racknerd.ndjson"
            write_site(path, site, {"scanned": 1}, [], {"7": {"pid": 7, "name": "x"}})
            lines = [line for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # meta + missing + product
        import json

        for line in lines:
            self.assertIsInstance(json.loads(line), dict)


if __name__ == "__main__":
    unittest.main()
