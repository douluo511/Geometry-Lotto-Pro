"""Actual PowerShell/export contracts; real boot/power loss are never emulated."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from research.ssq_dlt_v45.windows.container_loop import next_half_hour


ROOT = Path(__file__).resolve().parents[3]
WINDOWS = ROOT / "research" / "ssq_dlt_v45" / "windows"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
HAS_WINDOWS = os.name == "nt" and POWERSHELL.is_file()


class SchedulerPolicyTests(unittest.TestCase):
    def test_weekly_jst_boot_catchup_and_failure_policy(self):
        task = ET.parse(WINDOWS / "task-template.xml").getroot()
        self.assertEqual(task.findtext("t:Triggers/t:BootTrigger/t:Delay", namespaces=NS), "PT30S")
        self.assertEqual(task.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=NS), "2020-01-06T07:00:00Z")
        days = task.find("t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek", NS)
        self.assertEqual([item.tag.rsplit("}", 1)[1] for item in days], ["Monday", "Wednesday", "Saturday"])
        self.assertEqual(task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS), "PT30M")
        self.assertIsNone(task.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Duration", NS))
        expected = {"MultipleInstancesPolicy": "IgnoreNew", "StartWhenAvailable": "true", "Hidden": "true", "RunOnlyIfNetworkAvailable": "false", "ExecutionTimeLimit": "PT10M"}
        for key, value in expected.items():
            self.assertEqual(task.findtext(f"t:Settings/t:{key}", namespaces=NS), value)
        self.assertEqual(task.findtext("t:Settings/t:RestartOnFailure/t:Count", namespaces=NS), "3")
        self.assertEqual(task.findtext("t:Settings/t:RestartOnFailure/t:Interval", namespaces=NS), "PT1M")

    def test_container_next_half_hour_is_strictly_future(self):
        for timestamp, expected in ((0, 1800), (1799.9, 1800), (1800, 3600), (3599.99, 3600)):
            self.assertEqual(next_half_hour(timestamp), expected)


@unittest.skipUnless(HAS_WINDOWS, "Actual Windows PowerShell required")
class WindowsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="glp-v45-windows-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.repo = self.directory / "repository & local"
        self.module = self.repo / "research" / "ssq_dlt_v45"
        self.module.mkdir(parents=True)
        shutil.copytree(WINDOWS, self.module / "windows", ignore=shutil.ignore_patterns("__pycache__"))
        # Fixture proves the real launcher argument/exit/log contract, and does
        # not pretend to be a production model or a successful runtime test.
        (self.module / "runtime.py").write_text(
            "import argparse,json,sys\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser(); p.add_argument('--config',required=True); a=p.parse_args()\n"
            "c=json.loads(Path(a.config).read_text()); print(json.dumps({'fixture':True,'config':a.config}))\n"
            "print('fixture stderr', file=sys.stderr)\nsys.exit(c.get('exit_code',0))\n", encoding="utf-8")
        self.config = self.directory / "runtime & local.json"
        self.config.write_text("{}", encoding="utf-8")
        self.logs = self.directory / "launcher logs"
        self.xml = self.directory / "reviewed task.xml"

    def execute(self, script, *arguments):
        return subprocess.run([str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.module / "windows" / script), *map(str, arguments)], text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=45)

    def arguments(self):
        return ["-PythonPath", sys.executable, "-RepositoryPath", self.repo, "-ConfigPath", self.config, "-LauncherLogDirectory", self.logs]

    def test_actual_powershell_syntax(self):
        result = self.execute("Probe-Scheduler.ps1", "-EvidencePath", self.directory / "probe.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(all(item["status"] == "PASS" for item in receipt["syntax"]))
        self.assertIn(receipt["scheduler_com"], ("PASS", "BLOCKED"))
        self.assertIn(receipt["scheduler_cim"], ("PASS", "BLOCKED"))
        for name in ("durable_install", "real_boot", "thirty_minute_elapsed_trigger", "power_cycle"):
            self.assertEqual(receipt[name], "NOT_RUN")

    def test_export_is_hidden_quoted_and_creates_no_runtime_output(self):
        result = self.execute("Install-Tasks.ps1", *self.arguments(), "-ExportXmlPath", self.xml)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "EXPORTED_ONLY")
        self.assertFalse(receipt["installed"])
        self.assertFalse(self.logs.exists())
        task = ET.parse(self.xml).getroot()
        arguments = task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
        self.assertIn("-WindowStyle Hidden", arguments)
        self.assertIn(f'"{self.config.resolve()}"', arguments)
        self.assertNotIn("__", arguments)

    def test_export_does_not_replace_reviewed_file(self):
        self.xml.write_bytes(b"reviewed bytes")
        result = self.execute("Install-Tasks.ps1", *self.arguments(), "-ExportXmlPath", self.xml)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), b"reviewed bytes")

    def test_relative_config_rejected(self):
        arguments = self.arguments()
        arguments[arguments.index("-ConfigPath") + 1] = "relative.json"
        result = self.execute("Install-Tasks.ps1", *arguments, "-ExportXmlPath", self.xml)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.xml.exists())

    def test_non_python_rejected(self):
        arguments = self.arguments()
        arguments[arguments.index("-PythonPath") + 1] = POWERSHELL
        result = self.execute("Install-Tasks.ps1", *arguments, "-ExportXmlPath", self.xml)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.xml.exists())

    def test_install_requires_current_acceptance_before_any_scheduler_write(self):
        result = self.execute("Install-Tasks.ps1", *self.arguments(), "-ExportXmlPath", self.xml, "-Install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("integration acceptance receipt", result.stderr)
        self.assertTrue(self.xml.exists())

    def test_launcher_real_execution_preserves_streams_and_unique_receipts(self):
        for _ in range(2):
            result = self.execute("Invoke-Runtime.ps1", *self.arguments())
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual((receipt["status"], receipt["exit_code"]), ("PASS", 0))
        receipts = list(self.logs.glob("*.json"))
        self.assertEqual(len(receipts), 2)
        self.assertEqual(len(list(self.logs.glob("*.stdout.log"))), 2)
        self.assertTrue(all("fixture stderr" in path.read_text(encoding="utf-8-sig") for path in self.logs.glob("*.stderr.log")))

    def test_launcher_propagates_failure_and_retains_diagnostics(self):
        self.config.write_text('{"exit_code": 17}', encoding="utf-8")
        result = self.execute("Invoke-Runtime.ps1", *self.arguments())
        self.assertEqual(result.returncode, 17, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["status"], receipt["exit_code"]), ("FAIL", 17))
        self.assertEqual(len(list(self.logs.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
