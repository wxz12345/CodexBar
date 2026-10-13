"""Cross-device token accounting and source selection regressions."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codexbar import aggregate_usage, config, remote_usage, token_usage, web_dashboard


MODEL_PRICES = {
    "model-a": {"input": 1.0, "cached_input": 0.1, "output": 2.0},
    "model-b": {"input": 4.0, "cached_input": 0.2, "output": 8.0},
    "test-model": {"input": 1.0, "cached_input": 0.1, "output": 2.0},
}
FIXED_DAY = dt.date(2026, 10, 12)


def utc_noon(day: dt.date) -> str:
    return dt.datetime.combine(day, dt.time(12), tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def token_event(timestamp: str, cumulative_input: int, model: str | None = None) -> dict:
    info = {
        "total_token_usage": {
            "input_tokens": cumulative_input,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": cumulative_input,
        },
        "model_context_window": 128_000,
    }
    if model is not None:
        info["model"] = model
    return {"type": "event_msg", "timestamp": timestamp, "payload": {"type": "token_count", "info": info}}


def session_meta(session_id: str, timestamp: str | None = None) -> dict:
    return {"type": "session_meta", "timestamp": timestamp, "payload": {"id": session_id}}


def turn_context(timestamp: str, model: str) -> dict:
    return {"type": "turn_context", "timestamp": timestamp, "payload": {"model": model}}


def user_message(timestamp: str) -> dict:
    return {"type": "event_msg", "timestamp": timestamp, "payload": {"type": "user_message", "message": ""}}


def snapshot(record_id: str | None, events: list[dict], *, title: str = "Conversation", model: str = "") -> dict:
    return {
        "schema": 1,
        "warnings": [],
        "threads": [{
            "record": {
                "id": record_id,
                "title": title,
                "model": model,
                "cwd": "/workspace/project",
                "updated_at_ms": 1_800_000_000_000,
            },
            "events": events,
        }],
    }


def token_events(merged: dict) -> list[dict]:
    return [
        event
        for thread in merged["threads"]
        for event in thread["events"]
        if (event.get("payload") or {}).get("type") == "token_count"
    ]


class MaterializedSnapshot:
    def __init__(self, merged: dict):
        self.temporary = tempfile.TemporaryDirectory(prefix="CodexBar-aggregate-test-")
        self.path = Path(self.temporary.name)
        remote_usage.materialize_snapshot(merged, self.path)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc) -> None:
        self.temporary.cleanup()


class FakeRemote:
    def __init__(self, source_id: str, data: dict | None = None, *, stale: bool = False, error: bool = False):
        self.source_id = source_id
        self.data = data
        self.stale = stale
        self.error = error

    def snapshot(self, force: bool = False) -> dict:
        if self.error or self.data is None:
            raise remote_usage.RemoteUsageError("offline")
        return self.data

    def status(self) -> dict:
        return {
            "id": self.source_id,
            "label": self.source_id.removeprefix("ssh:"),
            "stale": self.stale,
            "fetched_at": 123.0,
            "error": "offline" if self.stale else "",
        }


class AggregateUsageTests(unittest.TestCase):
    def setUp(self):
        self.price_patch = mock.patch.object(token_usage, "load_model_prices", return_value=MODEL_PRICES)
        self.price_patch.start()
        token_usage.clear_usage_cache()
        self.addCleanup(token_usage.clear_usage_cache)
        self.addCleanup(self.price_patch.stop)

    def test_session_meta_identity_merges_synced_copy_and_continuation_before_parsing(self):
        day1, day2 = FIXED_DAY, FIXED_DAY + dt.timedelta(days=1)
        first_time = utc_noon(day1)
        second_time = utc_noon(day2)
        first_context = turn_context(first_time, "model-a")
        first_count = token_event(first_time, 100)
        repeated_message = user_message(second_time)
        source_a = snapshot("device-a-record", [
            session_meta("shared-session"),
            first_context,
            first_count,
            repeated_message,
        ], title="Host A title")
        source_b = snapshot("device-b-record", [
            session_meta("shared-session"),
            first_context,
            first_count,
            turn_context(second_time, "model-b"),
            token_event(second_time, 160),
            repeated_message,
        ], title="Host B title")

        merged = aggregate_usage.merge_snapshots([("ssh:a", source_a), ("ssh:b", source_b)])

        self.assertEqual(merged["schema"], 1)
        self.assertEqual(len(merged["threads"]), 1)
        self.assertGreaterEqual(merged["deduplicated_events"], 1)
        merged_counts = token_events(merged)
        self.assertEqual(len(merged_counts), 2)
        self.assertTrue(all(event["payload"]["info"].get("model") for event in merged_counts))
        self.assertEqual([event["payload"]["info"]["model"] for event in merged_counts], ["model-a", "model-b"])
        self.assertTrue(all(event["payload"]["info"]["model_context_window"] == 128_000 for event in merged_counts))

        with MaterializedSnapshot(merged) as codex_home:
            today = token_usage.collect_today_usage(codex_home=codex_home, today=day2, use_cache=False)
            days = token_usage.collect_usage_days(days=2, codex_home=codex_home, anchor_date=day2, use_cache=False)
            rows = token_usage.collect_thread_usage_for_day(day2, codex_home=codex_home, use_cache=False)

        self.assertEqual([bucket["total_tokens"] for bucket in days["buckets"]], [100, 60])
        self.assertEqual(days["total_tokens"], 160)
        self.assertEqual(today["total_tokens"], days["buckets"][-1]["total_tokens"])
        self.assertAlmostEqual(days["cost_usd"], 0.00034)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_tokens"], today["total_tokens"])
        self.assertEqual(rows[0]["message_count"], 1)

    def test_record_id_is_a_reliable_fallback_when_session_metadata_is_absent(self):
        event = token_event(utc_noon(FIXED_DAY), 75, "test-model")
        merged = aggregate_usage.merge_snapshots([
            ("ssh:a", snapshot("shared-record", [event])),
            ("ssh:b", snapshot("shared-record", [event])),
        ])

        self.assertEqual(len(merged["threads"]), 1)
        self.assertEqual(merged["deduplicated_events"], 1)
        with MaterializedSnapshot(merged) as codex_home:
            result = token_usage.collect_usage_days(days=1, codex_home=codex_home, anchor_date=FIXED_DAY, use_cache=False)
        self.assertEqual(result["total_tokens"], 75)

    def test_different_sessions_with_identical_usage_remain_separate(self):
        event = token_event(utc_noon(FIXED_DAY), 50, "test-model")
        merged = aggregate_usage.merge_snapshots([
            ("ssh:a", snapshot("record-a", [session_meta("session-a"), event])),
            ("ssh:b", snapshot("record-b", [session_meta("session-b"), event])),
        ])

        self.assertEqual(len(merged["threads"]), 2)
        self.assertEqual(merged["deduplicated_events"], 0)
        with MaterializedSnapshot(merged) as codex_home:
            result = token_usage.collect_usage_days(days=1, codex_home=codex_home, anchor_date=FIXED_DAY, use_cache=False)
        self.assertEqual(result["total_tokens"], 100)
        self.assertEqual(result["threads"], 2)
        self.assertEqual(result["events"], 2)

    def test_missing_reliable_ids_do_not_collapse_equal_usage_and_report_warning(self):
        event = token_event(utc_noon(FIXED_DAY), 40, "test-model")
        merged = aggregate_usage.merge_snapshots([
            ("ssh:a", snapshot("rollout-a", [event])),
            ("ssh:b", snapshot("rollout-b", [event])),
        ])

        self.assertEqual(len(merged["threads"]), 2)
        self.assertTrue(merged["warnings"])
        with MaterializedSnapshot(merged) as codex_home:
            result = token_usage.collect_usage_days(days=1, codex_home=codex_home, anchor_date=FIXED_DAY, use_cache=False)
        self.assertEqual(result["total_tokens"], 80)

    def test_conflicting_cumulative_values_at_same_timestamp_are_kept_and_warned(self):
        timestamp = utc_noon(FIXED_DAY)
        merged = aggregate_usage.merge_snapshots([
            ("ssh:a", snapshot("record-a", [session_meta("shared"), token_event(timestamp, 100, "test-model")])),
            ("ssh:b", snapshot("record-b", [session_meta("shared"), token_event(timestamp, 120, "test-model")])),
        ])

        self.assertEqual(len(token_events(merged)), 2)
        self.assertTrue(merged["warnings"])
        with MaterializedSnapshot(merged) as codex_home:
            result = token_usage.collect_usage_days(days=1, codex_home=codex_home, anchor_date=FIXED_DAY, use_cache=False)
        self.assertEqual(result["total_tokens"], 120)

    def test_utc_ordering_preserves_cumulative_baseline_across_local_date_boundary(self):
        day1, day2 = FIXED_DAY, FIXED_DAY + dt.timedelta(days=1)
        # Deliberately provide reverse input order. Both instants are midday UTC,
        # so the test remains away from local midnight on supported desktops.
        merged = aggregate_usage.merge_snapshots([("ssh:a", snapshot("shared", [
            token_event(utc_noon(day2), 145, "test-model"),
            token_event(utc_noon(day1), 90, "test-model"),
        ]))])

        parsed_times = [dt.datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) for event in token_events(merged)]
        self.assertEqual(parsed_times, sorted(parsed_times))
        with MaterializedSnapshot(merged) as codex_home:
            result = token_usage.collect_usage_days(days=2, codex_home=codex_home, anchor_date=day2, use_cache=False)
        self.assertEqual([bucket["total_tokens"] for bucket in result["buckets"]], [90, 55])

    def test_aggregate_source_supports_same_local_parser_queries(self):
        today = dt.date.today()
        data = snapshot("local-session", [
            session_meta("local-session"),
            turn_context(utc_noon(today), "test-model"),
            token_event(utc_noon(today), 64),
            user_message(utc_noon(today)),
        ])
        source = aggregate_usage.AggregateUsageSource(
            ["local"], lambda _source_id: self.fail("local collection must not construct a remote source"),
            local_snapshot=lambda: data,
        )
        self.addCleanup(source.close)

        today_usage = source.collect_today_usage(use_cache=False)
        days = source.collect_usage_days(days=1, anchor_date=today, use_cache=False)
        week = source.collect_usage_range("week", anchor_date=today, use_cache=False)
        rows = source.collect_thread_usage_for_day(today, use_cache=False)

        self.assertEqual(today_usage["total_tokens"], 64)
        self.assertEqual(days["total_tokens"], today_usage["total_tokens"])
        self.assertEqual(week["total_tokens"], today_usage["total_tokens"])
        self.assertEqual(rows[0]["total_tokens"], today_usage["total_tokens"])
        self.assertEqual(rows[0]["message_count"], 1)
        self.assertEqual(source.status()["devices"][0]["state"], "fresh")

    def test_partial_remote_failure_keeps_successful_device_usage_and_marks_incomplete(self):
        good = FakeRemote("ssh:good", snapshot("good-session", [token_event(utc_noon(FIXED_DAY), 81, "test-model")]))
        offline = FakeRemote("ssh:offline", error=True)
        remotes = {"ssh:good": good, "ssh:offline": offline}
        source = aggregate_usage.AggregateUsageSource(
            ["ssh:good", "ssh:offline"], lambda source_id: remotes[source_id], local_snapshot=lambda: self.fail("local not selected"),
        )
        self.addCleanup(source.close)

        result = source.collect_usage_days(days=1, anchor_date=FIXED_DAY, use_cache=False)
        states = {device["id"]: device["state"] for device in source.status()["devices"]}

        self.assertEqual(result["total_tokens"], 81)
        self.assertTrue(result["incomplete"])
        self.assertEqual(states, {"ssh:good": "fresh", "ssh:offline": "failed"})

    def test_stale_remote_snapshot_is_counted_as_cached_and_incomplete(self):
        cached = FakeRemote(
            "ssh:cached",
            snapshot("cached-session", [token_event(utc_noon(FIXED_DAY), 92, "test-model")]),
            stale=True,
        )
        source = aggregate_usage.AggregateUsageSource(
            ["ssh:cached"], lambda _source_id: cached, local_snapshot=lambda: self.fail("local not selected"),
        )
        self.addCleanup(source.close)

        result = source.collect_usage_days(days=1, anchor_date=FIXED_DAY, use_cache=False)

        self.assertEqual(result["total_tokens"], 92)
        self.assertTrue(result["incomplete"])
        self.assertEqual(source.status()["devices"][0]["state"], "cached")
        self.assertEqual(source.status()["cached_count"], 1)

    def test_all_remote_failures_without_any_snapshot_raise_instead_of_returning_zero(self):
        source = aggregate_usage.AggregateUsageSource(
            ["ssh:offline"], lambda _source_id: FakeRemote("ssh:offline", error=True),
            local_snapshot=lambda: self.fail("local not selected"),
        )
        self.addCleanup(source.close)

        with self.assertRaises(remote_usage.RemoteUsageError):
            source.collect_usage_days(days=1, anchor_date=FIXED_DAY, use_cache=False)

    def test_all_failed_refresh_retains_previous_aggregate_cache(self):
        remote = FakeRemote("ssh:server", snapshot("server-session", [token_event(utc_noon(FIXED_DAY), 107, "test-model")]))
        source = aggregate_usage.AggregateUsageSource(
            ["ssh:server"], lambda _source_id: remote, local_snapshot=lambda: self.fail("local not selected"),
        )
        self.addCleanup(source.close)
        first = source.collect_usage_days(days=1, anchor_date=FIXED_DAY, use_cache=False)
        remote.error = True

        source.refresh(force=True)
        cached = source.collect_usage_days(days=1, anchor_date=FIXED_DAY, use_cache=False)

        self.assertEqual(first["total_tokens"], 107)
        self.assertEqual(cached["total_tokens"], first["total_tokens"])
        self.assertTrue(cached["incomplete"])
        self.assertEqual(source.status()["devices"][0]["state"], "failed")

    def test_selection_persistence_uses_patched_path_and_rejects_empty_or_invalid_values(self):
        with tempfile.TemporaryDirectory(prefix="CodexBar-selection-test-") as temporary:
            settings_path = Path(temporary) / "config.json"
            selection_path = settings_path.with_name("aggregate_sources.json")
            with mock.patch.object(config, "CFG_PATH", str(settings_path)):
                self.assertEqual(aggregate_usage.load_selected_sources(), ["local"])
                with self.assertRaises(ValueError):
                    aggregate_usage.save_selected_sources([])
                with self.assertRaises(ValueError):
                    aggregate_usage.save_selected_sources(["ssh:bad alias"])

                aggregate_usage.save_selected_sources(["local", "ssh:lab-node"])
                self.assertEqual(json.loads(selection_path.read_text(encoding="utf-8")), {
                    "source_ids": ["local", "ssh:lab-node"],
                })
                self.assertEqual(aggregate_usage.load_selected_sources(), ["local", "ssh:lab-node"])

                selection_path.write_text("{not json", encoding="utf-8")
                self.assertEqual(aggregate_usage.load_selected_sources(), ["local"])

    def test_dashboard_lists_without_connecting_and_preserves_orphaned_selection_until_cancelled(self):
        local = {"id": "local", "label": "本机", "remote": False}
        alpha = {"id": "ssh:alpha", "label": "Alpha", "remote": True}
        gone = {"id": "ssh:gone", "label": "Gone", "remote": True}
        visible_sources = {"items": [local, alpha, gone]}

        with tempfile.TemporaryDirectory(prefix="CodexBar-dashboard-selection-test-") as temporary:
            cfg_path = Path(temporary) / "config.json"
            with mock.patch.object(config, "CFG_PATH", str(cfg_path)), \
                    mock.patch.object(remote_usage, "discover_sources", side_effect=lambda: visible_sources["items"]), \
                    mock.patch.object(remote_usage, "RemoteUsageSource") as remote_source_factory:
                api = web_dashboard.DashboardApi()
                sources = api.get_sources()
                self.assertEqual([item["id"] for item in sources], ["local", "ssh:alpha", "ssh:gone", "aggregate"])
                self.assertTrue(sources[-1]["aggregate"])
                remote_source_factory.assert_not_called()

                settings = api.get_aggregate_settings()
                self.assertEqual(settings["selected_ids"], ["local"])
                self.assertTrue(next(item for item in settings["sources"] if item["id"] == "local")["selected"])

                saved = api.save_aggregate_sources(["local", "ssh:gone"])
                self.assertEqual(saved["selected_ids"], ["local", "ssh:gone"])
                self.assertTrue(next(item for item in saved["sources"] if item["id"] == "ssh:gone")["selected"])

                visible_sources["items"] = [local, alpha]
                missing_settings = api.get_aggregate_settings()
                unavailable = next(item for item in missing_settings["sources"] if item["id"] == "ssh:gone")
                self.assertTrue(unavailable["selected"])
                self.assertFalse(unavailable["available"])

                with self.assertRaises(ValueError):
                    api.save_aggregate_sources(["local", "ssh:new-host"])
                self.assertEqual(aggregate_usage.load_selected_sources(), ["local", "ssh:gone"])

                cancelled = api.save_aggregate_sources(["local"])
                self.assertEqual(cancelled["selected_ids"], ["local"])
                self.assertNotIn("ssh:gone", [item["id"] for item in cancelled["sources"]])

    def test_dashboard_save_failure_keeps_previous_selection_and_aggregate_instance(self):
        with tempfile.TemporaryDirectory(prefix="CodexBar-dashboard-save-failure-test-") as temporary:
            cfg_path = Path(temporary) / "config.json"
            with mock.patch.object(config, "CFG_PATH", str(cfg_path)), \
                    mock.patch.object(remote_usage, "discover_sources", return_value=[
                        {"id": "local", "label": "本机", "remote": False},
                        {"id": "ssh:alpha", "label": "Alpha", "remote": True},
                    ]):
                aggregate_usage.save_selected_sources(["local", "ssh:alpha"])
                api = web_dashboard.DashboardApi()
                old_aggregate = mock.Mock()
                api._aggregate_source = old_aggregate

                with mock.patch.object(aggregate_usage, "save_selected_sources", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        api.save_aggregate_sources(["local"])

                self.assertEqual(aggregate_usage.load_selected_sources(), ["local", "ssh:alpha"])
                self.assertIs(api._aggregate_source, old_aggregate)

    def test_aggregate_load_jobs_keep_their_selection_across_concurrent_configuration_change(self):
        selected = {"ids": ["local"]}
        api = web_dashboard.DashboardApi()
        self.addCleanup(api.close)

        with mock.patch.object(aggregate_usage, "load_selected_sources", side_effect=lambda: list(selected["ids"])), \
                mock.patch.object(web_dashboard.threading, "Thread") as thread_factory:
            first_job = api.start_initial_load("aggregate")
            old_source = api._aggregate_source
            selected["ids"] = ["ssh:beta"]
            second_job = api.start_initial_load("aggregate")
            new_source = api._aggregate_source

            self.assertNotEqual(first_job["job_id"], second_job["job_id"])
            self.assertIsNot(old_source, new_source)
            self.assertNotEqual(id(old_source), id(new_source))
            self.assertEqual(old_source.source_ids, ("local",))
            self.assertEqual(new_source.source_ids, ("ssh:beta",))
            self.assertEqual(thread_factory.call_count, 2)
            old_thread_args = thread_factory.call_args_list[0].kwargs["args"]
            new_thread_args = thread_factory.call_args_list[1].kwargs["args"]
            self.assertIs(old_thread_args[3], old_source)
            self.assertIs(new_thread_args[3], new_source)

            observed_during_build = []

            def build_old_job(*, job_id, source_id):
                self.assertEqual(job_id, first_job["job_id"])
                self.assertEqual(source_id, "aggregate")
                observed_during_build.append(api._usage_source("aggregate"))
                self.assertIs(api._aggregate_source, new_source)
                return {"loaded_with": "old selection"}

            with mock.patch.object(old_source, "refresh") as refresh, \
                    mock.patch.object(api, "_build_initial_state", side_effect=build_old_job):
                api._run_initial_load_job(first_job["job_id"], "aggregate", False, old_source)

            refresh.assert_called_once_with(force=False)
            self.assertEqual(observed_during_build, [old_source])
            self.assertEqual(api.get_load_status(first_job["job_id"])["state"], "done")
            self.assertIs(api._usage_source("aggregate"), new_source)


if __name__ == "__main__":
    unittest.main()
