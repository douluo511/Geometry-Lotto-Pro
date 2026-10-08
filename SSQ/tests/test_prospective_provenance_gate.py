"""Fail-first SSQ scientific provenance tests: never count local replay as prospective."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))

from glp.evidence import _prospective_provenance_gate
from glp.engine import model_identity
from glp.service import LottoService
from glp.util import sha256_json


class FakeResult:
    def __init__(self, count: int):
        self.count = count

    def fetchone(self):
        return (self.count,)


class FakeDB:
    def __init__(self, total=30, selector_matched=30):
        self.total = total
        self.selector_matched = selector_matched
        self.closed = False
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))
        return FakeResult(self.selector_matched if "JOIN freezes" in query else self.total)

    def close(self):
        self.closed = True


class SSQProspectiveIntegrityTests(unittest.TestCase):
    def test_thirty_rehashed_local_replays_cannot_self_certify(self):
        selector = model_identity()["selector_hash"]
        candidate = {
            "selector_hash": selector,
            "target_issue": "2026999",
            "freeze_hash": "f" * 64,
            "replayed_at": "2026-10-07T00:00:00Z",
            "actual_issue": "2026999",
            "provenance_verified": True,  # forged flag must never authorize
        }
        records = [dict(candidate) for _ in range(30)]
        gate = _prospective_provenance_gate(records, selector)
        self.assertEqual(gate["unverified_count"], 30)
        self.assertEqual(gate["qualified_count"], 0)
        self.assertTrue(gate["selector_consistent"])
        self.assertFalse(gate["promotion_authorized"])
        self.assertEqual(gate["authority"], "EXTERNAL_PREDRAW_GIT_LEDGER_NOT_VERIFIED")

    def test_selector_missing_wrong_type_or_non_dict_is_rejected(self):
        selector = model_identity()["selector_hash"]
        cases = [
            {"target_issue": "2026999"},
            {"selector_hash": ""},
            {"selector_hash": None},
            {"selector_hash": "other"},
            {"selector_hash": selector.upper()},
            None,
            "faked",
        ]
        for forged in cases:
            with self.subTest(forged=forged):
                gate = _prospective_provenance_gate([forged], selector)
                self.assertEqual(gate["qualified_count"], 0)
                self.assertFalse(gate["selector_consistent"])

    def test_service_legacy_replay_rows_audited_but_not_promoted(self):
        selector = model_identity()["selector_hash"]
        db = FakeDB(total=30, selector_matched=29)
        service = LottoService.__new__(LottoService)
        service._db = lambda: db

        qualified = service._prospective_replays(selector)
        self.assertEqual(qualified, [])
        self.assertTrue(db.closed)
        self.assertEqual(service._prospective_audit["local_replay_rows"], 30)
        self.assertEqual(service._prospective_audit["selector_matched_local_rows"], 29)
        self.assertEqual(service._prospective_audit["qualified_replays"], 0)
        self.assertFalse(service._prospective_audit["promotion_authorized"])

    def test_scientific_policy_fingerprint_changes_after_verifier_code_change(self):
        """A formerly PASS court becomes stale when the verification policy changes."""
        old = LottoService._scientific_policy_hash()
        self.assertEqual(len(old), 64)
        original = __import__("glp.evidence", fromlist=["run_evidence_court"]).run_evidence_court

        def altered_policy(*args, **kwargs):
            return {"software_verdict": "FAIL"}

        from glp import evidence as evidence_module
        with patch.object(evidence_module, "run_evidence_court", altered_policy):
            changed = LottoService._scientific_policy_hash()
        self.assertNotEqual(old, changed)
        self.assertEqual(original, evidence_module.run_evidence_court)

    def test_cached_zero_qualified_court_requires_matching_exact_policy(self):
        identity = model_identity()
        old = {
            "schema": "evidence-court-v8",
            "canonical_hash": "test-canonical",
            "model_hash": identity["model_hash"],
            "selector_hash": identity["selector_hash"],
            "scientific_policy_hash": "0" * 64,
            "software_verdict": "PASS",
            "final_validation": {"status": "PASS"},
            "prospective_authority": {
                "authority": "EXTERNAL_PREDRAW_GIT_LEDGER_NOT_VERIFIED"
            },
            "prospective_n": 0,
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
        }
        old["court_hash"] = sha256_json(old)
        service = LottoService.__new__(LottoService)
        service.latest_court = lambda: old
        service._prospective_replays = lambda _: []
        service._prospective_audit = {
            "authority": "EXTERNAL_PREDRAW_GIT_LEDGER_NOT_VERIFIED",
            "qualified_replays": 0,
        }
        service._append_experiment = lambda *_: None
        fresh = {
            "software_verdict": "PASS",
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
            "prospective_n": 0,
        }
        with patch("glp.service.run_evidence_court", return_value=fresh) as gate:
            court = service._court([], "test-canonical")
        gate.assert_called_once()
        self.assertEqual(court["scientific_policy_hash"], LottoService._scientific_policy_hash())
        self.assertNotEqual(court["scientific_policy_hash"], "0" * 64)

    def test_old_historically_passed_court_is_not_reused(self):
        selector_identity = model_identity()
        old = {
            "schema": "evidence-court-v8",
            "canonical_hash": "test-canonical",
            "model_hash": selector_identity["model_hash"],
            "selector_hash": selector_identity["selector_hash"],
            "software_verdict": "PASS",
            "final_validation": {"status": "PASS"},
            "edge_state": "EDGE_PROVEN",
            "dan_state": "CERTIFIED_DAN",
        }
        old["court_hash"] = sha256_json(old)
        service = LottoService.__new__(LottoService)
        service.latest_court = lambda: old
        service._prospective_replays = lambda _selector: []
        service._prospective_audit = {
            "authority": "EXTERNAL_PREDRAW_GIT_LEDGER_NOT_VERIFIED",
            "qualified_replays": 0,
        }
        saved = []
        service._append_experiment = lambda *args: saved.append(args)

        fresh = {
            "schema": "evidence-court-v8",
            "software_verdict": "PASS",
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
            "prospective_n": 0,
            "final_validation": {"status": "PASS"},
        }
        with patch("glp.service.run_evidence_court", return_value=fresh) as gate:
            result = service._court([], "test-canonical")
        gate.assert_called_once()
        self.assertEqual(result["edge_state"], "NO_EDGE")
        self.assertEqual(result["dan_state"], "NULL_DAN")
        self.assertEqual(result["prospective_authority"]["qualified_replays"], 0)
        self.assertEqual(len(saved), 1)
        self.assertEqual(result["court_hash"], sha256_json({k: v for k, v in result.items() if k != "court_hash"}))


if __name__ == "__main__":
    unittest.main()
