from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main as app_main


class ReleaseGateAuthorityTests(unittest.TestCase):
    def test_exact_exe_cannot_self_certify_final_release(self):
        source = inspect.getsource(app_main.run_acceptance)
        self.assertIn('report["exact_acceptance_gate"] = "PASS"', source)
        self.assertIn('report["final_release_gate"] = "PENDING"', source)
        self.assertNotIn('report["final_release_gate"] = "PASS"', source)

    def test_acceptance_exit_code_is_bound_to_exact_acceptance_not_final_gate(self):
        source = inspect.getsource(app_main.run_acceptance)
        self.assertIn('report["exact_acceptance_gate"] == "PASS"', source)


if __name__ == "__main__":
    unittest.main()
