"""Staged scheduler export and actual hidden PowerShell wrapper contracts.

The entry points below are temporary fixtures. No test registers a task or
pretends that XML export demonstrates a real cold boot or elapsed timer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

MODULE = Path(__file__).resolve().parents[1]
WINDOWS = MODULE / "windows"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
HAS_WINDOWS = os.name == "nt" and POWERSHELL.is_file()
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()


class StagedSchedulerPolicyTests(unittest.TestCase):
    def test_five_fixed_utc_stages_boot_catchup_and_status_recovery(self):
        task = ET.parse(WINDOWS / "task-staged-template.xml").getroot()
        calendars = task.findall("t:Triggers/t:CalendarTrigger", NS)
        self.assertEqual([node.findtext("t:StartBoundary", namespaces=NS) for node in calendars],
                         [f"2020-01-06T{clock}:00Z" for clock in ("06:10", "06:20", "06:30", "06:45", "07:00")])
        for node in calendars:
            days = node.find("t:ScheduleByWeek/t:DaysOfWeek", NS)
            self.assertEqual([day.tag.rsplit("}", 1)[1] for day in days],
                             ["Monday", "Wednesday", "Saturday"])
        self.assertEqual(task.findtext("t:Triggers/t:BootTrigger/t:Delay", namespaces=NS), "PT30S")
        self.assertEqual(task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS), "PT30M")
        self.assertEqual(task.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS), "IgnoreNew")
        self.assertEqual(task.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS), "true")
        self.assertEqual(task.findtext("t:Settings/t:RunOnlyIfNetworkAvailable", namespaces=NS), "false")


@unittest.skipUnless(HAS_WINDOWS, "Actual Windows PowerShell required")
class StagedWindowsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="glp-v45-staged-windows-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.repo = self.directory / "repository & staged"
        self.module = self.repo / "research" / "ssq_dlt_v45"
        self.module.mkdir(parents=True)
        shutil.copytree(WINDOWS, self.module / "windows", ignore=shutil.ignore_patterns("__pycache__"))
        (self.module / "runtime.py").write_text("raise SystemExit(91)\n", encoding="utf-8")
        (self.module / "workflow.py").write_text(
            "import argparse,json,sys\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()\n"
            "c=json.loads(Path(a.config).read_text());print(json.dumps({'fixture':'workflow','config':a.config}))\n"
            "print('workflow fixture stderr',file=sys.stderr);sys.exit(c.get('exit_code',0))\n", encoding="utf-8")
        self.config = self.directory / "workflow & config.json"
        self.config.write_text("{}", encoding="utf-8")
        self.logs = self.directory / "launcher logs"
        self.xml = self.directory / "staged reviewed.xml"

    def execute(self, script, *arguments):
        return subprocess.run([str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(self.module / "windows" / script), *map(str, arguments)],
                              text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=45)

    def arguments(self):
        return ["-PythonPath", sys.executable, "-RepositoryPath", self.repo,
                "-ConfigPath", self.config, "-LauncherLogDirectory", self.logs]

    def install_arguments(self):
        return [*self.arguments(), "-ExportXmlPath", self.xml, "-StagedWorkflow"]

    def acceptance(self):
        manifest = {p.relative_to(self.module).as_posix(): sha(p) for p in self.module.rglob("*")
                    if p.is_file() and p.suffix in (".py", ".ps1", ".xml")
                    and not ({"tests", "__pycache__"} & set(p.relative_to(self.module).parts))}
        return dict(status="PASS", runtime_integration="PASS", runtime_sha256=sha(self.module / "runtime.py"),
                    config_sha256=sha(self.config), workflow_sha256=sha(self.module / "workflow.py"), code_manifest=manifest)

    def reject_acceptance(self, receipt, expected):
        path = self.directory / "invalid-acceptance.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        result = self.execute("Install-Tasks.ps1", *self.install_arguments(), "-RuntimeAcceptancePath", path, "-Install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected, " ".join(result.stderr.split()))
        self.assertFalse(self.logs.exists())

    def test_staged_export_selects_workflow_without_executing_or_replacing(self):
        result = self.execute("Install-Tasks.ps1", *self.install_arguments())
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "EXPORTED_ONLY")
        self.assertTrue(receipt["staged_workflow"])
        self.assertFalse(receipt["installed"])
        self.assertFalse(self.logs.exists())
        task = ET.parse(self.xml).getroot()
        self.assertEqual(len(task.findall("t:Triggers/t:CalendarTrigger", NS)), 5)
        arguments = task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
        self.assertIn("-Mode workflow", arguments)
        self.assertIn("-WindowStyle Hidden", arguments)
        self.assertIn(f'"{self.config.resolve()}"', arguments)
        before = self.xml.read_bytes()
        repeated = self.execute("Install-Tasks.ps1", *self.install_arguments())
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(self.xml.read_bytes(), before)

    def test_missing_workflow_is_rejected_before_export(self):
        (self.module / "workflow.py").unlink()
        result = self.execute("Install-Tasks.ps1", *self.install_arguments())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workflow entry point is missing", " ".join(result.stderr.split()))
        self.assertFalse(self.xml.exists())

    def test_workflow_wrapper_executes_selected_module_and_pins_sha(self):
        result = self.execute("Invoke-Runtime.ps1", *self.arguments(), "-Mode", "workflow")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["mode"], receipt["entry_point"]), ("workflow", "research.ssq_dlt_v45.workflow"))
        self.assertEqual(receipt["workflow_sha256"], sha(self.module / "workflow.py"))
        self.assertEqual(receipt["entry_point_sha256"], receipt["workflow_sha256"])
        self.assertIn('"fixture": "workflow"', next(self.logs.glob("*.stdout.log")).read_text(encoding="utf-8-sig"))
        self.assertIn("workflow fixture stderr", next(self.logs.glob("*.stderr.log")).read_text(encoding="utf-8-sig"))

    def test_workflow_wrapper_propagates_real_process_failure(self):
        self.config.write_text('{"exit_code": 19}', encoding="utf-8")
        result = self.execute("Invoke-Runtime.ps1", *self.arguments(), "-Mode", "workflow")
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_missing_workflow_wrapper_is_rejected_with_failure_receipt(self):
        (self.module / "workflow.py").unlink()
        result = self.execute("Invoke-Runtime.ps1", *self.arguments(), "-Mode", "workflow")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list(self.logs.glob("*.failure.json"))), 1)

    def test_install_rejects_stale_workflow_sha_before_scheduler_access(self):
        receipt = self.acceptance()
        receipt["workflow_sha256"] = "0" * 64
        self.reject_acceptance(receipt, "workflow acceptance SHA")

    def test_install_rejects_incomplete_code_manifest_before_scheduler_access(self):
        receipt = self.acceptance()
        receipt["code_manifest"].pop("runtime.py")
        self.reject_acceptance(receipt, "code manifest has missing or extra files")

    def test_install_rejects_changed_dependency_sha_before_scheduler_access(self):
        receipt = self.acceptance()
        receipt["code_manifest"]["windows/Common.ps1"] = "0" * 64
        self.reject_acceptance(receipt, "code manifest SHA does not match")


if __name__ == "__main__":
    unittest.main()
