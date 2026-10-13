"""Offline native-runtime check using synthetic accounting data only."""

import datetime as dt
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk

from . import aggregate_usage, config, pricing, runtime, token_usage, ui, web_dashboard


def write_report(destination: str) -> bool:
    report = {"success": False, "frozen": runtime.is_frozen(), "synthetic_data": True}
    previous_home = os.environ.get("CODEX_HOME")
    original_home = config.HOME
    original_refresh = pricing.refresh_prices
    original_prices = config.OFFICIAL_PRICES_PATH, config.MODEL_PRICES_PATH
    original_config_path = config.CFG_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="CodexBar-check-") as temporary:
            home = Path(temporary)
            os.environ["CODEX_HOME"] = str(home)
            config.HOME = str(home)
            config.OFFICIAL_PRICES_PATH = str(home / "prices.json")
            config.MODEL_PRICES_PATH = str(home / "overrides.json")
            config.CFG_PATH = str(home / "widget-config.json")
            pricing.refresh_prices = lambda *args, **kwargs: pricing.get_status()
            sessions = home / "sessions"
            sessions.mkdir()
            event = {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "type": "event_msg",
                     "payload": {"type": "token_count", "info": {"model": "gpt-5.4-mini",
                         "total_token_usage": {"input_tokens": 150, "cached_input_tokens": 20,
                                               "output_tokens": 15, "reasoning_output_tokens": 5,
                                               "total_tokens": 165}}}}
            metadata = {"type": "session_meta", "payload": {"id": "check-session"}}
            (sessions / "rollout-check.jsonl").write_text(json.dumps(metadata) + "\n" + json.dumps(event) + "\n", encoding="utf-8")
            report["check"] = "accounting"
            usage = token_usage.collect_today_usage(use_cache=False)
            if usage["total_tokens"] != 165:
                raise RuntimeError("Synthetic accounting mismatch")
            report["total_tokens"] = usage["total_tokens"]
            report["check"] = "tk"
            root = tk.Tk()
            try:
                root.withdraw()
                canvas = tk.Canvas(root, width=300, height=40)
                canvas.create_text(10, 20, text="CodexBar 165 tokens", anchor="w")
                root.update()
                report["tk"] = root.tk.call("info", "patchlevel")
                # Exercise the real menu without connecting to any SSH host.
                ssh_config = home / ".ssh" / "config"
                ssh_config.parent.mkdir()
                ssh_config.write_text("Host codexbar-self-test\n  HostName example.invalid\n", encoding="utf-8")
                widget = object.__new__(ui.QuotaWidget)
                widget.root = root
                widget.settings = dict(config.DEFAULTS)
                widget.data = widget._empty_data()
                widget._usage_source_status = widget._usage_selection_status()
                widget._context_menu_open = False
                widget.refresh_async = lambda: None
                menu = tk.Menu(root, tearoff=False)
                widget._add_usage_source_menu(menu, ("Segoe UI", 9))
                source_menu = root.nametowidget(menu.entrycget(0, "menu"))
                source_menu.invoke(1)
                saved_remote = config.load_config()["usage_source"]
                if saved_remote != "ssh:codexbar-self-test" or widget.data["usage"]["tokens"] != "--":
                    raise RuntimeError("Taskbar source selection did not persist")
                widget._usage_source_status["loading"] = False
                widget.data.update(rows={
                    "h": {"remain": 50, "reset": time.time() + 3600},
                    "w": {"remain": 80, "reset": time.time() + 604800},
                }, usage={"tokens": "123.4M", "cost": "$123.45"})
                widget.canvas = canvas
                widget.W, widget.H, widget._dpi_scale = 250, 40, 1.0
                widget._status_code = None
                widget._build_ui()
                root.update()
                texts = [item for item in canvas.find_all() if canvas.type(item) == "text"]
                fits = all(canvas.bbox(texts[offset + 2])[2] <= canvas.bbox(texts[offset + 3])[0]
                           for offset in (0, 4))
                if not fits:
                    raise RuntimeError("Taskbar source text overlaps reset time")
                source_menu.invoke(0)
                if config.load_config()["usage_source"] != "local":
                    raise RuntimeError("Taskbar local source did not persist")
                report["taskbar_source_menu"] = {"success": True, "saved_remote": saved_remote,
                                               "saved_local": "local", "minimum_width_fits": fits,
                                               "live_ssh": False}
            finally:
                root.destroy()
            report["check"] = "webview"
            import webview

            api = web_dashboard.DashboardApi()
            continuation = copy.deepcopy(event)
            continuation["timestamp"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat()
            continuation["payload"]["info"]["total_token_usage"].update(input_tokens=180, output_tokens=20, total_tokens=200)

            class SyntheticRemote:
                def snapshot(self, force=False):
                    return {"schema": 1, "warnings": [], "threads": [{
                        "record": {"id": "check-session", "model": "gpt-5.4-mini", "title": "Synthetic synced session"},
                        "events": [metadata, event, continuation]}]}

                def status(self):
                    return {"id": "ssh:codexbar-self-test", "label": "codexbar-self-test", "stale": False,
                            "fetched_at": time.time(), "error": ""}

                def close(self):
                    pass

            api._remote_sources["ssh:codexbar-self-test"] = SyntheticRemote()
            window = webview.create_window("CodexBar runtime check", web_dashboard.DASHBOARD_HTML.as_uri(),
                                           js_api=api, width=1290, height=735,
                                           min_size=(1200, 540), hidden=True)
            loaded = threading.Event()
            window.events.loaded += lambda: loaded.set()

            def verify():
                try:
                    if not loaded.wait(25):
                        raise TimeoutError("WebView did not load")
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        state = window.evaluate_js("({tokens: state.selected?.total_tokens, "
                                                   "loading: !document.getElementById('loadingOverlay').classList.contains('done'), "
                                                   "stage: document.getElementById('loadingStage').textContent, "
                                                   "detail: document.getElementById('loadingDetail').textContent, "
                                                   "apiReady: !!window.pywebview?.api, "
                                                   "scope: document.body.textContent.includes('其他设备与云端任务未纳入'), "
                                                   "accountButton: !!document.getElementById('accountUsageButton'), "
                                                   "viewportWidth: document.documentElement.clientWidth, "
                                                   "layoutFits: [...document.querySelectorAll('.layout > *, .topbar, .conversation-head')].every(el => { "
                                                   "const rect = el.getBoundingClientRect(); "
                                                   "return rect.left >= 0 && rect.right <= document.documentElement.clientWidth "
                                                   "&& el.scrollWidth <= el.clientWidth + 1; })})")
                        report["last_state"] = state
                        if state and state.get("tokens") == 165 and not state.get("loading"):
                            report["webview"] = state
                            report["success"] = bool(state.get("scope") and state.get("accountButton")
                                                     and state.get("layoutFits"))
                            break
                        time.sleep(0.2)
                    if not report["success"]:
                        report["error"] = "DashboardDidNotBecomeReady"
                        return
                    # Click the real settings dialog and save through the bridge.
                    window.evaluate_js("openAggregateSettings(); true")
                    deadline = time.monotonic() + 15
                    dialog_state = None
                    while time.monotonic() < deadline:
                        dialog_state = window.evaluate_js("({open: document.getElementById('aggregateDialog').open, "
                            "choices: document.querySelectorAll('.aggregate-choice').length, "
                            "ready: !document.getElementById('aggregateSaveButton').disabled, "
                            "fits: (() => { const el = document.getElementById('aggregateDialog'); const r = el.getBoundingClientRect(); "
                            "return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight && el.scrollWidth <= el.clientWidth + 1; })()})")
                        if dialog_state and dialog_state.get("ready") and dialog_state.get("choices") == 2:
                            break
                        time.sleep(0.2)
                    if not dialog_state or not dialog_state.get("open") or not dialog_state.get("fits"):
                        raise RuntimeError("AggregateDialogDidNotFit")
                    window.evaluate_js("document.querySelector('.aggregate-choice[value=\"ssh:codexbar-self-test\"]').checked = true; "
                                       "document.getElementById('aggregateSaveButton').click(); true")
                    deadline = time.monotonic() + 20
                    aggregate_state = None
                    while time.monotonic() < deadline:
                        aggregate_state = window.evaluate_js("({tokens: state.selected?.total_tokens, sourceId: state.sourceId, "
                            "fresh: state.source?.fresh_count, selected: state.source?.selected_count, "
                            "deduplicated: state.source?.deduplicated_events, incomplete: state.selected?.incomplete, "
                            "conversations: state.selected?.conversations?.reduce((total,row) => total + row.tokens, 0), "
                            "rangeTokens: state.range?.total_tokens, dialogOpen: document.getElementById('aggregateDialog').open, "
                            "loading: !document.getElementById('loadingOverlay').classList.contains('done'), "
                            "fits: [...document.querySelectorAll('.layout > *, .topbar, .conversation-head')].every(el => { "
                            "const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth + 1; })})")
                        if aggregate_state and aggregate_state.get("tokens") == 200 and not aggregate_state.get("loading"):
                            break
                        time.sleep(0.2)
                    report["aggregate_dashboard"] = {"dialog": dialog_state, "state": aggregate_state, "live_ssh": False}
                    report["success"] = bool(aggregate_state and aggregate_state.get("sourceId") == "aggregate"
                        and aggregate_state.get("tokens") == 200 and aggregate_state.get("fresh") == 2
                        and aggregate_state.get("selected") == 2 and aggregate_state.get("deduplicated", 0) >= 1
                        and not aggregate_state.get("incomplete") and not aggregate_state.get("dialogOpen")
                        and aggregate_state.get("conversations") == 200 and aggregate_state.get("rangeTokens") == 200
                        and aggregate_state.get("fits") and aggregate_usage.load_selected_sources() == ["local", "ssh:codexbar-self-test"])
                    if not report["success"]:
                        report["error"] = "AggregateDashboardMismatch"
                except Exception as error:
                    report["error"] = type(error).__name__
                finally:
                    window.destroy()

            webview.start(verify, gui="edgechromium", private_mode=True)
            api.close()
    except Exception as error:
        report["error"] = type(error).__name__
    finally:
        config.HOME = original_home
        config.OFFICIAL_PRICES_PATH, config.MODEL_PRICES_PATH = original_prices
        config.CFG_PATH = original_config_path
        pricing.refresh_prices = original_refresh
        if previous_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = previous_home
        token_usage.clear_usage_cache()
    Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report["success"]
