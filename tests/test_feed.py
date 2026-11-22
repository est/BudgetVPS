import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scraper.crawler import crawl
from scraper.feed import (
    FeedNeedsCart,
    FeedNoPrice,
    FeedNotFound,
    fetch_product,
    parse_widget,
)
from scraper.sites import SITES

CART_PAGE = """
<div class="product-info">
    <p class="product-title">Cart VPS</p>
    <p>1 GB RAM<br />1x vCore CPU<br />20 GB SSD<br />750 GB Monthly Bandwidth</p>
</div>
<select name="billingcycle"><option value="annually">$71.88 USD Annually</option></select>
"""


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.url = "https://example.com/feed"


class FakeFetcher:
    instances: list["FakeFetcher"] = []

    def __init__(self, base_url: str = "", credentials: dict | None = None) -> None:
        self.calls: list[str] = []
        FakeFetcher.instances.append(self)

    def get(self, path: str, timeout: float = 45.0):
        self.calls.append(path)
        return self.route(path)

    def update_credentials(self, credentials: dict) -> None:
        pass


def feed_query(path: str) -> tuple[int, str, str | None]:
    query = parse_qs(urlparse(path).query)
    return (
        int(query["pid"][0]),
        query["get"][0],
        (query.get("billingcycle") or [None])[0],
    )


def widget(value: str) -> str:
    return f"document.write('{value}');"


def static_fetcher(fields: dict[tuple[str, str | None], str]) -> FakeFetcher:
    def route(path: str) -> FakeResponse:
        _, field, cycle = feed_query(path)
        value = fields.get((field, cycle))
        if value is None:
            return FakeResponse("", 404)
        return FakeResponse(widget(value))

    fetcher = FakeFetcher()
    fetcher.route = route
    return fetcher


class WidgetTest(unittest.TestCase):
    def test_parse_widget(self):
        self.assertEqual(parse_widget(widget("LA KVM VPS Starter")), "LA KVM VPS Starter")
        self.assertIsNone(parse_widget("<html>403</html>"))

    def test_unescape_addslashes(self):
        self.assertEqual(parse_widget(widget(r"it\'s \"quoted\" \\ ok")),
                         'it\'s "quoted" \\ ok')


class FetchProductTest(unittest.TestCase):
    site = SITES["dedirock"]

    def test_annual_product(self):
        fetcher = static_fetcher({
            ("name", None): "LA KVM VPS Starter",
            ("description", None): "1 GB RAM<br />1x vCore CPU<br />20 GB SSD<br />750 GB Bandwidth",
            ("price", "annually"): "$71.88 USD",
        })
        product = fetch_product(fetcher, self.site, 36)
        self.assertEqual(product["name"], "LA KVM VPS Starter")
        self.assertEqual(product["cpu"], "1 vCPU")
        self.assertEqual(product["ram"], "1 GB")
        self.assertEqual(product["disk"], "20 GB SSD")
        self.assertEqual(product["traffic"], "¾ TB")
        self.assertEqual(product["price_year"], 71.88)
        self.assertEqual(product["price_month"], 5.99)
        self.assertEqual(product["billing_cycle"], "annually")
        self.assertFalse(product["price_estimated"])
        self.assertEqual(product["status"], "active")

    def test_monthly_product_falls_back_to_monthly_price(self):
        fetcher = static_fetcher({
            ("name", None): "Dedicated Server",
            ("description", None): "1 GB RAM<br />1x vCore CPU<br />20 GB SSD",
            ("price", "annually"): "$-1.00 USD",
            ("price", "monthly"): "$59.00 USD",
        })
        product = fetch_product(fetcher, self.site, 40)
        self.assertEqual(product["price_year"], 708.0)
        self.assertEqual(product["price_month"], 59.0)
        self.assertEqual(product["billing_cycle"], "monthly")
        self.assertTrue(product["price_estimated"])

    def test_previous_out_of_stock_is_kept(self):
        fetcher = static_fetcher({
            ("name", None): "Promo VPS",
            ("description", None): "1 GB RAM<br />20 GB SSD",
            ("price", "annually"): "$10.18 USD",
        })
        product = fetch_product(
            fetcher, self.site, 89, {"status": "out_of_stock"}
        )
        self.assertEqual(product["status"], "out_of_stock")

    def test_missing_pid(self):
        fetcher = static_fetcher({("name", None): "Product ID Not Found"})
        with self.assertRaises(FeedNotFound):
            fetch_product(fetcher, self.site, 999)

    def test_no_annual_or_monthly_price(self):
        fetcher = static_fetcher({
            ("name", None): "Quarterly Only",
            ("description", None): "1 GB RAM<br />20 GB SSD",
            ("price", "annually"): "$-1.00 USD",
            ("price", "monthly"): "$-1.00 USD",
        })
        with self.assertRaises(FeedNoPrice):
            fetch_product(fetcher, self.site, 1)

    def test_unknown_pid_only_checks_name(self):
        fetcher = static_fetcher({("name", None): "Retired Product - X"})
        with self.assertRaises(FeedNeedsCart):
            fetch_product(fetcher, self.site, 39, known=False)
        self.assertEqual(len(fetcher.calls), 1)
        self.assertIn("get=name", fetcher.calls[0])


class FeedCrawlTest(unittest.TestCase):
    def run_crawl(self, route, previous=None, max_pid=4):
        site = replace(SITES["dedirock"], feed=True)
        FakeFetcher.route = staticmethod(route)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("scraper.crawler.Fetcher", FakeFetcher), mock.patch(
                "scraper.crawler.time.sleep", lambda _: None
            ), mock.patch("scraper.crawler.random.uniform", lambda _a, _b: 0.0):
                return crawl(
                    site,
                    1,
                    max_pid,
                    0.0,
                    0.0,
                    {"user_agent": "ua", "cookies": {}},
                    Path(tmp) / "cookies.json",
                    previous or {},
                )

    def test_feed_primary_and_cart_fallback(self):
        def route(path: str):
            if not path.startswith("/feeds/"):
                return FakeResponse(CART_PAGE)
            pid, field, cycle = feed_query(path)
            if pid == 1:
                return FakeResponse(widget("Product ID Not Found"))
            if pid == 3:
                return FakeResponse("", 500)
            if field == "name":
                return FakeResponse(widget(f"VPS {pid}"))
            if field == "description":
                return FakeResponse(widget("1 GB RAM<br />20 GB SSD"))
            return FakeResponse(widget("$10.00 USD"))

        previous = {
            "products": {
                "4": {"pid": 4, "status": "out_of_stock", "name": "VPS 4"},
            }
        }
        result = self.run_crawl(route, previous)

        self.assertEqual(set(result.found), {"2", "3", "4"})
        self.assertEqual(result.missing, {"1"})
        # 2 是新 pid：feed 只能确认存在，交给 cart 判断是否真的可订购
        self.assertEqual(result.found["2"]["name"], "Cart VPS")
        self.assertEqual(result.found["3"]["name"], "Cart VPS")  # feed 500 -> cart
        # 4 是已知 pid：直接用 feed，保留上次售罄状态
        self.assertEqual(result.found["4"]["name"], "VPS 4")
        self.assertEqual(result.found["4"]["status"], "out_of_stock")
        self.assertEqual(result.out_of_stock, {"4"})
        self.assertEqual(result.stats.active, 2)
        self.assertEqual(result.stats.out_of_stock, 1)

        fetcher = FakeFetcher.instances[-1]
        cart_calls = [call for call in fetcher.calls if not call.startswith("/feeds/")]
        self.assertEqual(len(cart_calls), 2)
        self.assertTrue(any("pid=2" in call for call in cart_calls))
        self.assertTrue(any("pid=3" in call for call in cart_calls))
        self.assertFalse(any("pid=4" in call for call in cart_calls))

    def test_unknown_feed_product_is_not_added_without_cart(self):
        def route(path: str):
            if path.startswith("/feeds/"):
                pid, field, cycle = feed_query(path)
                if pid == 2:
                    return FakeResponse(widget("Retired Product - E3-1230v2"))
                return FakeResponse(widget("Product ID Not Found"))
            return FakeResponse("<html>nothing here</html>")

        result = self.run_crawl(route)
        self.assertEqual(result.found, {})
        self.assertEqual(result.missing, {"1", "2", "3", "4"})

    def test_known_pid_uses_feed_without_cart(self):
        def route(path: str):
            if not path.startswith("/feeds/"):
                return FakeResponse(CART_PAGE)
            pid, field, cycle = feed_query(path)
            if pid == 1:
                return FakeResponse(widget("Product ID Not Found"))
            if field == "name":
                return FakeResponse(widget("Known VPS"))
            if field == "description":
                return FakeResponse(widget("1 GB RAM<br />20 GB SSD"))
            return FakeResponse(widget("$10.00 USD"))

        previous = {"products": {"2": {"pid": 2, "status": "active", "name": "old"}}}
        result = self.run_crawl(route, previous, max_pid=2)

        self.assertEqual(set(result.found), {"2"})
        self.assertEqual(result.found["2"]["name"], "Known VPS")
        fetcher = FakeFetcher.instances[-1]
        self.assertFalse(any(not call.startswith("/feeds/") for call in fetcher.calls))

    def test_feed_disabled_after_repeated_failures(self):
        def route(path: str):
            if path.startswith("/feeds/"):
                return FakeResponse("", 500)
            return FakeResponse(CART_PAGE)

        result = self.run_crawl(route)
        self.assertEqual(set(result.found), {"1", "2", "3", "4"})

        fetcher = FakeFetcher.instances[-1]
        feed_calls = [call for call in fetcher.calls if call.startswith("/feeds/")]
        cart_calls = [call for call in fetcher.calls if not call.startswith("/feeds/")]
        self.assertEqual(len(cart_calls), 4)
        # 前 3 个 pid 各试一次 feed 后熔断，pid 4 不再试
        self.assertNotIn("pid=4", "".join(feed_calls))
        self.assertEqual(len(feed_calls), 3)


if __name__ == "__main__":
    unittest.main()
