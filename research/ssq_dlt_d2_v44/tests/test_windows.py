"""Scheduler contract and actual Windows wrapper checks; never claim reboot PASS."""
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
WINDOWS = ROOT / "research" / "ssq_dlt_d2_v44" / "windows"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
HAS_WINDOWS = os.name == "nt" and POWERSHELL.is_file()


class SchedulerPolicyTests(unittest.TestCase):
    def test_task_boot_repetition_retry_and_no_overlap(self):
        task = ET.parse(WINDOWS / "task-template.xml").getroot()
        self.assertEqual(task.findtext("t:Triggers/t:BootTrigger/t:Enabled", namespaces=NS), "true")
        self.assertEqual(task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS), "PT30M")
        self.assertIsNone(task.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Duration", NS))
        self.assertEqual(task.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS), "IgnoreNew")
        self.assertEqual(task.findtext("t:Settings/t:RestartOnFailure/t:Count", namespaces=NS), "3")
        self.assertEqual(task.findtext("t:Settings/t:RestartOnFailure/t:Interval", namespaces=NS), "PT1M")
        self.assertEqual(task.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=NS), "PT5M")
        self.assertEqual(task.findtext("t:Settings/t:Hidden", namespaces=NS), "true")
        self.assertEqual(task.findtext("t:Settings/t:RunOnlyIfNetworkAvailable", namespaces=NS), "false")


@unittest.skipUnless(HAS_WINDOWS, "Actual Windows PowerShell is required; no reboot emulation")
class WindowsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glp-v44-status-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.database = self.directory / "ledger.sqlite"
        self.output = self.directory / "status output"
        self.xml = self.directory / "status task.xml"

    def execute(self, script, *arguments):
        return subprocess.run(
            [str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(WINDOWS / script), *map(str, arguments)],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=35,
        )

    def install_arguments(self):
        return ["-PythonPath", sys.executable, "-RepositoryPath", ROOT,
                "-DatabasePath", self.database, "-OutputDirectory", self.output,
                "-ExportXmlPath", self.xml]

    def runtime_arguments(self):
        return ["-PythonPath", sys.executable, "-RepositoryPath", ROOT,
                "-DatabasePath", self.database, "-OutputDirectory", self.output]

    def test_dry_export_is_valid_hidden_and_does_not_run_runtime(self):
        result = self.execute("Install-StatusTask.ps1", *self.install_arguments())
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "EXPORTED_ONLY")
        self.assertFalse(receipt["installed"])
        self.assertFalse(self.database.exists())
        self.assertFalse(self.output.exists())
        task = ET.parse(self.xml).getroot()
        self.assertEqual(task.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS), str(ROOT))
        arguments = task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
        self.assertIn("-WindowStyle Hidden", arguments)
        self.assertIn(str(self.output), arguments)
        self.assertIn(str(Path(sys.executable)), arguments)
        self.assertNotIn("__", arguments)

    def test_export_refuses_to_replace_reviewed_xml(self):
        self.xml.write_bytes(b"reviewed-original")
        result = self.execute("Install-StatusTask.ps1", *self.install_arguments())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), b"reviewed-original")
        self.assertFalse(self.database.exists())

    def test_relative_database_rejected_before_export(self):
        arguments = self.install_arguments()
        arguments[arguments.index("-DatabasePath") + 1] = "relative.sqlite"
        result = self.execute("Install-StatusTask.ps1", *arguments)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.xml.exists())

    def test_non_python_executable_rejected(self):
        arguments = self.install_arguments()
        arguments[arguments.index("-PythonPath") + 1] = POWERSHELL
        result = self.execute("Install-StatusTask.ps1", *arguments)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.xml.exists())

    def test_status_runner_twice_preserves_outputs_and_admission(self):
        for _ in range(2):
            result = self.execute("Invoke-Status.ps1", *self.runtime_arguments())
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual((receipt["R2"], receipt["formal_A"], receipt["decision"], receipt["prediction_calls"]),
                             ("BLOCKED", 0, "NO_EDGE", 0))
        reports = list(self.output.glob("*/status.json"))
        self.assertEqual(len(reports), 2)
        self.assertEqual(len({json.loads(path.read_text(encoding="utf-8"))["run_id"] for path in reports}), 2)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM heartbeats").fetchone()[0], 2)

    def test_runtime_failure_propagates_nonzero(self):
        self.database.write_bytes(b"intentionally-not-a-sqlite-database")
        before = self.database.read_bytes()
        result = self.execute("Invoke-Status.ps1", *self.runtime_arguments())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "FAIL"', result.stderr)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(list(self.output.glob("*/status.json")), [])
        failures = list((self.output / "launcher-failures").glob("*.json"))
        self.assertEqual(len(failures), 1)
        failure = json.loads(failures[0].read_text(encoding="utf-8"))
        self.assertEqual((failure["status"], failure["exit_code"], failure["R2"]), ("FAIL", result.returncode, "BLOCKED"))


if __name__ == "__main__":
    unittest.main()
