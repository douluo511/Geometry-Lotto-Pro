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
    def test_checked_in_proposal_does_not_invent_user_approval(self):
        proposal = json.loads((ROOT / "BUSINESS_SCOPE_APPROVAL.json").read_text(encoding="utf-8"))
        self.assertEqual(proposal["status"], "PENDING")
        self.assertIsNone(proposal["approved_by"])
        self.assertIsNone(proposal["approval_reference"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "BUSINESS_SCOPE_APPROVAL.json").write_text(json.dumps(proposal))
            result = gate._business_scope_approval(path)
            self.assertEqual(result["status"], "PENDING")
            self.assertFalse(result["release_authorized"])

    def test_absent_approval_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = gate._business_scope_approval(Path(tmp))
            self.assertEqual(result["status"], "PENDING")
            self.assertFalse(result["release_authorized"])


if __name__ == "__main__":
    unittest.main()

