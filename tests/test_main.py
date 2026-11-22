import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from scraper.crawler import CrawlResult
from scraper.main import process_site, resolve_max_pid, run_sites
from scraper.sites import SITES, Site
from scraper.store import write_site


class MaxPidTest(unittest.TestCase):
    site = SITES["racknerd"]

    def test_cli_wins(self):
        with mock.patch.dict(os.environ, {"MAX_PID": "5000",
                                          "RACKNERD_MAX_PID": "7000"}):
            value, src = resolve_max_pid(self.site, 9999)
        self.assertEqual((value, src), (9999, "--max-pid"))

    def test_global_env_beats_site_env(self):
        with mock.patch.dict(os.environ, {"MAX_PID": "5000",
                                          "RACKNERD_MAX_PID": "7000"}):
            value, src = resolve_max_pid(self.site, 0)
        self.assertEqual((value, src), (5000, "MAX_PID"))

    def test_site_env_beats_config(self):
        env = {"RACKNERD_MAX_PID": "7000"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAX_PID", None)
            value, src = resolve_max_pid(self.site, 0)
        self.assertEqual((value, src), (7000, "RACKNERD_MAX_PID"))

    def test_falls_back_to_site_config(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAX_PID", None)
            os.environ.pop("RACKNERD_MAX_PID", None)
            value, src = resolve_max_pid(self.site, 0)
        self.assertEqual((value, src), (self.site.max_pid, "sites.py"))

    def test_invalid_site_env_ignored(self):
        with mock.patch.dict(os.environ, {"RACKNERD_MAX_PID": "abc"}):
            os.environ.pop("MAX_PID", None)
            value, src = resolve_max_pid(self.site, 0)
        self.assertEqual((value, src), (self.site.max_pid, "sites.py"))

    def test_other_site_env_not_leaked(self):
        """dedirock 不该被 RACKNERD_MAX_PID 影响。"""
        with mock.patch.dict(os.environ, {"RACKNERD_MAX_PID": "7000"}):
            os.environ.pop("MAX_PID", None)
            value, src = resolve_max_pid(SITES["dedirock"], 0)
        self.assertEqual((value, src), (SITES["dedirock"].max_pid, "sites.py"))


def fake_site(name: str) -> Site:
    return Site(
        id=name, name=name.upper(), base_url="https://example.com",
        crawl_path="/p/{pid}", link_path="/l/{pid}", max_pid=10,
    )


class FeedCredentialsTest(unittest.TestCase):
    def _args(self):
        return mock.Mock(
            cf_cache_minutes=20,
            force_solve=False,
            reparse=False,
            no_crawl=False,
            min_pid=1,
            max_pid=1,
            delay_min=None,
            delay_max=None,
        )

    def test_feed_site_does_not_solve_cloudflare_upfront(self):
        result = CrawlResult(min_pid=1, max_pid=1)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scraper.main.get_credentials"
        ) as credentials, mock.patch(
            "scraper.main.crawl", return_value=result
        ):
            process_site(SITES["dedirock"], self._args(), Path(tmp))
        credentials.assert_not_called()

    def test_cart_site_still_solves_cloudflare_upfront(self):
        site = replace(SITES["dedirock"], feed=False)
        result = CrawlResult(min_pid=1, max_pid=1)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scraper.main.get_credentials",
            return_value={"user_agent": "ua", "cookies": {}},
        ) as credentials, mock.patch(
            "scraper.main.crawl", return_value=result
        ):
            process_site(site, self._args(), Path(tmp))
        credentials.assert_called_once()


class FailedCrawlKeepsDataTest(unittest.TestCase):
    """抓取失败时，磁盘上的老数据和商品状态都要原样保留。"""

    site = SITES["dedirock"]
    HISTORY = {
        "2": {"pid": 2, "status": "active", "name": "在售 A", "price_year": 10.0},
        "5": {"pid": 5, "status": "stale", "name": "已下架 B", "price_year": 20.0},
    }

    def _args(self):
        return mock.Mock(
            cf_cache_minutes=20,
            force_solve=False,
            reparse=False,
            no_crawl=False,
            min_pid=1,
            max_pid=0,
            delay_min=None,
            delay_max=None,
        )

    def _seed(self, path: Path) -> str:
        write_site(
            path, self.site, {"active": 1}, {7, 8}, dict(self.HISTORY),
            "2026-11-01T00:00:00Z",
            {"next_pid": 1, "complete": True, "min_pid": 1, "max_pid": 400},
        )
        return path.read_text(encoding="utf-8")

    def _failed_result(self) -> CrawlResult:
        result = CrawlResult(min_pid=1, max_pid=400)
        result.stats.scanned = 10
        result.stats.ok = 0
        result.stats.failed = True
        result.stats.finished_at = "2026-11-02T00:00:00Z"
        return result

    def _assert_kept(self, store, before: str, path: Path) -> None:
        # 磁盘上一个字节都没动
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        # 返回给页面的还是上一轮的数据，站点不会消失
        self.assertEqual(set(store["products"]), {"2", "5"})
        self.assertEqual(store["products"]["2"]["status"], "active")
        self.assertEqual(store["products"]["5"]["status"], "stale")
        self.assertEqual(store["missing"], [7, 8])

    def test_crawl_exception_keeps_previous_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{self.site.id}.ndjson"
            before = self._seed(path)
            with mock.patch("scraper.main.crawl", side_effect=RuntimeError("cf 过不去")):
                store = process_site(self.site, self._args(), Path(tmp))
            self._assert_kept(store, before, path)

    def test_failed_round_keeps_previous_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{self.site.id}.ndjson"
            before = self._seed(path)
            with mock.patch("scraper.main.crawl", return_value=self._failed_result()):
                store = process_site(self.site, self._args(), Path(tmp))
            self._assert_kept(store, before, path)

    def test_cloudflare_solve_failure_keeps_previous_data(self):
        site = replace(self.site, feed=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{site.id}.ndjson"
            before = self._seed(path)
            with mock.patch(
                "scraper.main.get_credentials", side_effect=RuntimeError("浏览器起不来")
            ), mock.patch("scraper.main.crawl") as crawl_call:
                store = process_site(site, self._args(), Path(tmp))
            crawl_call.assert_not_called()
            self._assert_kept(store, before, path)

    def test_successful_round_still_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{self.site.id}.ndjson"
            self._seed(path)
            result = CrawlResult(min_pid=1, max_pid=400)
            result.stats.scanned = 1
            result.stats.ok = 1
            result.stats.parsed = 1
            result.stats.active = 1
            result.stats.finished_at = "2026-11-02T00:00:00Z"
            result.visited = {"9"}
            result.found["9"] = {"pid": 9, "status": "active", "name": "新商品"}
            with mock.patch("scraper.main.crawl", return_value=result):
                store = process_site(self.site, self._args(), Path(tmp))
            self.assertIn("9", store["products"])
            self.assertIn("9", path.read_text(encoding="utf-8"))


class RunSitesTest(unittest.TestCase):
    def test_different_sites_crawl_concurrently(self):
        sites = [fake_site(f"s{i}") for i in range(3)]
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def fake(site, args, data_dir, deadline=None):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return {"meta": {"site": site.id}, "products": {"1": {}}, "missing": []}

        with mock.patch("scraper.main.process_site", fake):
            stores = run_sites(sites, None, Path("."), None)

        self.assertEqual([s["meta"]["site"] for s in stores], ["s0", "s1", "s2"])
        self.assertEqual(state["peak"], 3, "三个站点应该同时在跑")

    def test_one_site_failure_does_not_kill_others(self):
        sites = [fake_site("ok1"), fake_site("bad"), fake_site("ok2")]

        def fake(site, args, data_dir, deadline=None):
            if site.id == "bad":
                raise RuntimeError("boom")
            return {"meta": {"site": site.id}, "products": {"1": {}}, "missing": []}

        with mock.patch("scraper.main.process_site", fake):
            stores = run_sites(sites, None, Path("."), None)

        self.assertEqual([s["meta"]["site"] for s in stores], ["ok1", "ok2"])

    def test_failed_site_falls_back_to_disk_data(self):
        sites = [fake_site("ok"), fake_site("bad")]

        def fake(site, args, data_dir, deadline=None):
            if site.id == "bad":
                raise RuntimeError("boom")
            return {"meta": {"site": site.id}, "products": {"1": {}}, "missing": []}

        with tempfile.TemporaryDirectory() as tmp:
            write_site(
                Path(tmp) / "bad.ndjson", sites[1], {"active": 1}, [],
                {"3": {"pid": 3, "status": "active", "name": "老数据"}},
                "2026-11-01T00:00:00Z",
            )
            with mock.patch("scraper.main.process_site", fake):
                stores = run_sites(sites, None, Path(tmp), None)

        self.assertEqual([s["meta"]["site"] for s in stores], ["ok", "bad"])
        bad = next(s for s in stores if s["meta"]["site"] == "bad")
        self.assertIn("3", bad["products"])

    def test_single_site_runs_without_thread_pool(self):
        calls = []

        def fake(site, args, data_dir, deadline=None):
            calls.append(site.id)
            return {"meta": {"site": site.id}, "products": {"1": {}}, "missing": []}

        with mock.patch("scraper.main.process_site", fake):
            run_sites([fake_site("only")], None, Path("."), None)
        self.assertEqual(calls, ["only"])

    def test_deadline_is_passed_through(self):
        seen = []

        def fake(site, args, data_dir, deadline=None):
            seen.append(deadline)
            return {"meta": {"site": site.id}, "products": {"1": {}}, "missing": []}

        with mock.patch("scraper.main.process_site", fake):
            run_sites([fake_site("a"), fake_site("b")], None, Path("."), 123.0)
        self.assertEqual(seen, [123.0, 123.0])


if __name__ == "__main__":
    unittest.main()
