import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from scraper.crawler import (
    CrawlResult,
    build_progress,
    crawl,
    merge_store,
    resume_pid,
)
from scraper.sites import SITES

CART_SITE = replace(SITES["dedirock"], feed=False)

PAGE = """
<div class="product-info">
    <p class="product-title">Test VPS</p>
    <p>1 GB RAM<br />1x vCore CPU<br />20 GB SSD<br />750 GB Monthly Bandwidth</p>
</div>
<select name="billingcycle"><option value="annually">$71.88 USD Annually</option></select>
"""


class Clock:
    """每次请求 +1 秒，用来测时间预算。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.url = "https://example.com/cart.php"


class FakeFetcher:
    instances: list["FakeFetcher"] = []
    clock: Clock | None = None

    def __init__(self, base_url: str, credentials: dict) -> None:
        self.calls: list[str] = []
        FakeFetcher.instances.append(self)

    def get(self, path: str, timeout: float = 45.0):
        self.calls.append(path)
        if FakeFetcher.clock:
            FakeFetcher.clock.now += 1.0
        pid = int(re.search(r"pid=(\d+)", path).group(1))
        if pid % 2 == 0:
            return FakeResponse(PAGE)
        if pid % 3 == 0:
            return FakeResponse("<html>Out of Stock</html>")
        return FakeResponse("<html>nothing here</html>")

    def update_credentials(self, credentials: dict) -> None:
        pass


def run_crawl(previous, **kwargs):
    site = CART_SITE
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch("scraper.crawler.Fetcher", FakeFetcher), mock.patch(
            "scraper.crawler.time.sleep", lambda _: None
        ), mock.patch("scraper.crawler.random.uniform", lambda _a, _b: 0.0):
            return crawl(
                site,
                kwargs.pop("min_pid", 1),
                kwargs.pop("max_pid", 10),
                0.0,
                0.0,
                {"user_agent": "ua", "cookies": {}},
                Path(tmp) / "cookies.json",
                previous,
                **kwargs,
            )


class ResumePidTest(unittest.TestCase):
    def test_complete_cycle_restarts_from_min(self):
        previous = {"progress": {"next_pid": 500, "complete": True}}
        self.assertEqual(resume_pid(previous, 1, 1000), 1)

    def test_incomplete_cycle_resumes_from_cursor(self):
        previous = {"progress": {"next_pid": 281, "complete": False}}
        self.assertEqual(resume_pid(previous, 1, 1000), 281)

    def test_cursor_clamped_to_range(self):
        self.assertEqual(
            resume_pid({"progress": {"next_pid": 9999, "complete": False}}, 1, 300), 300
        )
        self.assertEqual(
            resume_pid({"progress": {"next_pid": 0, "complete": False}}, 100, 300), 100
        )

    def test_no_progress_starts_from_min(self):
        self.assertEqual(resume_pid({}, 1, 100), 1)
        self.assertEqual(resume_pid({"progress": {"next_pid": "x"}}, 1, 100), 1)


class BudgetTest(unittest.TestCase):
    def test_stops_at_deadline_and_saves_cursor(self):
        clock = Clock()
        FakeFetcher.clock = clock
        self.addCleanup(setattr, FakeFetcher, "clock", None)
        with mock.patch("scraper.crawler.Fetcher", FakeFetcher), mock.patch(
            "scraper.crawler.time.monotonic", clock
        ), mock.patch("scraper.crawler.time.sleep", lambda _: None), mock.patch(
            "scraper.crawler.random.uniform", lambda _a, _b: 0.0
        ):
            with tempfile.TemporaryDirectory() as tmp:
                result = crawl(
                    CART_SITE, 1, 100, 0.0, 0.0,
                    {"user_agent": "ua", "cookies": {}},
                    Path(tmp) / "cookies.json",
                    {},
                    deadline=5.0,
                )
        self.assertFalse(result.complete)
        self.assertTrue(result.stats.incomplete)
        self.assertEqual(result.stats.scanned, 5)
        self.assertEqual(result.next_pid, 6)  # 下次从第 6 个继续
        # 已采到的照常保留
        self.assertEqual(set(result.found), {"2", "4"})
        self.assertEqual(result.out_of_stock, {"3"})

    def test_complete_cycle_resets_cursor(self):
        result = run_crawl({}, min_pid=1, max_pid=10)
        self.assertTrue(result.complete)
        self.assertFalse(result.stats.incomplete)
        self.assertEqual(result.next_pid, 1)  # 采完了，下次重新全量
        self.assertEqual(result.stats.scanned, 10)

    def test_resumes_from_cursor_not_from_min(self):
        previous = {
            "progress": {"next_pid": 8, "complete": False},
            "missing": [],
            "products": {},
        }
        result = run_crawl(previous, min_pid=1, max_pid=10)
        fetcher = FakeFetcher.instances[-1]
        scanned = {int(re.search(r"pid=(\d+)", c).group(1)) for c in fetcher.calls}
        self.assertEqual(scanned, {8, 9, 10})


class CheckpointTest(unittest.TestCase):
    def test_checkpoint_called_with_partial_state(self):
        seen: list[tuple[int, bool]] = []

        def checkpoint(result):
            seen.append((len(result.found), result.complete))

        run_crawl({}, min_pid=1, max_pid=10, on_checkpoint=checkpoint,
                  checkpoint_every=4)
        # 中途落了两次盘，每次都是"采到一半"的数据，最后一次是收尾
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(seen[0][0], 2)   # pid 1..4 里只有 2、4 是产品
        self.assertEqual(seen[-1][0], 5)  # 收尾时 2/4/6/8/10 全在
        self.assertLess(seen[0][0], seen[-1][0])

    def test_checkpoint_failure_does_not_abort(self):
        def boom(result):
            raise RuntimeError("磁盘满了")

        result = run_crawl({}, min_pid=1, max_pid=10, on_checkpoint=boom,
                           checkpoint_every=4)
        self.assertEqual(result.stats.scanned, 10)


class MergeStoreTest(unittest.TestCase):
    site = CART_SITE

    def _result(self, visited):
        result = CrawlResult(min_pid=1, max_pid=10)
        result.visited = set(visited)
        result.missing = {str(pid) for pid in range(1, 11)} - set(visited)
        return result

    def test_only_visited_statuses_change(self):
        previous = {
            "products": {
                "5": {"pid": 5, "status": "active", "name": "扫过但没了"},
                "9": {"pid": 9, "status": "active", "name": "这轮压根没轮到"},
            }
        }
        merged = merge_store(previous, self._result({"5"}), self.site)
        self.assertEqual(merged["products"]["5"]["status"], "stale")
        # 没请求过的不能动，否则中断续采会把在售商品误标成下架
        self.assertEqual(merged["products"]["9"]["status"], "active")

    def test_found_products_marked_active(self):
        previous = {"products": {"5": {"pid": 5, "status": "stale", "name": "回来了"}}}
        result = self._result({"5"})
        result.found["5"] = {"pid": 5, "status": "active", "name": "回来了"}
        merged = merge_store(previous, result, self.site)
        self.assertEqual(merged["products"]["5"]["status"], "active")

    def test_visited_but_oos_gets_strikethrough_status(self):
        previous = {"products": {"5": {"pid": 5, "status": "active", "name": "x"}}}
        result = self._result({"5"})
        result.out_of_stock.add("5")
        merged = merge_store(previous, result, self.site)
        self.assertEqual(merged["products"]["5"]["status"], "out_of_stock")

    def test_progress_recorded(self):
        result = self._result({"5"})
        result.complete = False
        result.next_pid = 6
        merged = merge_store({}, result, self.site)
        self.assertEqual(
            merged["progress"],
            {"next_pid": 6, "complete": False, "min_pid": 1, "max_pid": 10,
             "updated_at": merged["progress"]["updated_at"]},
        )
        self.assertTrue(merged["progress"]["updated_at"])

    def test_build_progress_resets_cursor_when_complete(self):
        result = CrawlResult(min_pid=1, max_pid=100, next_pid=77, complete=True)
        self.assertEqual(build_progress(result)["next_pid"], 1)
        result.complete = False
        self.assertEqual(build_progress(result)["next_pid"], 77)


if __name__ == "__main__":
    unittest.main()
