import json
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from release_gate import HARD_GATES, evaluate

MARKERS=[
    "source_self_test.pass","unit_tests.pass","contract_tests.pass","integration_tests.pass",
    "fault_injection.pass","real_network.pass","business_validation.pass",
    "counterexample_validation.pass","reversal_validation.pass","windows_build.pass",
    "exact_exe_self_test.pass","exact_exe_network.pass","gui_smoke.pass",
    "physical_gui_click.pass","same_hash.pass",
]


class ReleaseGateTests(unittest.TestCase):
    def fixture(self,tmp):
        ed=tmp/"evidence"; ed.mkdir()
        for name in MARKERS:
            (ed/name).write_text("PASS",encoding="utf-8")
        tested=tmp/"tested.exe"; final=tmp/"final.exe"
        tested.write_bytes(b"same"); final.write_bytes(b"same")
        payload={"status":"PASS","gates":{k:"PASS" for k in HARD_GATES}}
        return ed,tested,final,payload

    def test_all_current_run_evidence_passes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ed,tested,final,payload=self.fixture(pathlib.Path(td))
            result=evaluate(payload,ed,tested,final)
            self.assertEqual(result["final_gate"],"PASS")
            self.assertEqual(result["hard_fail_count"],0)

    def test_warning_or_missing_marker_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ed,tested,final,payload=self.fixture(pathlib.Path(td))
            payload["gates"]["oos_validation"]="WARNING"
            (ed/"physical_gui_click.pass").unlink()
            result=evaluate(payload,ed,tested,final)
            self.assertEqual(result["final_gate"],"FAIL")
            self.assertEqual(result["failures"]["oos_validation"],"WARNING")
            self.assertEqual(result["failures"]["physical_gui_click"],"FAIL")


if __name__=="__main__":
    unittest.main()
