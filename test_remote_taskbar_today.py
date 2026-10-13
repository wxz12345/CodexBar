"""Taskbar today's-usage behavior for isolated remote Codex snapshots."""

import datetime as dt
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from codexbar import config, remote_usage, token_usage


def count_event(timestamp, input_tokens, output_tokens):
    return {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "info": {
                "model": "test-model",
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": 0,
                    "total_tokens": input_tokens + output_tokens,
                },
            },
        },
    }


def local_noon_timestamp(day):
    local_noon = dt.datetime.combine(day, dt.time(12, 0)).astimezone()
    return local_noon.astimezone(dt.timezone.utc).isoformat()


class RemoteTaskbarTodayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.local_codex_home = self.root / "local" / ".codex"
        self.local_codex_home.mkdir(parents=True)
        self.today = dt.date.today()
        self.timestamp = local_noon_timestamp(self.today)

        home_patch = mock.patch.object(config, "HOME", str(self.root / "local"))
        home_patch.start()
        self.addCleanup(home_patch.stop)
        env_patch = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.local_codex_home)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        prices_patch = mock.patch.object(
            token_usage,
            "load_model_prices",
            return_value={"test-model": {"input": 1, "cached_input": 0, "output": 2}},
        )
        prices_patch.start()
        self.addCleanup(prices_patch.stop)
        self.addCleanup(token_usage.clear_usage_cache)

        self._write_local_usage(10_000, 2_000)

    def _write_local_usage(self, input_tokens, output_tokens):
        database = self.local_codex_home / "state_5.sqlite"
        rollout = self.local_codex_home / "local-rollout.jsonl"
        rollout.write_text(
            json.dumps(count_event(self.timestamp, input_tokens, output_tokens)) + "\n",
            encoding="utf-8",
        )
        with closing(sqlite3.connect(database)) as db, db:
            db.execute(
                "CREATE TABLE threads "
                "(id TEXT, rollout_path TEXT, model TEXT, title TEXT, cwd TEXT, updated_at_ms INTEGER)"
            )
            db.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)",
                ("local-thread", str(rollout), "test-model", "local", "C:/local", 1),
            )

    def _snapshot(self, input_tokens=150, output_tokens=30):
        return {
            "schema": 1,
            "threads": [{
                "record": {
                    "id": "remote-thread",
                    "model": "test-model",
                    "title": "remote",
                    "cwd": "/remote/project",
                    "updated_at_ms": 1,
                },
                "events": [count_event(self.timestamp, input_tokens, output_tokens)],
            }],
            "warnings": [],
        }

    def _source(self):
        source = remote_usage.RemoteUsageSource("test-host", "Test host")
        self.addCleanup(source.close)
        return source

    def test_today_totals_come_only_from_remote_snapshot_and_close_removes_cache(self):
        local = token_usage.collect_today_usage(
            codex_home=self.local_codex_home,
            use_cache=False,
        )
        self.assertEqual(local["total_tokens"], 12_000)

        source = self._source()
        with mock.patch.object(remote_usage, "fetch_snapshot", return_value=self._snapshot()), \
                mock.patch.object(
                    token_usage,
                    "collect_today_usage",
                    wraps=token_usage.collect_today_usage,
                ) as parser:
            result = source.collect_today_usage()

        self.assertEqual(result["total_tokens"], 180)
        self.assertEqual(result["events"], 1)
        self.assertFalse(result["incomplete"])
        parser.assert_called_once()
        parser_kwargs = parser.call_args.kwargs
        self.assertEqual(Path(parser_kwargs["codex_home"]), Path(source._temporary.name))
        self.assertFalse(parser_kwargs["use_cache"])
        self.assertNotEqual(Path(parser_kwargs["codex_home"]), self.local_codex_home)

        temporary_path = Path(source._temporary.name)
        self.assertTrue(temporary_path.is_dir())
        source.close()
        self.assertFalse(temporary_path.exists())

    def test_disconnect_reuses_remote_today_snapshot_and_marks_result_incomplete(self):
        source = self._source()
        with mock.patch.object(remote_usage, "fetch_snapshot", return_value=self._snapshot()):
            initial = source.collect_today_usage()
        self.assertEqual(initial["total_tokens"], 180)

        with mock.patch.object(
            remote_usage,
            "fetch_snapshot",
            side_effect=remote_usage.RemoteUsageError("SSH offline"),
        ):
            source.refresh(force=True)
            result = source.collect_today_usage()

        self.assertEqual(result["total_tokens"], 180)
        self.assertTrue(result["incomplete"])
        self.assertTrue(any("显示上次读取的数据" in warning for warning in result["warnings"]))
        self.assertTrue(source.status()["stale"])

    def test_initial_disconnect_raises_instead_of_returning_zero_usage(self):
        source = self._source()
        with mock.patch.object(
            remote_usage,
            "fetch_snapshot",
            side_effect=remote_usage.RemoteUsageError("SSH offline"),
        ):
            with self.assertRaises(remote_usage.RemoteUsageError):
                source.collect_today_usage()


if __name__ == "__main__":
    unittest.main()
