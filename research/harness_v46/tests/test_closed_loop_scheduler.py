"""Opt-in unattended local Bot runner: no scheduler installation in CI."""
import os
import shutil
import subprocess
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
