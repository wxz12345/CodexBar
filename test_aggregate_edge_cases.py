"""Privacy, timezone, and inherited-history boundaries of device merging."""

import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codexbar import aggregate_usage, token_usage
from test_aggregate_usage import MaterializedSnapshot, session_meta, snapshot, token_event, utc_noon, FIXED_DAY


class AggregateEdgeCases(unittest.TestCase):
    def tearDown(self):
        token_usage.clear_usage_cache()

    def test_equivalent_timezone_representations_deduplicate_same_event(self):
        a = token_event("2026-10-12T12:00:00Z", 50, "test-model")
        b = token_event("2026-10-12T20:00:00+08:00", 50, "test-model")
        merged = aggregate_usage.merge_snapshots([("local", snapshot("same", [a])), ("ssh:a", snapshot("same", [b]))])
        self.assertEqual(merged["deduplicated_events"], 1)
        with MaterializedSnapshot(merged) as home:
            result = token_usage.collect_usage_days(1, home, FIXED_DAY, False)
        self.assertEqual(result["total_tokens"], 50)

    def test_local_midnight_baseline_is_shared_across_device_logs(self):
        timezone = dt.datetime.now().astimezone().tzinfo
        before = dt.datetime(2026, 10, 12, 23, 59, tzinfo=timezone)
        after = before + dt.timedelta(minutes=2)
        merged = aggregate_usage.merge_snapshots([
            ("local", snapshot("same", [token_event(before.isoformat(), 100, "test-model")])),
            ("ssh:a", snapshot("same", [token_event(after.astimezone(dt.timezone.utc).isoformat(), 160, "test-model")])),
        ])
        with MaterializedSnapshot(merged) as home:
            result = token_usage.collect_usage_days(2, home, after.date(), False)
        self.assertEqual([bucket["total_tokens"] for bucket in result["buckets"]], [100, 60])

    def test_child_replay_is_not_charged_again_even_with_untimed_handoff(self):
        first = token_event("2026-10-12T12:00:00Z", 100, "test-model")
        second = token_event("2026-10-12T12:02:00Z", 130, "test-model")
        meta = session_meta("child")
        meta["payload"]["forked_from_id"] = "parent"
        handoff = {"type": "event_msg", "payload": {"type": "thread_settings_applied"}}
        merged = aggregate_usage.merge_snapshots([
            ("local", snapshot("parent", [session_meta("parent"), first])),
            ("ssh:a", snapshot("child", [meta, first, handoff, second])),
        ])
        with MaterializedSnapshot(merged) as home:
            result = token_usage.collect_usage_days(1, home, FIXED_DAY, False)
        self.assertEqual(result["total_tokens"], 130)

    def test_invalid_token_record_keeps_good_events_and_reports_incomplete(self):
        invalid = token_event(utc_noon(FIXED_DAY), 50, "test-model")
        invalid["payload"]["info"]["total_token_usage"]["input_tokens"] = "invalid"
        merged = aggregate_usage.merge_snapshots([("local", snapshot("same", [invalid, token_event(utc_noon(FIXED_DAY), 25, "test-model")]))])
        self.assertTrue(merged["warnings"])
        with MaterializedSnapshot(merged) as home:
            result = token_usage.collect_usage_days(1, home, FIXED_DAY, False)
        self.assertEqual(result["total_tokens"], 25)

    def test_local_snapshot_excludes_message_bodies_and_credentials_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            sessions = home / "sessions"
            sessions.mkdir()
            events = [session_meta("same"), token_event(utc_noon(FIXED_DAY), 25, "test-model"),
                      {"type": "event_msg", "timestamp": utc_noon(FIXED_DAY), "payload": {"type": "user_message", "message": "PRIVATE_BODY"}}]
            path = sessions / "rollout-test.jsonl"
            contents = "\n".join(json.dumps(event) for event in events)
            path.write_text(contents, encoding="utf-8")
            (home / "auth.json").write_text('{"access_token":"PRIVATE_CREDENTIAL"}', encoding="utf-8")
            before = {file.name: file.read_bytes() for file in [path, home / "auth.json"]}
            with mock.patch.dict(os.environ, {"CODEX_HOME": temporary}):
                data = aggregate_usage.local_snapshot()
            self.assertNotIn("PRIVATE_BODY", json.dumps(data))
            self.assertNotIn("PRIVATE_CREDENTIAL", json.dumps(data))
            self.assertEqual(len(data["threads"]), 1)
            self.assertEqual(before, {file.name: file.read_bytes() for file in [path, home / "auth.json"]})


if __name__ == "__main__":
    unittest.main()
