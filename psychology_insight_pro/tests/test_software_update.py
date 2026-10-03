from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software_update import (
    _load_release_config,
    launch_independent_updater,
    software_update_environment_status,
)


class SoftwareUpdateHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.main = self.root / "Psychology_Insight_Pro.exe"
        self.updater = self.root / "Psychology_Insight_Pro_Updater.exe"
        self.main.write_bytes(b"MZ-main")
        self.updater.write_bytes(b"MZ-updater")

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, *, manifest_url="https://updates.example/latest.json", trusted_hosts=None):
        value = {
            "schema": "psychology-software-update-config-v1",
            "manifest_url": manifest_url,
            "trusted_hosts": trusted_hosts or ["updates.example"],
        }
        self.main.with_name("Psychology_Insight_Pro_Update_Config.json").write_text(
            json.dumps(value), encoding="utf-8"
        )

    def test_missing_release_config_is_blocked(self):
        status = software_update_environment_status(
            main_exe=self.main,
            current_version="0.4.0",
            updater_exe=self.updater,
        )
        self.assertEqual(status["status"], "BLOCKED")
        self.assertEqual(status["checks"]["release_config"]["status"], "BLOCKED")

    def test_insecure_release_config_fails_closed(self):
        self.write_config(manifest_url="http://updates.example/latest.json")
        with self.assertRaises(RuntimeError):
            _load_release_config(self.main)

    def test_independent_updater_handoff(self):
        self._assert_independent_updater_handoff()

    def test_independent_updater_handoff_accepts_same_file_path_alias(self):
        # Windows short-name paths and normalized paths can name the same EXE.
        alias_directory = self.root / "path_alias"
        alias_directory.mkdir()
        self.updater = alias_directory / ".." / self.updater.name
        self.assertNotEqual(self.updater, self.updater.resolve())
        self._assert_independent_updater_handoff()

    def _assert_independent_updater_handoff(self):
        self.write_config()

        class Proc:
            pid = 4321

        with patch("software_update.subprocess.Popen", return_value=Proc()) as popen:
            report = launch_independent_updater(
                data_root=self.root / "data",
                current_version="0.4.0",
                main_exe=self.main,
                updater_exe=self.updater,
                parent_pid=99,
            )

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["action"], "UPDATER_HANDOFF")
        self.assertEqual(report["updater_pid"], 4321)
        self.assertTrue(report["requires_parent_exit"])
        args = popen.call_args.args[0]
        self.assertTrue(Path(args[0]).samefile(self.updater))
        self.assertIn("--parent-pid", args)
        self.assertIn("99", args)
        self.assertIn("--trusted-host", args)
        self.assertIn("updates.example", args)


if __name__ == "__main__":
    unittest.main()
