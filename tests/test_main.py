import os
import unittest
from unittest import mock

from scraper.main import resolve_max_pid
from scraper.sites import SITES


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


if __name__ == "__main__":
    unittest.main()
