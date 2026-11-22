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
from scraper.fetch import ChallengeError
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


class FailingFetcher:
    """所有请求都抛异常，模拟 Cloudflare 拦死 / 站点挂掉。"""

    def __init__(self, base_url: str, credentials: dict) -> None:
        pass

    def get(self, path: str, timeout: float = 45.0):
        raise RuntimeError("connection reset")

    def update_credentials(self, credentials: dict) -> None:
        pass


class BlankFetcher:
    """请求都成功，但页面里什么都没有（比如 200 的验证页 / 维护页）。"""

    class Response:
        status_code = 200

        def __init__(self) -> None:
            self.text = "<html>maintenance</html>"
            self.url = "https://example.com/cart.php"

    def __init__(self, base_url: str, credentials: dict) -> None:
        pass

    def get(self, path: str, timeout: float = 45.0):
        return self.Response()

    def update_credentials(self, credentials: dict) -> None:
        pass


class ChallengeFetcher:
    """每个请求都撞 Cloudflare 验证。"""

    def __init__(self, base_url: str, credentials: dict) -> None:
        pass

    def get(self, path: str, timeout: float = 45.0):
        raise ChallengeError(f"Cloudflare challenge on {path} (403)")

    def update_credentials(self, credentials: dict) -> None:
        pass


class OneShotChallengeFetcher:
    """第一个请求撞验证，之后就正常。"""

    def __init__(self, base_url: str, credentials: dict) -> None:
        self.challenges = 0

    def get(self, path: str, timeout: float = 45.0):
        if self.challenges == 0:
            self.challenges += 1
            raise ChallengeError("Cloudflare challenge on first request")
        return FakeResponse(PAGE)

    def update_credentials(self, credentials: dict) -> None:
        pass


HISTORY = {
    "products": {
        "2": {"pid": 2, "status": "active", "name": "在售 A"},
        "5": {"pid": 5, "status": "stale", "name": "已下架 B"},
    },
    "missing": [7, 8],
    "progress": {"next_pid": 1, "complete": True, "min_pid": 1, "max_pid": 10},
}


class CloudflareBudgetTest(unittest.TestCase):
    """Cloudflare 验证不能无限重试：超了就整体跳过站点。"""

    site = CART_SITE

    def _crawl(self, fetcher, previous=None, max_challenges=5, credentials=None):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scraper.crawler.Fetcher", fetcher
        ), mock.patch(
            "scraper.crawler.get_credentials",
            return_value={"user_agent": "ua", "cookies": {}, "solved_at": 0},
        ) as solve, mock.patch(
            "scraper.crawler.time.sleep", lambda _: None
        ), mock.patch("scraper.crawler.random.uniform", lambda _a, _b: 0.0):
            result = crawl(
                self.site, 1, 10, 0.0, 0.0,
                credentials or {"user_agent": "ua", "cookies": {}},
                Path(tmp) / "cookies.json",
                previous or {},
                max_challenges=max_challenges,
            )
        return result, solve

    def test_gives_up_on_site_after_max_challenges(self):
        result, solve = self._crawl(ChallengeFetcher)
        self.assertTrue(result.aborted)
        self.assertTrue(result.stats.cf_abandoned)
        self.assertTrue(result.stats.failed)
        self.assertEqual(result.stats.challenges, 5)
        # 没有把 10 个 pid 全部走完，被拦到第 5 次就停了
        self.assertLessEqual(result.stats.scanned, 5)
        # 而且没有连点浏览器：短时间内最多只起一次（CF_SOLVE_COOLDOWN）
        self.assertEqual(solve.call_count, 1)

    def test_custom_threshold(self):
        result, _ = self._crawl(ChallengeFetcher, max_challenges=2)
        self.assertEqual(result.stats.challenges, 2)
        self.assertTrue(result.aborted)

    def test_aborted_round_keeps_previous_data(self):
        previous = {
            "products": {"2": {"pid": 2, "status": "active", "name": "旧"}},
            "missing": [7],
            "progress": {"next_pid": 1, "complete": True, "min_pid": 1, "max_pid": 10},
        }
        result, _ = self._crawl(ChallengeFetcher, previous=previous)
        merged = merge_store(previous, result, self.site)
        self.assertTrue(merged["failed"])
        self.assertEqual(merged["products"], {"2": {"pid": 2, "status": "active", "name": "旧"}})
        self.assertEqual(merged["missing"], [7])

    def test_single_challenge_then_ok_keeps_going(self):
        result, solve = self._crawl(OneShotChallengeFetcher)
        self.assertFalse(result.aborted)
        self.assertEqual(result.stats.challenges, 1)
        self.assertEqual(len(result.found), 10)
        self.assertEqual(solve.call_count, 1)

    def test_recent_clearance_is_not_re_solved(self):
        # 刚取到的 cookie 又被拒：不要连点浏览器，直接跳过这个 pid
        result, solve = self._crawl(
            ChallengeFetcher,
            credentials={"user_agent": "ua", "cookies": {}, "solved_at": 9.9e9},
        )
        self.assertEqual(solve.call_count, 0)


class FailedRoundTest(unittest.TestCase):
    site = CART_SITE

    def _crawl(self, fetcher, previous):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scraper.crawler.Fetcher", fetcher
        ), mock.patch("scraper.crawler.time.sleep", lambda _: None), mock.patch(
            "scraper.crawler.random.uniform", lambda _a, _b: 0.0
        ):
            return crawl(
                self.site, 1, 4, 0.0, 0.0,
                {"user_agent": "ua", "cookies": {}},
                Path(tmp) / "cookies.json",
                previous,
            )

    def test_all_requests_error_is_a_failed_round(self):
        result = self._crawl(FailingFetcher, HISTORY)
        self.assertTrue(result.stats.failed)
        self.assertEqual(result.stats.ok, 0)
        self.assertEqual(result.stats.errors, 4)

    def test_blank_pages_with_history_is_a_failed_round(self):
        result = self._crawl(BlankFetcher, HISTORY)
        self.assertTrue(result.stats.failed)
        self.assertGreater(result.stats.ok, 0)
        self.assertEqual(result.stats.parsed, 0)

    def test_blank_pages_without_history_is_not_failed(self):
        # 全新站点本来就可能是空的，不该当成抓取失败
        result = self._crawl(BlankFetcher, {})
        self.assertFalse(result.stats.failed)

    def test_failed_round_leaves_previous_statuses_untouched(self):
        for fetcher in (FailingFetcher, BlankFetcher):
            with self.subTest(fetcher=fetcher.__name__):
                result = self._crawl(fetcher, HISTORY)
                merged = merge_store(HISTORY, result, self.site)
                self.assertTrue(merged["failed"])
                self.assertEqual(merged["products"]["2"]["status"], "active")
                self.assertEqual(merged["products"]["5"]["status"], "stale")
                self.assertEqual(merged["missing"], [7, 8])

    def test_mark_stale_false_only_adds_products(self):
        # 中途落盘只做加法：抓到的新商品写进去，旧的绝不标 stale
        previous = {"products": {"5": {"pid": 5, "status": "active", "name": "旧"}}}
        result = CrawlResult(min_pid=1, max_pid=10)
        result.visited = {"5"}
        result.found["6"] = {"pid": 6, "status": "active", "name": "新"}
        merged = merge_store(previous, result, self.site, mark_stale=False)
        self.assertEqual(merged["products"]["5"]["status"], "active")
        self.assertEqual(merged["products"]["6"]["name"], "新")


if __name__ == "__main__":
    unittest.main()
