import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from completion_boundary import completion_states, static_report

spec = importlib.util.spec_from_file_location("dlt_final_boundary", SCRIPTS / "final_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class BusinessReleaseBoundaries(unittest.TestCase):
    def test_chinese_contract_literals_survive_publication(self):
        source = (SCRIPTS / "business_no_shell_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("\ufffd", source)
        for literal in ("\u9884\u6d4b\u4e0b\u4e00\u671f", "\u4e0d\u4ee3\u8868\u66f4\u9ad8\u4e2d\u5956\u6982\u7387"):
            self.assertIn(literal, source)

    def test_static_pass_never_means_business_pass(self):
        report = static_report([{"name": "interface", "status": "PASS"}], "test")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(completion_states(report), {"business_content": "PENDING", "no_shell": "PENDING"})
        self.assertIsNone(report["overall_completion"])
        self.assertFalse(report["release_authorized"])

    def test_old_static_pass_is_rejected(self):
        legacy = {"schema": "dlt-business-no-shell-gate-v1", "status": "PASS", "business_content": "PASS", "no_shell": "PASS"}
        self.assertEqual(set(completion_states(legacy).values()), {"FAIL"})

    def test_incomplete_static_checks_fail_closed(self):
        for checks in ([], None, [None], [{"status": "PASS"}], [{"name": "a", "status": "SKIPPED"}], [{"name": "a", "status": "PASS"}] * 2):
            with self.subTest(checks=checks):
                self.assertEqual(static_report(checks, "test")["status"], "FAIL")

    def test_top_level_forged_completion_cannot_promote(self):
        report = static_report([{"name": "a", "status": "PASS"}], "test")
        report.update(business_content="PASS", no_shell="PASS")
        self.assertEqual(set(completion_states(report).values()), {"PENDING"})

    def test_real_final_consumer_blocks_static_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            exe.write_bytes(b"TEST_ONLY_NOT_A_PRODUCTION_EXE")
            report = static_report([{"name": "a", "status": "PASS"}], "test")
            (root / "business_no_shell_gate.json").write_text(json.dumps(report))
            result = gate.derive(root, exe)
            self.assertEqual(result["final_gate"], "FAIL")
            self.assertEqual(result["gates"]["business_content"], "FAIL")
            self.assertEqual(result["gates"]["no_shell"], "FAIL")

    def test_checked_in_scope_review_requires_valid_explicit_state(self):
        approval = json.loads((SCRIPTS.parent / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["scope_ids"], ["B01", "B02", "B03", "B04", "B05", "B06", "B07"])
        self.assertEqual(approval["entry_inventory"], ["predict", "update", "repair", "audit"])
        self.assertTrue(approval["original_requirements_preserved"])
        self.assertTrue(approval["no_scope_reduction"])
        self.assertIn(approval["status"], {"PENDING", "APPROVED"})
        if approval["status"] == "PENDING":
            self.assertIsNone(approval["approved_by"])
            self.assertIsNone(approval["approval_reference"])
        else:
            self.assertEqual(approval["approved_by"], "user")
            self.assertIsInstance(approval["approval_reference"], str)
            self.assertTrue(approval["approval_reference"].strip())

    def test_approved_scope_without_user_reference_is_rejected_by_runtime_gate_contract(self):
        source = (SCRIPTS / "business_runtime_gate.py").read_text(encoding="utf-8")
        self.assertIn('approval.get("approved_by") == "user"', source)
        self.assertIn('bool(str(approval.get("approval_reference", "")).strip())', source)

    def test_negative_gui_failure_binds_exact_updater_process(self):
        source = (SCRIPTS / "physical_gui_failure_smoke.ps1").read_text(encoding="utf-8")
        for literal in ("updater_exe_sha256", "parent_pid_match", "updater_failure_exact_hash", "updater_failure_parent_bound"):
            self.assertIn(literal, source)
        final_source = (SCRIPTS / "final_gate.py").read_text(encoding="utf-8")
        runtime_source = (SCRIPTS / "business_runtime_gate.py").read_text(encoding="utf-8")
        self.assertIn("updater_failure_exact_hash", final_source)
        self.assertIn("updater_failure_parent_bound", final_source)
        self.assertIn("updater_failure_exact_hash", runtime_source)
        self.assertIn("updater_failure_parent_bound", runtime_source)

    def test_missing_negative_gui_evidence_is_a_hard_final_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            exe.write_bytes(b"TEST_ONLY_NOT_A_PRODUCTION_EXE")
            result = gate.derive(root, exe)
            self.assertEqual(result["gates"]["physical_gui_failure"], "FAIL")
            self.assertEqual(result["gates"]["physical_gui_repair_failure"], "FAIL")

    def test_runtime_four_entry_evidence_closes_no_shell_not_business(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            exe.write_bytes(b"TEST_ONLY_NOT_A_PRODUCTION_EXE")
            exe_hash = gate._sha256(exe)
            static = static_report([{"name": "interface", "status": "PASS"}], "test")
            static["github_sha"] = os.environ.get("GITHUB_SHA")
            static["github_run_id"] = os.environ.get("GITHUB_RUN_ID")
            (root / "business_no_shell_gate.json").write_text(json.dumps(static), encoding="utf-8")
            (root / "business_runtime_gate.json").write_text(json.dumps({
                "schema": "dlt-business-runtime-gate-v1",
                "status": "PASS",
                "business_content": "PENDING",
                "no_shell": "PASS",
                "approval_status": "PENDING",
                "original_requirements_preserved": True,
                "exe_sha256": exe_hash,
                "updater_sha256": "",
                "github_sha": os.environ.get("GITHUB_SHA"),
                "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                "tasks": {"B05": {"status": "PENDING"}},
            }), encoding="utf-8")
            result = gate.derive(root, exe)
            self.assertEqual(result["gates"]["no_shell"], "PASS")
            self.assertEqual(result["gates"]["business_content"], "PENDING")
            self.assertEqual(result["final_gate"], "FAIL")


if __name__ == "__main__":
    unittest.main()
