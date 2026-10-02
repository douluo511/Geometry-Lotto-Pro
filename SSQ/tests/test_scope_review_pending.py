import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("ssq_scope_review", ROOT / "tools" / "derive_gate_status.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ScopeReviewPending(unittest.TestCase):
    def test_checked_in_explicit_user_approval_is_machine_validated(self):
        approval = json.loads((ROOT / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["status"], "APPROVED")
        self.assertEqual(approval["approved_by"], "user")
        self.assertTrue(str(approval["approval_reference"]).strip())
        self.assertTrue(approval["original_requirements_preserved"])
        self.assertTrue(approval["no_scope_reduction"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "BUSINESS_SCOPE_APPROVAL.json").write_text(json.dumps(approval), encoding="utf-8")
            result = gate._business_scope_approval(path)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["release_authorized"])

    def test_proposal_without_explicit_user_approval_cannot_promote(self):
        approval = json.loads((ROOT / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        approval["status"] = "PENDING"
        approval["approved_by"] = None
        approval["approval_reference"] = None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "BUSINESS_SCOPE_APPROVAL.json").write_text(json.dumps(approval), encoding="utf-8")
            result = gate._business_scope_approval(path)
            self.assertNotEqual(result["status"], "PASS")
            self.assertFalse(result["release_authorized"])

    def test_absent_approval_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = gate._business_scope_approval(Path(tmp))
            self.assertEqual(result["status"], "PENDING")
            self.assertFalse(result["release_authorized"])


if __name__ == "__main__":
    unittest.main()
