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


class ScopeReviewApproval(unittest.TestCase):
    def test_checked_in_scope_review_requires_explicit_full_denominator_approval(self):
        approval = json.loads((ROOT / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        self.assertEqual(
            approval["scope_ids"],
            ["B01", "B02", "B03", "B04", "B05", "B06", "B07"],
        )
        self.assertEqual(
            approval["entry_inventory"],
            ["predict", "update", "repair", "audit"],
        )
        self.assertTrue(approval["original_requirements_preserved"])
        self.assertTrue(approval["no_scope_reduction"])
        self.assertEqual(approval["status"], "APPROVED")
        self.assertEqual(approval["approved_by"], "user")
        self.assertIsInstance(approval["approval_reference"], str)
        self.assertTrue(approval["approval_reference"].strip())
        self.assertIn("2026-10-03", approval["approval_reference"])
        self.assertIn("not a scope ceiling", approval["denominator_rule"])
        self.assertIn("No requirement may be removed", approval["denominator_rule"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "BUSINESS_SCOPE_APPROVAL.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )
            result = gate._business_scope_approval(path)

        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["release_authorized"])
        self.assertEqual(result["scope_ids"], approval["scope_ids"])
        self.assertEqual(result["entry_inventory"], approval["entry_inventory"])
        self.assertEqual(
            result["approval_reference"],
            approval["approval_reference"],
        )

    def test_absent_approval_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = gate._business_scope_approval(Path(tmp))
            self.assertEqual(result["status"], "PENDING")
            self.assertFalse(result["release_authorized"])

    def test_forged_approved_state_without_user_reference_fails_closed(self):
        forged = {
            "schema": "ssq-business-scope-approval-v1",
            "project": "SSQ",
            "status": "APPROVED",
            "approved_by": None,
            "scope_ids": ["B01", "B02", "B03", "B04", "B05", "B06", "B07"],
            "entry_inventory": ["predict", "update", "repair", "audit"],
            "approval_reference": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "BUSINESS_SCOPE_APPROVAL.json").write_text(
                json.dumps(forged), encoding="utf-8"
            )
            result = gate._business_scope_approval(path)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["release_authorized"])


if __name__ == "__main__":
    unittest.main()
