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

    def test_checked_in_scope_review_stays_pending_without_specific_user_approval(self):
        approval = json.loads((SCRIPTS.parent / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["status"], "PENDING")
        self.assertIsNone(approval["approved_by"])
        self.assertIsNone(approval["approval_reference"])

    def test_negative_gui_failure_binds_exact_updater_process(self):
        source = (SCRIPTS / "physical_gui_failure_smoke.ps1").read_text(encoding="utf-8")
        for literal in ("updater_exe_sha256", "parent_pid_match", "updater_failure_exact_hash", "updater_failure_parent_bound"):
            self.assertIn(literal, source)
        final_source = (SCRIPTS / "final_gate.py").read_text(encoding="utf-8")
        runtime_source = (SCRIPTS / "business_runtime_gate.py").read_text(encoding="utf-8")
        for literal in ("physical_hit_test_verified", "updater_failure_exact_hash", "updater_failure_parent_bound"):
            self.assertIn(literal, final_source)
            self.assertIn(literal, runtime_source)

    def test_missing_negative_gui_evidence_is_a_hard_final_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            exe.write_bytes(b"TEST_ONLY_NOT_A_PRODUCTION_EXE")
            result = gate.derive(root, exe)
            self.assertEqual(result["gates"]["physical_gui_failure"], "FAIL")
            self.assertEqual(result["gates"]["physical_gui_repair_failure"], "FAIL")

    def test_negative_gui_final_gate_requires_physical_hit_and_updater_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            updater = root / "Geometry_Lotto_Pro_DLT_Updater.exe"
            exe.write_bytes(b"TEST_ONLY_MAIN")
            updater.write_bytes(b"TEST_ONLY_UPDATER")
            base = {
                "schema": "dlt-physical-gui-failure-v1",
                "status": "PASS",
                "operation": "update",
                "exe_sha256": gate._sha256(exe),
                "updater_sha256": gate._sha256(updater),
                "github_sha": os.environ.get("GITHUB_SHA"),
                "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                "backend_status": "FAIL",
                "ui_fail_closed": True,
                "physical_hit_test_verified": True,
                "updater_failure_exact_hash": True,
                "updater_failure_parent_bound": True,
                "canonical_unchanged": True,
                "evidence_unchanged": True,
                "updater_failure_count": 1,
                "official_update_pass_increment": 0,
                "official_update_fail_increment": 1,
            }
            path = root / "physical_gui_failure.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_failure"], "PASS")

            missing_hit = dict(base)
            missing_hit.pop("physical_hit_test_verified")
            path.write_text(json.dumps(missing_hit), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_failure"], "FAIL")

            no_updater_failure = dict(base)
            no_updater_failure["updater_failure_count"] = 0
            path.write_text(json.dumps(no_updater_failure), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_failure"], "FAIL")

    def test_negative_repair_final_gate_requires_physical_hit_and_updater_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "fixture.exe"
            updater = root / "Geometry_Lotto_Pro_DLT_Updater.exe"
            exe.write_bytes(b"TEST_ONLY_MAIN")
            updater.write_bytes(b"TEST_ONLY_UPDATER")
            base = {
                "schema": "dlt-physical-gui-failure-v1",
                "status": "PASS",
                "operation": "repair",
                "exe_sha256": gate._sha256(exe),
                "updater_sha256": gate._sha256(updater),
                "github_sha": os.environ.get("GITHUB_SHA"),
                "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                "backend_status": "FAIL",
                "ui_fail_closed": True,
                "physical_hit_test_verified": True,
                "updater_failure_exact_hash": True,
                "updater_failure_parent_bound": True,
                "corruption_injected": True,
                "canonical_unchanged": True,
                "evidence_unchanged": True,
                "updater_failure_count": 1,
                "official_update_pass_increment": 0,
                "repair_pass_increment": 0,
                "repair_fail_increment": 1,
            }
            path = root / "physical_gui_repair_failure.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_repair_failure"], "PASS")

            base["physical_hit_test_verified"] = False
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_repair_failure"], "FAIL")

            base["physical_hit_test_verified"] = True
            base["updater_failure_count"] = 0
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(gate.derive(root, exe)["gates"]["physical_gui_repair_failure"], "FAIL")

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
