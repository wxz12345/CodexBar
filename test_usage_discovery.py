"""Accounting regressions using synthetic logs, never the user's Codex data."""

from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from codexbar import token_usage


class UsageDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patch_home = mock.patch.object(token_usage.config, "HOME", str(self.home / "unused"))
        patch_home.start()
        self.addCleanup(patch_home.stop)
        self.day = dt.date(2026, 10, 9)
        self.addCleanup(token_usage.clear_usage_cache)
        patch = mock.patch.object(token_usage, "load_model_prices", return_value={})
        patch.start()
        self.addCleanup(patch.stop)

    def rollout(self, directory="sessions", name="rollout-test.jsonl"):
        path = self.home / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        events = [
            {"type": "session_meta", "payload": {"id": "thread-test", "cwd": "/work/project"}},
            {"type": "turn_context", "payload": {"model": "test-model"}},
        ]
        for minute, total in ((1, 100), (2, 100), (3, 150)):
            events.append({"type": "event_msg", "timestamp": f"2026-10-09T12:0{minute}:00Z",
                           "payload": {"type": "token_count", "info": {"total_token_usage": {
                               "input_tokens": total, "cached_input_tokens": 20,
                               "output_tokens": total // 10, "reasoning_output_tokens": 5,
                               "total_tokens": total + total // 10}}}})
        path.write_text("".join(json.dumps(value) + "\n" for value in events), encoding="utf-8")
        return path

    def database(self, path, name="state_5.sqlite"):
        with closing(sqlite3.connect(self.home / name)) as db, db:
            db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?, ?)", ("thread-test", str(path), "My title"))

    def assert_all_views(self):
        today = token_usage.collect_today_usage(self.home, self.day, use_cache=False)
        days = token_usage.collect_usage_days(1, self.home, self.day, use_cache=False)
        week = token_usage.collect_usage_range("week", self.home, self.day, use_cache=False)
        rows = token_usage.collect_thread_usage_for_day(self.day, self.home)
        self.assertEqual([today["total_tokens"], days["total_tokens"], week["total_tokens"]], [165] * 3)
        self.assertEqual(sum(row["total_tokens"] for row in rows), 165)
        self.assertEqual(today["events"], 2)
        self.assertFalse(today["incomplete"])
        return rows

    def test_unindexed_session_is_present_in_all_views(self):
        self.rollout()
        rows = self.assert_all_views()
        self.assertEqual(rows[0]["thread_id"], "thread-test")

    def test_archived_session_without_database_is_counted(self):
        self.rollout("archived_sessions/2026/10/09")
        self.assert_all_views()

    def test_indexed_session_is_not_counted_again_by_directory_scan(self):
        path = self.rollout()
        self.database(path)
        self.assertEqual(self.assert_all_views()[0]["title"], "My title")

    def test_new_database_version_and_relative_rollout_path(self):
        path = self.rollout("custom")
        self.database(path.relative_to(self.home), "state_6.sqlite")
        self.assert_all_views()

    def test_custom_codex_home_is_used_by_default(self):
        self.rollout()
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            result = token_usage.collect_today_usage(today=self.day, use_cache=False)
            days = token_usage.collect_usage_days(1, anchor_date=self.day, use_cache=False)
            week = token_usage.collect_usage_range("week", anchor_date=self.day, use_cache=False)
            rows = token_usage.collect_thread_usage_for_day(self.day)
        self.assertEqual([result["total_tokens"], days["total_tokens"], week["total_tokens"]], [165] * 3)
        self.assertEqual(rows[0]["total_tokens"], 165)

    def test_missing_indexed_file_marks_totals_incomplete(self):
        self.database(self.home / "missing.jsonl")
        result = token_usage.collect_today_usage(self.home, self.day, use_cache=False)
        self.assertTrue(result["incomplete"])
        self.assertTrue(result["warnings"])

    def test_moved_session_recovers_database_title_without_duplicate(self):
        self.database(self.home / "old" / "rollout-test.jsonl")
        self.rollout("archived_sessions")
        self.assertEqual(self.assert_all_views()[0]["title"], "My title")


if __name__ == "__main__":
    unittest.main()
