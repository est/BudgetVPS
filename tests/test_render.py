import json
import tempfile
import unittest
from pathlib import Path

from scraper.render import build_site
from scraper.sites import SITES
from scraper.store import read_site, write_site

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "index.html"


class RenderTest(unittest.TestCase):
    def test_build_with_template(self):
        site = SITES["dedirock"]
        products = {
            "36": {
                "pid": 36,
                "name": "LA KVM VPS Starter",
                "status": "active",
                "price_year": 10.0,
                "price_estimated": False,
                "provider": "dedirock",
                "provider_name": "DediRock",
                "cpu": "1 vCPU",
                "ram": "1 GB",
                "disk": "20 GB SSD",
                "traffic": "¾ TB",
                "url": "https://billing.dedirock.com/aff.php?aff=1033&pid=36",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dedirock.ndjson"
            write_site(
                path, site, {"scanned": 1, "out_of_stock": 0}, [], products,
                "2026-11-12T00:00:00Z",
            )
            store = read_site(path)
            out_dir = Path(tmp) / "out"
            build_site([store], out_dir, TEMPLATE)
            html = (out_dir / "index.html").read_text(encoding="utf-8")
            markdown = (out_dir / "index.md").read_text(encoding="utf-8")
            data = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))

        self.assertIn('data-provider="dedirock"', html)
        self.assertIn("DediRock", html)
        self.assertIn("Storage", html)
        self.assertNotIn("{{", html)
        self.assertIn("aff=1033", markdown)
        self.assertIn("¾ TB", markdown)
        self.assertEqual(data["sites"][0]["site"], "dedirock")
        self.assertEqual(data["products"][0]["pid"], 36)


if __name__ == "__main__":
    unittest.main()
