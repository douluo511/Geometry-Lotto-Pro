"""Actual hidden Windows launcher and XML tests using a temporary CLI fixture.

No task is registered. These tests demonstrate local process invocation and
pin checks, never an Agent live model call, boot, elapsed timer or deadline.
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
RESEARCH = MODULE.parent
SCRIPTS = MODULE / "scripts"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
HAS_WINDOWS = os.name == "nt" and POWERSHELL.is_file()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AgentSchedulerSourceTests(unittest.TestCase):
    def test_live_only_schedule_hidden_and_admin_gate_are_explicit(self):
        source = (SCRIPTS / "Install-V45AgentTask.ps1").read_text(encoding="utf-8")
        self.assertIn(" -Mode live'", source)
        self.assertNotIn(" -Mode sdk-fixture", source)
        self.assertNotIn(" -Mode tools-smoke", source)
        self.assertIn("WindowsBuiltInRole]::Administrator", source)
        self.assertIn("if ($Install)", source)
        self.assertIn("[switch]$ExportOnly", source)
        self.assertNotIn(" -Force", source.split("Register-ScheduledTask -TaskPath")[1])
        launcher = (SCRIPTS / "Run-V45Agent.ps1").read_text(encoding="utf-8")
        self.assertIn("-WindowStyle Hidden -Wait -PassThru", launcher)
        self.assertIn("CLI_JST_MON_WED_SAT_DUE_SLOT", launcher)
        self.assertNotIn("Get-ChildItem Env:", source + launcher)
        self.assertNotIn("Send-MailMessage", source + launcher)


@unittest.skipUnless(HAS_WINDOWS, "Actual Windows PowerShell required")
class AgentWindowsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="glp-agent-windows-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.repo = self.directory / "repository & agent"
        self.module = self.repo / "research" / "ssq_dlt_agent_v1"
        self.module.mkdir(parents=True)
        shutil.copytree(SCRIPTS, self.module / "scripts")
        v45 = self.repo / "research" / "ssq_dlt_v45"
        (v45 / "windows").mkdir(parents=True)
        shutil.copy2(RESEARCH / "ssq_dlt_v45" / "windows" / "Common.ps1", v45 / "windows" / "Common.ps1")
        (v45 / "runtime.py").write_text("# Synthetic dependency pin fixture only.\n", encoding="utf-8")
        (self.repo / "research" / "ssq_dlt_d2_v44").mkdir()
        self.entry = self.module / "__main__.py"
        self.entry.write_text(
            "import argparse,json,sys\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser();p.add_argument('--config',required=True);"
            "p.add_argument('--mode',required=True);p.add_argument('--run-key');a=p.parse_args()\n"
            "c=json.loads(Path(a.config).read_text());"
            "print(json.dumps({'fixture':'temporary_cli_only','mode':a.mode,'run_key':a.run_key}))\n"
            "print('temporary CLI fixture stderr',file=sys.stderr);sys.exit(c.get('exit_code',0))\n",
            encoding="utf-8")
        self.config = self.directory / "agent & config.json"
        self.config.write_text("{}", encoding="utf-8")
        self.logs = self.directory / "hidden launcher logs"
        self.xml = self.directory / "reviewed task.xml"
        self.manifest = self.directory / "reviewed deployment.json"

    def execute(self, script, *arguments):
        return subprocess.run([
            str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(self.module / "scripts" / script), *map(str, arguments)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)

    def common_arguments(self):
        return ["-PythonPath", sys.executable, "-RepositoryPath", self.repo, "-ConfigPath", self.config,
                "-LauncherLogDirectory", self.logs, "-DeploymentManifestPath", self.manifest]

    def export(self):
        result = self.execute("Install-V45AgentTask.ps1", *self.common_arguments(), "-ExportXmlPath", self.xml, "-ExportOnly")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_export_only_has_exact_schedule_no_execution_and_immutable_outputs(self):
        receipt = self.export()
        self.assertFalse(receipt["installed"])
        self.assertEqual(receipt["status"], "EXPORTED_ONLY")
        self.assertEqual(receipt["scheduled_mode"], "live")
        self.assertEqual(receipt["deadline_enforcement"], "NOT_PROVEN")
        self.assertEqual(receipt["daily_schedule_execution"], "NOT_RUN")
        self.assertFalse(self.logs.exists())
        task = ET.parse(self.xml).getroot()
        self.assertEqual(task.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=NS), "2020-01-06T07:00:00Z")
        days = task.find("t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek", NS)
        self.assertEqual([day.tag.rsplit("}", 1)[1] for day in days], ["Monday", "Wednesday", "Saturday"])
        self.assertEqual(task.findtext("t:Triggers/t:BootTrigger/t:Delay", namespaces=NS), "PT30S")
        self.assertEqual(task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS), "PT30M")
        self.assertEqual(task.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS), "IgnoreNew")
        self.assertEqual(task.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS), "true")
        self.assertEqual(task.findtext("t:Settings/t:Hidden", namespaces=NS), "true")
        arguments = task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
        self.assertIn("-WindowStyle Hidden", arguments)
        self.assertIn("-Mode live", arguments)
        self.assertNotIn("sdk-fixture", arguments)
        self.assertNotIn("tools-smoke", arguments)
        self.assertNotIn("-RunKey", arguments)
        self.assertIn(f'"{self.config.resolve()}"', arguments)
        before = (self.xml.read_bytes(), self.manifest.read_bytes())
        again = self.execute("Install-V45AgentTask.ps1", *self.common_arguments(), "-ExportXmlPath", self.xml, "-ExportOnly")
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual((self.xml.read_bytes(), self.manifest.read_bytes()), before)

    def test_hidden_launcher_passes_mode_optional_key_and_logs_hash_receipt(self):
        self.export()
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments(), "-Mode", "sdk-fixture", "-RunKey", "explicit-test-key")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["validation_scope"], "HIDDEN_LAUNCHER_PROCESS_ONLY")
        self.assertEqual(receipt["mode"], "sdk-fixture")
        self.assertEqual(receipt["run_key_policy"], "EXPLICIT_OPERATOR_KEY")
        self.assertEqual(receipt["deployment_manifest_sha256"], sha(self.manifest))
        self.assertFalse(receipt["fallback_used"])
        stdout = next(self.logs.glob("*.stdout.log"))
        self.assertEqual(json.loads(stdout.read_text(encoding="utf-8-sig"))["run_key"], "explicit-test-key")
        self.assertEqual(receipt["stdout_sha256"], sha(stdout))

    def test_default_live_failure_propagates_without_fixture_fallback(self):
        self.config.write_text('{"exit_code":19}', encoding="utf-8")
        self.export()
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments())
        self.assertEqual(result.returncode, 19, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["mode"], receipt["status"]), ("live", "FAIL"))
        self.assertFalse(receipt["fallback_used"])
        self.assertEqual(receipt["run_key_policy"], "CLI_JST_MON_WED_SAT_DUE_SLOT")
        self.assertEqual(len(list(self.logs.glob("*.stdout.log"))), 1)
        payload = json.loads(next(self.logs.glob("*.stdout.log")).read_text(encoding="utf-8-sig"))
        self.assertEqual(payload["mode"], "live")
        self.assertIsNone(payload["run_key"])

    def test_live_blocked_exit_is_preserved_without_claiming_model_success(self):
        self.config.write_text('{"exit_code":2}', encoding="utf-8")
        self.export()
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments())
        self.assertEqual(result.returncode, 2, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["mode"], receipt["status"]), ("live", "BLOCKED"))
        self.assertEqual(receipt["validation_scope"], "HIDDEN_LAUNCHER_PROCESS_ONLY")
        self.assertFalse(receipt["fallback_used"])

    def test_opt_in_install_without_acceptance_keeps_reviewed_exports_and_cannot_register(self):
        self.export()
        before = (self.xml.read_bytes(), self.manifest.read_bytes())
        # No receipt is provided: both administrator and non-administrator
        # paths reject before importing Scheduler or registering any task.
        result = self.execute("Install-V45AgentTask.ps1", *self.common_arguments(), "-ExportXmlPath", self.xml, "-Install")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.xml.read_bytes(), self.manifest.read_bytes()), before)
        self.assertFalse(self.logs.exists())

    def test_changed_config_new_code_v45_dependency_and_python_hash_block_execution(self):
        self.export()
        original_manifest = self.manifest.read_text(encoding="utf-8")
        cases = [self.config, self.entry, self.repo / "research/ssq_dlt_v45/runtime.py"]
        for target in cases:
            original = target.read_bytes()
            target.write_bytes(original + b"\n# changed\n")
            result = self.execute("Run-V45Agent.ps1", *self.common_arguments(), "-Mode", "tools-smoke")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(list(self.logs.glob("*.stdout.log")))
            target.write_bytes(original)
        changed = json.loads(original_manifest)
        changed["python_sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(changed), encoding="utf-8")
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(self.logs.glob("*.stdout.log")))

    def test_added_production_code_blocks_and_failure_does_not_echo_secret_config(self):
        self.export()
        extra = self.module / "unreviewed.py"
        extra.write_text("raise SystemExit(99)\n", encoding="utf-8")
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(self.logs.glob("*.stdout.log")))
        extra.unlink()
        secret = "synthetic-secret-marker-do-not-log"
        self.config.write_text('{"secret":"' + secret, encoding="utf-8")
        result = self.execute("Run-V45Agent.ps1", *self.common_arguments())
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr + "".join(path.read_text(encoding="utf-8-sig") for path in self.logs.glob("*.json"))
        self.assertNotIn(secret, output)

    def test_manifest_pins_new_and_transitive_v45_code_runtime_and_config(self):
        self.export()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["python_sha256"], sha(Path(sys.executable)))
        self.assertEqual(manifest["base_python_sha256"], sha(Path(sys._base_executable)))
        self.assertEqual(manifest["config_sha256"], sha(self.config))
        self.assertEqual(manifest["code_manifest"]["ssq_dlt_agent_v1/__main__.py"], sha(self.entry))
        self.assertIn("ssq_dlt_v45/windows/Common.ps1", manifest["code_manifest"])
        self.assertIn("ssq_dlt_agent_v1/scripts/Run-V45Agent.ps1", manifest["code_manifest"])


if __name__ == "__main__":
    unittest.main()
