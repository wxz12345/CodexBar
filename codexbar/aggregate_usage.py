"""Merge selected devices' accounting records before computing token deltas.

Selection is a user assertion of scope, never evidence of account ownership.
No credentials or message bodies are read into the aggregate cache.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from . import config, remote_usage, token_usage
from .assets.remote_usage_probe import accounting_event


_SELECTION_LOCK = threading.RLock()
_MAX_SOURCES = 64
_MAX_MERGED_BYTES = 128 * 1024 * 1024


def _selection_path() -> Path:
    return Path(config.CFG_PATH).with_name("aggregate_sources.json")


def _validate_selection(values) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_SOURCES:
        raise ValueError("请至少选择一个设备，最多可选择 64 个")
    if any(not isinstance(value, str) or config.valid_usage_source(value) != value for value in values):
        raise ValueError("无效的汇总设备")
    return list(dict.fromkeys(values))


def load_selected_sources() -> list[str]:
    with _SELECTION_LOCK:
        try:
            data = json.loads(_selection_path().read_text(encoding="utf-8"))
            return _validate_selection(data["source_ids"])
        except (OSError, ValueError, TypeError, KeyError):
            return ["local"]


def save_selected_sources(source_ids: list[str]) -> None:
    selected = _validate_selection(source_ids)
    with _SELECTION_LOCK:
        path = _selection_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps({"source_ids": selected}), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def local_snapshot() -> dict:
    """Read the same local discovery scope, keeping only probe-safe events."""
    home = token_usage._codex_home()
    if not home.is_dir():
        raise remote_usage.RemoteUsageError("本机 Codex 日志目录不可用")
    warnings: list[str] = []
    records = token_usage._rollout_records(home, warnings)
    titles = token_usage._thread_display_titles(home)
    threads = []
    size = 0
    for record, path in records:
        events = []
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        event = accounting_event(json.loads(line))
                    except (ValueError, TypeError):
                        if '"token_count"' in line:
                            warnings.append("本机存在无法解析的 token 记录")
                        continue
                    if event is not None:
                        size += len(json.dumps(event).encode("utf-8"))
                        if size > remote_usage.MAX_SNAPSHOT_BYTES:
                            raise remote_usage.RemoteUsageError("本机汇总数据过大，未加载")
                        events.append(event)
        except OSError:
            warnings.append("本机存在无法读取的会话")
            continue
        clean = {key: record.get(key) for key in ("id", "model", "cwd", "updated_at_ms")}
        clean["title"] = token_usage._conversation_title(record, titles)
        threads.append({"record": clean, "events": events})
    return {"schema": 1, "threads": threads, "warnings": warnings}


def _identity(record: dict, events: list[dict]) -> str | None:
    for event in events:
        if event.get("type") == "session_meta":
            meta = event.get("payload") or {}
            for key in ("session_id", "sessionId", "id", "thread_id", "threadId"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    value = record.get("id")
    if isinstance(value, str) and value.strip() and not value.startswith("rollout-"):
        return value
    return None


def _canonical_event(value: dict, model: str) -> tuple[dict | None, str]:
    event = accounting_event(value)
    if event is None:
        return None, model
    payload = event["payload"]
    if event["type"] == "turn_context" and payload.get("model"):
        model = str(payload["model"])
    timestamp = token_usage._timestamp_utc(event.get("timestamp"))
    if timestamp is None and event.get("type") != "session_meta" and not token_usage._is_replay_handoff(event):
        return None, model
    if timestamp is not None:
        event["timestamp"] = timestamp.isoformat()
    if payload.get("type") == "token_count":
        info = payload["info"]
        info["model"] = str(info.get("model") or info.get("model_name") or payload.get("model") or model)
        for key in ("total_token_usage", "last_token_usage"):
            if isinstance(info.get(key), dict):
                info[key] = token_usage._normalize_usage(info[key])
    return event, model


def merge_snapshots(snapshots: list[tuple[str, dict]]) -> dict:
    """Union proven session identities and accounting events across devices.

    Merging raw cumulative snapshots first preserves prior-day baselines and
    overlapping logs. Unknown identities stay distinct; conflicts are flagged.
    """
    groups = {}
    warnings = []
    duplicates = 0
    total_bytes = 0
    for source_id, snapshot in snapshots:
        warnings.extend(f"{source_id}: {warning}" for warning in snapshot.get("warnings", []))
        for index, item in enumerate(snapshot.get("threads", [])):
            record = dict(item["record"])
            raw_events = item["events"]
            identity = _identity(record, raw_events)
            if identity is None:
                identity = "unidentified:" + hashlib.sha256(f"{source_id}:{index}".encode()).hexdigest()
                warnings.append("部分会话缺少可靠标识，无法跨设备去重；汇总可能包含重复记录")
            group = groups.setdefault(identity, {"record": {**record, "id": identity}, "events": {}, "tokens": {}, "meta": None})
            if int(record.get("updated_at_ms") or 0) > int(group["record"].get("updated_at_ms") or 0):
                group["record"] = {**record, "id": identity}
            model = str(record.get("model") or "")
            previous_time = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            for value in raw_events:
                try:
                    event, model = _canonical_event(value, model)
                except (TypeError, ValueError, OverflowError):
                    warnings.append("部分 token 记录无法解析，汇总可能不完整")
                    continue
                if event is None:
                    if isinstance(value, dict) and isinstance(value.get("payload"), dict) and value["payload"].get("type") == "token_count":
                        warnings.append("部分 token 记录缺少有效时间，汇总可能不完整")
                    continue
                payload = event["payload"]
                if event["type"] == "session_meta":
                    # Metadata precedes the merged timeline, preserving replay
                    # semantics without toggling it on each device's copy.
                    if group["meta"] is None:
                        group["meta"] = event
                    elif payload != group["meta"]["payload"]:
                        warnings.append("同一会话存在不同的会话元数据，请核对同步或分支记录")
                    continue
                timestamp = token_usage._timestamp_utc(event.get("timestamp"))
                if timestamp is not None:
                    previous_time = timestamp
                elif token_usage._is_replay_handoff(event):
                    # Untimed replay boundaries follow preceding snapshots,
                    # matching their position in the original append-only log.
                    event["timestamp"] = previous_time.isoformat()
                key = json.dumps(event, sort_keys=True, separators=(",", ":"))
                is_token = payload.get("type") == "token_count"
                if key in group["events"]:
                    duplicates += int(is_token)
                    continue
                if is_token:
                    timestamp = event["timestamp"]
                    accounting = json.dumps(payload["info"], sort_keys=True)
                    if timestamp in group["tokens"] and group["tokens"][timestamp] != accounting:
                        warnings.append("同一会话同一时间存在不同 token 记录，已保留并标记冲突")
                    group["tokens"][timestamp] = accounting
                total_bytes += len(key.encode("utf-8"))
                if total_bytes > _MAX_MERGED_BYTES:
                    raise remote_usage.RemoteUsageError("汇总数据过大，请减少所选设备")
                group["events"][key] = event
    threads = []
    def order(event):
        timestamp = token_usage._timestamp_utc(event.get("timestamp"))
        payload = event["payload"]
        priority = (0 if event["type"] == "turn_context" else 3 if token_usage._is_replay_handoff(event)
                    else 2 if payload.get("type") == "token_count" else 1)
        # Equal-time conflicts have a deterministic baseline order.
        cumulative = payload.get("info", {}).get("total_token_usage", {}).get("total_tokens", 0)
        return (timestamp or dt.datetime.min.replace(tzinfo=dt.timezone.utc), priority, cumulative)
    for group in groups.values():
        events = sorted(group["events"].values(), key=order)
        if group["meta"] is not None:
            events.insert(0, group["meta"])
        threads.append({"record": group["record"], "events": events})
    return {"schema": 1, "threads": threads, "warnings": list(dict.fromkeys(warnings)), "deduplicated_events": duplicates}


class AggregateUsageSource:
    """One immutable selection with parallel reads and a shared merged cache."""

    def __init__(self, source_ids, source_factory, local_snapshot=None):
        self.source_ids = tuple(_validate_selection(list(source_ids)))
        self.source_factory = source_factory
        self.local_snapshot = local_snapshot or globals()["local_snapshot"]
        self._lock = threading.RLock()
        self._temporary = None
        self._attempted_at = 0.0
        self._fetched_at = 0.0
        self._devices = []
        self._warnings = []
        self._deduplicated_events = 0

    def _read_source(self, source_id, force):
        device = {"id": source_id, "label": "本机" if source_id == "local" else source_id[4:], "state": "failed", "fetched_at": 0, "error": ""}
        try:
            if source_id == "local":
                snapshot = self.local_snapshot()
                device.update(state="fresh", fetched_at=time.time())
            else:
                source = self.source_factory(source_id)
                snapshot = source.snapshot(force=force)
                status = source.status()
                device.update(label=status.get("label", device["label"]),
                              state="cached" if status.get("stale") else "fresh",
                              fetched_at=status.get("fetched_at", 0), error=status.get("error", ""))
            return device, snapshot
        except Exception:
            device["error"] = "读取失败，请检查设备配置和日志"
            return device, None

    def refresh(self, force=False):
        with self._lock:
            if not force and self._temporary is not None and time.time() - self._attempted_at < remote_usage.SNAPSHOT_TTL_SECONDS:
                return
            self._attempted_at = time.time()
            with ThreadPoolExecutor(max_workers=min(4, len(self.source_ids))) as executor:
                results = list(executor.map(lambda source_id: self._read_source(source_id, force), self.source_ids))
            devices = [device for device, _ in results]
            snapshots = [(device["id"], snapshot) for device, snapshot in results if snapshot is not None]
            self._devices = devices
            if not snapshots:
                if self._temporary is None:
                    raise remote_usage.RemoteUsageError("所选设备均无法读取，尚无可用汇总")
                self._warnings = ["所有设备读取失败；显示上次汇总缓存"]
                return
            merged = merge_snapshots(snapshots)
            warnings = list(merged["warnings"])
            for device in devices:
                if device["state"] != "fresh":
                    warnings.append(f"{device['label']}: {'显示上次读取的缓存' if device['state'] == 'cached' else '未纳入本次汇总'}")
            temporary = tempfile.TemporaryDirectory(prefix="CodexBar-aggregate-")
            try:
                remote_usage.materialize_snapshot(merged, Path(temporary.name))
            except Exception:
                temporary.cleanup()
                raise
            previous = self._temporary
            self._temporary = temporary
            self._warnings = warnings
            self._deduplicated_events = merged["deduplicated_events"]
            self._fetched_at = time.time()
            if previous is not None:
                previous.cleanup()

    def status(self):
        with self._lock:
            counts = {state: sum(device["state"] == state for device in self._devices) for state in ("fresh", "cached", "failed")}
            return {"id": "aggregate", "label": "全部已选设备（汇总）", "aggregate": True, "remote": False,
                    "fetched_at": self._fetched_at, "stale": bool(counts["cached"] or counts["failed"]),
                    "incomplete": bool(self._warnings), "error": "部分汇总" if self._warnings else "",
                    "warnings": list(self._warnings), "devices": [dict(device) for device in self._devices],
                    "selected_count": len(self.source_ids), "fresh_count": counts["fresh"],
                    "cached_count": counts["cached"], "failed_count": counts["failed"],
                    "deduplicated_events": self._deduplicated_events}

    def _collect(self, method, *args, **kwargs):
        with self._lock:
            self.refresh()
            result = method(*args, codex_home=self._temporary.name, use_cache=False, **kwargs)
            targets = result if isinstance(result, list) else [result, *result.get("buckets", [])]
            for item in targets:
                item["warnings"] = list(dict.fromkeys([*item.get("warnings", []), *self._warnings]))
                item["incomplete"] = bool(item["warnings"])
            return result

    def collect_usage_days(self, days=30, anchor_date=None, use_cache=True):
        return self._collect(token_usage.collect_usage_days, days=days, anchor_date=anchor_date)

    def collect_usage_range(self, period, anchor_date=None, use_cache=True):
        return self._collect(token_usage.collect_usage_range, period, anchor_date=anchor_date)

    def collect_today_usage(self, use_cache=True):
        return self._collect(token_usage.collect_today_usage)

    def collect_thread_usage_for_day(self, day, use_cache=False, progress_callback=None):
        return self._collect(token_usage.collect_thread_usage_for_day, day, progress_callback=progress_callback)

    def close(self):
        with self._lock:
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
