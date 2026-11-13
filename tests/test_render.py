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
            },
            # 历史上有数据、本轮售罄：不删除，只划删除线
            "37": {
                "pid": 37,
                "name": "LA KVM VPS Sold Out",
                "status": "out_of_stock",
                "price_year": 20.0,
                "price_estimated": False,
                "provider": "dedirock",
                "provider_name": "DediRock",
                "cpu": "2 vCPU",
                "ram": "2 GB",
                "disk": "40 GB SSD",
                "traffic": "1 TB",
                "url": "https://billing.dedirock.com/aff.php?aff=1033&pid=37",
            },
            # 历史上有数据、本轮页面已无产品（下架）：同样保留
            "38": {
                "pid": 38,
                "name": "LA KVM VPS Delisted",
                "status": "stale",
                "price_year": 30.0,
                "price_estimated": False,
                "provider": "dedirock",
                "provider_name": "DediRock",
                "cpu": "2 vCPU",
                "ram": "4 GB",
                "disk": "60 GB SSD",
                "traffic": "2 TB",
                "url": "https://billing.dedirock.com/aff.php?aff=1033&pid=38",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dedirock.ndjson"
            write_site(
                path, site, {"scanned": 1, "out_of_stock": 1}, [], products,
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
        self.assertEqual(len(data["products"]), 3)

        # 在售 1 条，划线的不可用 2 条
        self.assertIn("<b>1</b>", html)
        self.assertIn('<b>2</b>', html)
        self.assertEqual(html.count('class="unavail"'), 2)
        self.assertIn('title="本轮售罄"', html)
        self.assertIn("可能已下架", html)
        # 在售那行不带删除线样式
        self.assertEqual(html.count('<tr data-provider="dedirock">'), 1)
        self.assertIn("[~~LA KVM VPS Sold Out~~]", markdown)
        self.assertIn("~~LA KVM VPS Delisted~~", markdown)
        self.assertIn("1 个在售套餐，2 个本轮不可用", markdown)
        # 默认顺序：在售在前，划线的排后面
        self.assertLess(html.index(">36</td>"), html.index(">37</td>"))
        self.assertLess(html.index(">37</td>"), html.index(">38</td>"))

    def test_unavailable_sorted_after_active(self):
        from scraper.render import active_products, unavailable_products

        store = {
            "products": {
                "1": {"pid": 1, "name": "cheap-oos", "status": "out_of_stock",
                      "price_year": 1.0},
                "2": {"pid": 2, "name": "expensive-active", "status": "active",
                      "price_year": 99.0},
            }
        }
        self.assertEqual([p["name"] for p in active_products(store)],
                         ["expensive-active"])
        self.assertEqual([p["name"] for p in unavailable_products(store)],
                         ["cheap-oos"])


if __name__ == "__main__":
    unittest.main()
