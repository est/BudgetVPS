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

    def test_incomplete_run_shows_a_warning_chip(self):
        site = SITES["racknerd"]
        store = {
            "meta": {
                "site": "racknerd", "name": "RackNerd", "base_url": "https://x",
                "updated_at": "2026-11-12T00:00:00Z",
                "stats": {"scanned": 10, "active": 1, "incomplete": True},
            },
            "progress": {"next_pid": 11, "complete": False},
            "missing": [],
            "products": {
                "1": {"pid": 1, "name": "X", "status": "active", "price_year": 9.0,
                      "provider": "racknerd", "provider_name": "RackNerd", "url": "u"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            build_site([store], out_dir, TEMPLATE)
            html = (out_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("本轮未采完", html)
        self.assertIn("chip warn", html)

    def test_complete_run_has_no_warning_chip(self):
        site = SITES["racknerd"]
        store = {
            "meta": {
                "site": "racknerd", "name": "RackNerd", "base_url": "https://x",
                "updated_at": "2026-11-12T00:00:00Z",
                "stats": {"scanned": 10, "active": 1, "incomplete": False},
            },
            "progress": {"next_pid": 1, "complete": True},
            "missing": [],
            "products": {
                "1": {"pid": 1, "name": "X", "status": "active", "price_year": 9.0,
                      "provider": "racknerd", "provider_name": "RackNerd", "url": "u"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            build_site([store], out_dir, TEMPLATE)
            html = (out_dir / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("本轮未采完", html)

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


class SortTest(unittest.TestCase):
    def test_sort_value_reads_common_formats(self):
        from scraper.render import sort_value

        self.assertEqual(sort_value("128 GB"), 128)
        self.assertEqual(sort_value("2.5 GB"), 2.5)
        self.assertEqual(sort_value("½ GB"), 0.5)
        self.assertEqual(sort_value("¾ TB"), 0.75)
        self.assertEqual(sort_value("1½ TB"), 1.5)
        self.assertEqual(sort_value("2 × 1000 GB SSD"), 2000)
        self.assertEqual(sort_value(36), 36)
        self.assertIsNone(sort_value("—"))
        self.assertIsNone(sort_value("Unmetered"))
        self.assertIsNone(sort_value(None))

    def test_natural_key_orders_numbers_by_value(self):
        from scraper.render import natural_key

        names = ["10 GB", "2 GB", "1 GB", "128 GB"]
        self.assertEqual(
            sorted(names, key=natural_key), ["1 GB", "2 GB", "10 GB", "128 GB"]
        )
        pids = ["1000", "968", "100", "2"]
        self.assertEqual(
            sorted(pids, key=natural_key), ["2", "100", "968", "1000"]
        )

    def test_rows_carry_sort_values(self):
        from scraper.render import _row

        product = {
            "pid": 36, "name": "X", "status": "active", "url": "u",
            "cpu": "1 vCPU", "ram": "½ GB", "disk": "2 × 1000 GB SSD",
            "traffic": "¾ TB", "price_year": 10.0, "price_estimated": False,
            "provider": "dedirock", "provider_name": "DediRock",
        }
        html = _row(1, product)
        self.assertIn('data-sort="0.5"', html)      # RAM
        self.assertIn('data-sort="2000"', html)     # Storage
        self.assertIn('data-sort="0.75"', html)     # Traffic
        self.assertIn('data-sort="36"', html)       # PID

    def test_rows_without_value_omit_sort_attr(self):
        from scraper.render import _row

        product = {
            "pid": 36, "name": "X", "status": "active", "url": "u",
            "cpu": "1 vCPU", "ram": "—", "disk": "—", "traffic": "Unmetered",
            "price_year": None, "price_estimated": False,
            "provider": "dedirock", "provider_name": "DediRock",
        }
        html = _row(1, product)
        self.assertNotIn('class="ram" data-sort', html)
        self.assertNotIn('class="traffic" data-sort', html)


if __name__ == "__main__":
    unittest.main()
