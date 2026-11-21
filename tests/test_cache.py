import json
import tempfile
import unittest
from pathlib import Path

from scraper.restore_cache import main, newest, updated_at


def ndjson(updated_at_value: str) -> str:
    meta = {"type": "meta", "site": "x", "updated_at": updated_at_value}
    return json.dumps(meta) + "\n" + json.dumps({"type": "missing", "pids": []}) + "\n"


class UpdatedAtTest(unittest.TestCase):
    def test_reads_meta_line(self):
        self.assertEqual(updated_at(ndjson("2026-11-21T01:00:00Z")),
                         "2026-11-21T01:00:00Z")

    def test_ignores_garbage_lines(self):
        text = "not json\n" + ndjson("2026-11-21T01:00:00Z")
        self.assertEqual(updated_at(text), "2026-11-21T01:00:00Z")

    def test_empty_when_no_meta(self):
        self.assertEqual(updated_at('{"type":"product","pid":1}\n'), "")


class NewestTest(unittest.TestCase):
    def test_newer_wins(self):
        cached = ndjson("2026-11-21T02:00:00Z")
        head = ndjson("2026-11-21T01:00:00Z")
        self.assertIs(newest(cached, head), cached)
        self.assertIs(newest(head, cached), cached)

    def test_tie_prefers_cache_because_of_cursor(self):
        same = "2026-11-21T01:00:00Z"
        cached = ndjson(same)
        head = ndjson(same)
        self.assertIs(newest(cached, head), cached)

    def test_unparsable_timestamps_do_not_crash(self):
        cached = ndjson("")
        head = ndjson("2026-11-21T01:00:00Z")
        self.assertIs(newest(cached, head), head)


class MainTest(unittest.TestCase):
    def test_keeps_newer_and_falls_back_to_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            head_dir = Path(tmp) / "head"
            cache_dir.mkdir()
            head_dir.mkdir()

            (cache_dir / "newer.ndjson").write_text(ndjson("2026-11-21T02:00:00Z"))
            (head_dir / "newer.ndjson").write_text(ndjson("2026-11-21T01:00:00Z"))
            (cache_dir / "older.ndjson").write_text(ndjson("2026-11-21T01:00:00Z"))
            (head_dir / "older.ndjson").write_text(ndjson("2026-11-21T03:00:00Z"))
            (cache_dir / "only-cache.ndjson").write_text(ndjson("2026-11-21T01:00:00Z"))

            main(["--cache-dir", str(cache_dir), "--head-dir", str(head_dir)])

            self.assertIn("2026-11-21T02:00:00", (cache_dir / "newer.ndjson").read_text())
            self.assertIn("2026-11-21T03:00:00", (cache_dir / "older.ndjson").read_text())
            self.assertTrue((cache_dir / "only-cache.ndjson").exists())

    def test_missing_cache_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                main(["--cache-dir", str(Path(tmp) / "nope")]), 0
            )

    def test_no_head_dir_keeps_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "a.ndjson").write_text(ndjson("2026-11-21T01:00:00Z"))
            self.assertEqual(main(["--cache-dir", str(cache_dir)]), 0)
            self.assertIn("2026-11-21T01:00:00", (cache_dir / "a.ndjson").read_text())


if __name__ == "__main__":
    unittest.main()
