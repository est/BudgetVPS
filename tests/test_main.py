import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scraper.main import resolve_max_pid, run_sites
from scraper.sites import SITES, Site


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
