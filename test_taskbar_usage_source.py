"""Taskbar source switching without network, credentials, or real SSH."""

import unittest
from unittest import mock

from codexbar import config, remote_usage, token_usage, ui


SOURCES = [
    {"id": "local", "label": "本机", "remote": False},
    {"id": "ssh:alpha", "label": "服务器 A", "remote": True},
    {"id": "ssh:beta", "label": "服务器 B", "remote": True},
]


class TaskbarUsageSourceTests(unittest.TestCase):
    def setUp(self):
        self.widget = widget = object.__new__(ui.QuotaWidget)
        widget.root = mock.Mock()
        widget.settings = dict(config.DEFAULTS)
        widget.data = widget._empty_data()
        widget._remote_usage_sources = {}
        widget._usage_source_status = widget._usage_selection_status()
        widget._refresh_generation = 0
        widget._refresh_in_progress = False
        widget._refresh_pending = False
        widget._refresh_after_id = None
        widget._closed = False
        widget._status_code = None
        widget._context_menu_open = False
        widget._persist_settings = mock.Mock(return_value=True)
        widget._redraw = mock.Mock()
        widget._position_at_taskbar = mock.Mock()
        widget._schedule_next = mock.Mock()
        self.patch = mock.patch.object(remote_usage, "discover_sources", return_value=SOURCES)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        config_patch = mock.patch.object(config, "load_config", return_value=dict(config.DEFAULTS))
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_source_menu_callbacks_select_the_matching_host_and_mark_current(self):
        widget = self.widget
        widget.settings["usage_source"] = "ssh:alpha"
        widget.refresh_async = mock.Mock()
        parent, submenu = mock.Mock(), mock.Mock()
        with mock.patch.object(ui.tk, "Menu", return_value=submenu):
            widget._add_usage_source_menu(parent, ("Segoe UI", 9))
        entries = submenu.add_command.call_args_list
        self.assertEqual([entry.kwargs["label"] for entry in entries],
                         ["本机", "✓ 服务器：服务器 A", "服务器：服务器 B"])
        parent.add_cascade.assert_called_once_with(label="用量来源：服务器 A", menu=submenu)
        entries[2].kwargs["command"]()
        self.assertEqual(widget.settings["usage_source"], "ssh:beta")
        self.assertEqual(widget._usage_source_status["label"], "服务器 B")
        widget._persist_settings.assert_called_once_with(widget.root)

    def test_switch_clears_previous_device_numbers_without_clearing_account_quota(self):
        widget = self.widget
        widget.data = {"rows": {"w": {"remain": 67}}, "usage": {"tokens": "9.9M", "cost": "$88"}}
        widget._refresh_in_progress = True
        widget._switch_usage_source("ssh:alpha")
        self.assertEqual(widget.data["rows"]["w"]["remain"], 67)
        self.assertEqual(widget.data["usage"], {"tokens": "--", "cost": "$--"})
        self.assertEqual(widget._usage_token_text("--"), "远程 …")
        self.assertTrue(widget._refresh_pending)
        self.assertEqual(widget._refresh_generation, 1)

    def test_failed_config_save_keeps_existing_selection_and_numbers(self):
        widget = self.widget
        widget.data["usage"] = {"tokens": "9.9M", "cost": "$88"}
        widget._persist_settings.return_value = False
        widget.refresh_async = mock.Mock()
        widget._switch_usage_source("ssh:alpha")
        self.assertEqual(widget.settings["usage_source"], "local")
        self.assertEqual(widget.data["usage"]["tokens"], "9.9M")
        widget.refresh_async.assert_not_called()

    def test_local_selection_uses_only_local_parser(self):
        usage = token_usage.empty_usage()
        with mock.patch.object(token_usage, "collect_today_usage", return_value=usage) as local, \
                mock.patch.object(remote_usage, "RemoteUsageSource") as remote:
            result, status = self.widget._collect_selected_usage()
        self.assertIs(result, usage)
        self.assertFalse(status["remote"])
        local.assert_called_once_with()
        remote.assert_not_called()

    def test_remote_selection_uses_remote_parser_and_retains_stale_marker(self):
        self.widget.settings["usage_source"] = "ssh:alpha"
        source = mock.Mock()
        usage = token_usage.empty_usage()
        usage.update(total_tokens=1_200_000, cost_usd=1.23, incomplete=True)
        source.collect_today_usage.return_value = usage
        source.status.return_value = {"id": "ssh:alpha", "label": "服务器 A", "remote": True,
                                      "stale": True, "error": "离线；显示上次读取的数据"}
        with mock.patch.object(remote_usage, "RemoteUsageSource", return_value=source) as remote, \
                mock.patch.object(token_usage, "collect_today_usage") as local:
            result, status = self.widget._collect_selected_usage()
            self.widget._collect_selected_usage()
        remote.assert_called_once_with("alpha", "服务器 A")
        local.assert_not_called()
        self.assertTrue(status["stale"])
        self.assertEqual(self.widget._usage_labels(result), {"tokens": "~1.2M", "cost": "~$1.23"})

    def test_initial_remote_failure_has_no_local_fallback_or_zero(self):
        widget = self.widget
        widget.settings["usage_source"] = "ssh:alpha"
        source = mock.Mock()
        source.collect_today_usage.side_effect = remote_usage.RemoteUsageError("SSH 读取失败")
        with mock.patch.object(remote_usage, "RemoteUsageSource", return_value=source), \
                mock.patch.object(token_usage, "collect_today_usage") as local, \
                mock.patch.object(ui.diagnostics, "log_exception"):
            usage, status = widget._collect_selected_usage()
        self.assertIsNone(usage)
        self.assertEqual(status["error"], "SSH 读取失败")
        local.assert_not_called()
        widget._usage_source_status = status
        self.assertEqual(widget._usage_token_text(widget._usage_labels(usage)["tokens"]), "SSH ERR")

    def test_removed_saved_host_is_not_silently_replaced_by_local(self):
        self.widget.settings["usage_source"] = "ssh:removed"
        with mock.patch.object(token_usage, "collect_today_usage") as local, \
                mock.patch.object(ui.diagnostics, "log_exception"):
            usage, status = self.widget._collect_selected_usage()
        self.assertIsNone(usage)
        self.assertTrue(status["error"])
        self.assertEqual(status["id"], "ssh:removed")
        local.assert_not_called()

    def test_old_device_result_cannot_overwrite_new_selection(self):
        widget = self.widget
        widget._refresh_generation = 2
        widget._usage_source_status = {"id": "local", "label": "本机", "remote": False}
        widget._finish_refresh(1, {"plan": "plus"}, token_usage.empty_usage(), None,
                               usage_status={"id": "ssh:alpha", "label": "A", "remote": True})
        self.assertEqual(widget._usage_source_status["id"], "local")
        self.assertEqual(widget.data["usage"]["tokens"], "--")

    def test_auth_error_still_displays_the_selected_server_usage(self):
        widget = self.widget
        widget._refresh_generation = 1
        usage = token_usage.empty_usage()
        usage.update(total_tokens=2_300_000, cost_usd=2.34)
        widget._finish_refresh(1, None, usage, "AUTH", usage_status={
            "id": "ssh:alpha", "label": "服务器 A", "remote": True, "error": ""})
        self.assertEqual(widget.data["usage"]["tokens"], "2.3M")
        self.assertEqual(widget._usage_token_text("2.3M"), "远程 2.3M")
        self.assertEqual(widget._status_code, "AUTH")

    def test_display_settings_cancel_does_not_revert_changed_source(self):
        widget = self.widget
        snapshot = dict(config.DEFAULTS)
        widget.settings.update(width=440, usage_source="ssh:alpha")
        widget._apply_widget_geometry_from_settings = mock.Mock()
        with mock.patch.object(ui, "set_colors"):
            widget._restore_settings_snapshot(snapshot)
        self.assertEqual(widget.settings["width"], snapshot["width"])
        self.assertEqual(widget.settings["usage_source"], "ssh:alpha")

    def test_source_switch_saves_only_source_without_committing_display_preview(self):
        widget = self.widget
        widget.settings["width"] = 440
        widget.refresh_async = mock.Mock()
        saved = []
        widget._persist_settings.side_effect = lambda parent: saved.append(dict(widget.settings)) or True
        widget._switch_usage_source("ssh:alpha")
        self.assertEqual(saved[0]["usage_source"], "ssh:alpha")
        self.assertEqual(saved[0]["width"], config.DEFAULTS["width"])
        self.assertEqual(widget.settings["width"], 440)


if __name__ == "__main__":
    unittest.main()
