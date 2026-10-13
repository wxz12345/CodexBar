"""Offline native-runtime check using synthetic accounting data only."""

import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk

from . import config, pricing, runtime, token_usage, ui, web_dashboard


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
            (sessions / "rollout-check.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
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
                except Exception as error:
                    report["error"] = type(error).__name__
                finally:
                    window.destroy()

            webview.start(verify, gui="edgechromium", private_mode=True)
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
