import json
import pathlib
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from release_gate import HARD_GATES, evaluate


class ReleaseGateTests(unittest.TestCase):
    def test_repository_independence_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            evidence=root/"evidence"
            evidence.mkdir()
            for marker in {
                "self_test.pass","unit_tests.pass","contract_tests.pass","integration_tests.pass",
                "fault_injection.pass","real_network.pass","business_validation.pass",
                "counterexample_validation.pass","reversal_validation.pass","windows_build.pass",
                "exact_exe_self_test.pass","gui_smoke.pass","physical_gui_click.pass","same_hash.pass",
            }:
                (evidence/marker).write_text("PASS",encoding="utf-8")
            candidate=root/"candidate.exe"; final=root/"final.exe"
            candidate.write_bytes(b"same-bytes"); final.write_bytes(b"same-bytes")
            gates={name:"PASS" for name in HARD_GATES}
            gates["repository_independence"]="FAIL"
            gate_input=root/"gate.json"
            gate_input.write_text(json.dumps({"status":"FAIL","gates":gates}),encoding="utf-8")
            result=evaluate(evidence,candidate,final,gate_input)
            self.assertEqual(result["final_gate"],"FAIL")
            self.assertEqual(result["failures"]["repository_independence"],"FAIL")

    def test_unknown_or_missing_gate_never_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            evidence=root/"evidence"; evidence.mkdir()
            candidate=root/"candidate.exe"; final=root/"final.exe"
            candidate.write_bytes(b"x"); final.write_bytes(b"x")
            gate_input=root/"gate.json"
            gate_input.write_text(json.dumps({"gates":{}}),encoding="utf-8")
            result=evaluate(evidence,candidate,final,gate_input)
            self.assertEqual(result["final_gate"],"FAIL")
            self.assertGreater(result["hard_fail_count"],0)


if __name__=="__main__":
    unittest.main()
