import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper.crawler import crawl
from scraper.sites import SITES

PAGE = """
<div class="product-info">
    <p class="product-title">Test VPS</p>
    <p>1 GB RAM<br />1x vCore CPU<br />20 GB SSD<br />750 GB Monthly Bandwidth</p>
</div>
<select name="billingcycle"><option value="annually">$71.88 USD Annually</option></select>
"""


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.url = "https://example.com/cart.php"


class FakeFetcher:
    instances: list["FakeFetcher"] = []

    def __init__(self, base_url: str, credentials: dict) -> None:
        self.calls: list[str] = []
        FakeFetcher.instances.append(self)

    def get(self, path: str, timeout: float = 45.0):
        self.calls.append(path)
        pid = int(re.search(r"pid=(\d+)", path).group(1))
        if pid in (10, 20):
            return FakeResponse(PAGE)
        if pid == 15:
            return FakeResponse("<html>Out of Stock</html>")
        return FakeResponse("<html>nothing here</html>")

    def update_credentials(self, credentials: dict) -> None:
        pass


class SkipTest(unittest.TestCase):
    def test_skip_interior_missing_and_recheck_tail(self):
        site = SITES["dedirock"]
        previous = {
            "missing": sorted(set(range(1, 31)) - {10, 15, 20, 25}),
            "products": {
                "10": {"pid": 10, "status": "active", "name": "A"},
                "20": {"pid": 20, "status": "active", "name": "B"},
                "25": {"pid": 25, "status": "out_of_stock", "name": "C"},
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("scraper.crawler.Fetcher", FakeFetcher), mock.patch(
                "scraper.crawler.time.sleep", lambda _: None
            ), mock.patch("scraper.crawler.random.uniform", lambda _a, _b: 0.0):
                result = crawl(
                    site,
                    1,
                    30,
                    0.0,
                    0.0,
                    {"user_agent": "ua", "cookies": {}},
                    Path(tmp) / "cookies.json",
                    previous,
                )

        self.assertEqual(result.stats.skipped, 21)
        self.assertEqual(result.stats.scanned, 9)
        self.assertEqual(set(result.found), {"10", "20"})
        self.assertEqual(result.out_of_stock, {"15"})
        self.assertEqual(
            result.missing, {str(pid) for pid in range(1, 31)} - {"10", "15", "20"}
        )
        # 尾部 26-30 虽然上次就"无产品"，仍然每个都复查了
        fetcher = FakeFetcher.instances[-1]
        scanned_pids = {int(re.search(r"pid=(\d+)", call).group(1)) for call in fetcher.calls}
        self.assertEqual(scanned_pids, {10, 15, 20, 25, 26, 27, 28, 29, 30})
        self.assertEqual(result.stats.missing, len(result.missing))


if __name__ == "__main__":
    unittest.main()
