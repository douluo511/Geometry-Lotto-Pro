import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from release_gate import HARD_GATES, evaluate


class ReleaseGateTests(unittest.TestCase):
    def test_all_pass_is_pass(self):
        r = evaluate({"gates": {k: "PASS" for k in HARD_GATES}})
        self.assertEqual(r["final_gate"], "PASS")

    def test_warning_is_fail(self):
        gates = {k: "PASS" for k in HARD_GATES}
        gates["gui_smoke"] = "WARNING"
        self.assertEqual(evaluate({"gates": gates})["final_gate"], "FAIL")

    def test_missing_is_fail(self):
        self.assertEqual(evaluate({"gates": {}})["final_gate"], "FAIL")


if __name__ == "__main__":
    unittest.main()
