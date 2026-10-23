"""Opt-in unattended local Bot runner: no scheduler installation in CI."""
import os
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ClosedLoopSchedulerTests(unittest.TestCase):
    def test_configured_runner_and_install_script_exist_and_do_not_auto_install(self):
        handler = (ROOT / "invoke_closed_loop.ps1").read_text(encoding="utf-8")
        install = (ROOT / "windows_closed_loop_tasks.ps1").read_text(encoding="utf-8")
        self.assertIn("research.harness_v46.closed_loop", handler)
        self.assertIn("--workspace", handler)
        self.assertIn("--snapshot-bundle", handler)
        self.assertIn("closed_loop", handler)
        self.assertIn("exit_code=", handler)
        self.assertIn("SSQDLT-V47-CLOSED-LOOP-SHADOW", install)
        self.assertIn("[switch]$Install", install)
        self.assertIn("if (-not $Install)", install)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", install)
        self.assertIn("-RepetitionInterval", install)
        self.assertIn("IgnoreNew", install)
        self.assertIn("TASK_ALREADY_EXISTS_REFUSING_OVERWRITE", install)
        self.assertNotIn("Register-ScheduledTask -Force", install)
        self.assertNotIn("Register-ScheduledTask -TaskName $TaskName -Force", install)

    @unittest.skipUnless(os.name == "nt", "Windows dry run only")
    def test_windows_real_dry_run_does_not_register_task(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell installed")
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "bot-config.json"
            cfg_path.write_text(json.dumps({
                "repository_root": str(ROOT.parents[1]),
                "python_exe": "python.exe",
                "workspace": str(Path(td) / "workspace"),
                "log_path": str(Path(td) / "bot.log"),
                "snapshot_bundle": None,
                "research_history_bundle": None
            }), encoding="utf-8")
            out = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "windows_closed_loop_tasks.ps1"),
                 "-ConfigFile", str(cfg_path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
            self.assertIn("NOT_INSTALLED", out.stdout)
            self.assertFalse((Path(td) / "workspace" / "ledger.sqlite3").exists())

    @unittest.skipUnless(os.name == "nt", "PowerShell AST on Windows CI only")
    def test_windows_powershell_ast_syntax(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell installed")
        for name in ("windows_closed_loop_tasks.ps1", "invoke_closed_loop.ps1"):
            file = ROOT / name
            code = ("$tokens=$null;$errors=$null;"
                    "[void][System.Management.Automation.Language.Parser]::ParseFile("
                    "'" + str(file).replace("'", "''") + "',[ref]$tokens,[ref]$errors);"
                    "if($errors.Count -gt 0){$errors|Out-String|Write-Error;exit 1}")
            run = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", code],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)


if __name__ == "__main__":
    unittest.main()
