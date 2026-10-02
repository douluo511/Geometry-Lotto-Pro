import importlib.util
import json
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
            self.assertEqual(result["gates"]["business_content"], "PENDING")
            self.assertEqual(result["gates"]["no_shell"], "PENDING")


if __name__ == "__main__":
    unittest.main()
