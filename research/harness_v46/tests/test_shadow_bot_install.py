"""Task installer contract tests. Parsing is not proof of real host enrollment."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from research.harness_v46 import shadow_bot


class ShadowBotInstallerTests(unittest.TestCase):
    def test_install_never_happens_on_preview_or_existing_task(self):
        path = Path(shadow_bot.__file__).with_name("windows_shadow_bot_task.ps1")
        raw = path.read_text(encoding="utf-8")
        self.assertIn("[switch]$Install", raw)
        self.assertIn("if (-not $Install)", raw)
        self.assertIn("NOT_INSTALLED:", raw)
        self.assertIn("BOT_TASK_ALREADY_EXISTS_REFUSING_OVERWRITE", raw)
        self.assertNotIn("Register-ScheduledTask -Force", raw)
        self.assertIn("Register-ScheduledTask", raw)
        self.assertIn("SSQDLT-V47-SHADOW-BOT", raw)
        self.assertIn("formal", raw.lower())
        self.assertIn("NO_EDGE", raw)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", raw)
        self.assertIn("New-TimeSpan -Minutes 30", raw)
        self.assertIn("-MultipleInstances IgnoreNew", raw)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser only")
    def test_opt_in_installer_has_valid_powershell_syntax(self):
        exe = shutil.which("powershell.exe")
        if exe is None:
            self.skipTest("Windows PowerShell unavailable")
        script = Path(shadow_bot.__file__).with_name("windows_shadow_bot_task.ps1")
        ps_literal = "'" + str(script).replace("'", "''") + "'"
        check = (
            "$tokens=$null;$errors=$null;"
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            + ps_literal + ",[ref]$tokens,[ref]$errors);"
            "if($errors.Count -gt 0){$errors|Out-String|Write-Error;exit 1}"
        )
        result = subprocess.run([exe, "-NoProfile", "-NonInteractive",
                                 "-Command", check], capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
