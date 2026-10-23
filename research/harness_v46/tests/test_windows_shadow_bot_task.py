"""Windows Bot task installer is opt-in and isolated from V4.5/V4.6."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research.harness_v46 import shadow_bot as bot


ROOT = Path(bot.__file__).resolve().parent
INSTALLER = ROOT / "windows_shadow_bot_tasks.ps1"
HANDLER = ROOT / "invoke_v47_shadow_bot.ps1"


class WindowsBotTaskSafetyTests(unittest.TestCase):
    def test_installer_requires_explicit_install_and_refuses_task_overwrite(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("[switch]$Install", text)
        self.assertIn("if (-not $Install)", text)
        self.assertIn("NOT_INSTALLED:", text)
        self.assertIn("TASK_ALREADY_EXISTS_REFUSING_OVERWRITE", text)
        self.assertIn("$TaskName = 'SSQDLT-V47-SHADOW-BOT'", text)
        self.assertNotIn("SSQDLT-V46-SHADOW", text)
        self.assertNotIn("SSQDLT-V47-SHADOW'", text)  # no existing task collision
        self.assertNotRegex(text, r"(?m)^Register-ScheduledTask.*-Force")
        self.assertNotRegex(text, r"(?mi)^\s*(?:Unregister|Stop|Disable)-ScheduledTask")
        self.assertNotIn("Start-ScheduledTask", text)

    def test_task_retries_every_thirty_minutes_without_parallel_overlap(self):
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("-AtStartup", text)
        self.assertIn("New-TimeSpan -Minutes 30", text)
        self.assertIn("-MultipleInstances IgnoreNew", text)
        self.assertIn("-StartWhenAvailable", text)
        self.assertIn("V4.7 SSQ/DLT SHADOW Bot: research-only", text)
        self.assertIn("formal A=0, NO_EDGE", text)

    def test_task_executes_real_bot_module_not_legacy_schedule(self):
        install = INSTALLER.read_text(encoding="utf-8")
        invoke = HANDLER.read_text(encoding="utf-8")
        self.assertIn("invoke_v47_shadow_bot.ps1", install)
        self.assertIn("-m research.harness_v46.shadow_bot --config $ConfigFile", invoke)
        self.assertIn("SHADOW_BOT_TICK_FAILED", invoke)
        self.assertIn("SHADOW_BOT_TICK_EXIT_CODE", invoke)
        self.assertIn("Set-Location -LiteralPath $RepositoryRoot", invoke)
        self.assertNotIn("-m research.harness_v46.schedule", invoke)
        self.assertNotIn("NO_EDGE_CONFIRMED", invoke)

    @unittest.skipUnless(os.name == "nt", "Requires Windows PowerShell parser")
    def test_real_windows_powershell_ast_parse(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell executable")
        for path in (INSTALLER, HANDLER):
            script = (
                "$tokens=$null;$errors=$null;"
                "[void][System.Management.Automation.Language.Parser]::ParseFile("
                "'" + str(path).replace("'", "''") + "',[ref]$tokens,[ref]$errors);"
                "if($errors.Count -gt 0){$errors|Out-String|Write-Error;exit 1}"
            )
            proc = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, str(path) + "\n" + proc.stderr + proc.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows dry-run behavior")
    def test_real_windows_installer_dry_run_does_not_register_task(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell executable")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "receipts").mkdir()
            (tmp / "snapshots.json").write_text("{}", encoding="utf-8")
            config = tmp / "config.json"
            config.write_text(json.dumps({
                "schema": "V47-SHADOW-BOT-CONFIG-1",
                "snapshot_bundle": "snapshots.json",
                "database": "research.sqlite3",
                "result_bundle": "results.json",
                "receipts_dir": "receipts",
            }), encoding="utf-8")
            proc = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
                 "-ConfigFile", str(config),
                 "-PythonExe", sys.executable,
                 "-RepositoryRoot", str(ROOT.parent.parent)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("NOT_INSTALLED:", proc.stdout)
            self.assertIn("formal_A=0, NO_EDGE", proc.stdout)


if __name__ == "__main__":
    unittest.main()
