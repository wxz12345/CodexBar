"""Tests for the persisted taskbar usage source setting."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codexbar import config


class UsageSourceConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.config_path = root / "config.json"
        self.legacy_path = root / "legacy.json"
        self.older_legacy_path = root / "older-legacy.json"

        for name, value in (
            ("CFG_PATH", self.config_path),
            ("LEGACY_CFG_PATH", self.legacy_path),
            ("OLDER_LEGACY_CFG_PATH", self.older_legacy_path),
        ):
            patcher = mock.patch.object(config, name, os.fspath(value))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_config(self, values):
        self.config_path.write_text(json.dumps(values), encoding="utf-8")

    def test_missing_config_defaults_usage_source_to_local(self):
        loaded = config.load_config()

        self.assertEqual(loaded["usage_source"], "local")
        self.assertEqual(loaded["width"], config.DEFAULTS["width"])

    def test_valid_ssh_source_is_loaded(self):
        self._write_config({"usage_source": "ssh:gpu_01.example-host"})

        self.assertEqual(config.load_config()["usage_source"], "ssh:gpu_01.example-host")

    def test_malformed_sources_fall_back_to_local(self):
        malformed = (
            None,
            7,
            "SSH:host",
            "ssh:",
            "ssh:contains space",
            "ssh:host/path",
            "ssh:-starts-with-hyphen",
            "ssh:" + "a" * 255,
        )
        for value in malformed:
            with self.subTest(value=value):
                self._write_config({"usage_source": value})
                self.assertEqual(config.load_config()["usage_source"], "local")

    def test_save_and_load_round_trip_preserves_source_and_other_settings(self):
        settings = config.load_config()
        settings["usage_source"] = "ssh:build-host_2"
        settings["width"] = 360
        settings["refresh_minutes"] = 7

        config.save_config(settings)
        loaded = config.load_config()

        self.assertEqual(loaded["usage_source"], "ssh:build-host_2")
        self.assertEqual(loaded["width"], 360)
        self.assertEqual(loaded["refresh_minutes"], 7)

    def test_legacy_migration_preserves_valid_source_and_other_settings(self):
        self.legacy_path.write_text(
            json.dumps(
                {
                    "usage_source": "ssh:remote_box",
                    "height": 46,
                    "color_warn": "#123456",
                }
            ),
            encoding="utf-8",
        )

        loaded = config.load_config()

        self.assertEqual(loaded["usage_source"], "ssh:remote_box")
        self.assertEqual(loaded["height"], 46)
        self.assertEqual(loaded["color_warn"], "#123456")
        self.assertTrue(self.config_path.exists())
        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["usage_source"], "ssh:remote_box")


if __name__ == "__main__":
    unittest.main()
