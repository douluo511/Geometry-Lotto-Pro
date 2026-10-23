"""Adversarial synthetic-only tests for read-only prospective study aggregation."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.harness_v46 import core, prospective_cycle as cycle
from research.harness_v46.tests.test_core import fixture


class ProspectiveStudyTests(unittest.TestCase):
    def setUp(self):
        self.before = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}

    def _freeze_and_score(self, path, issue):
        snaps = {g: {**s, "target_issue": str(issue)} for g, s in self.snaps.items()}
        record = cycle.forecast_on_demand(snaps, path, now=self.before)
        results = {
            game: {
                "lottery": game, "issue": str(issue),
                "front": list(snaps[game]["draws"][-2]["front"]),
                "back": list(snaps[game]["draws"][-2]["back"]),
            }
            for game in ("SSQ", "DLT")
        }
        return cycle.evaluate_after_draw(path, record["run_id"], results)

    def test_two_distinct_frozen_draws_are_replayed_with_coverage_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "shadow.sqlite3"
            one = self._freeze_and_score(db, "29999")
            two = self._freeze_and_score(db, "30000")
            before_sha = hashlib.sha256(db.read_bytes()).hexdigest()
            report = cycle.summarize_prospective_receipts(db, [two, one])
            self.assertEqual(report, cycle.summarize_prospective_receipts(db, [one, two]))
            self.assertEqual(report["draws_by_game"], {"SSQ": 2, "DLT": 2})
            self.assertEqual(report["forecast_outcome_integrity"], "REPLAYED_FROZEN_LEDGER")
            self.assertEqual(report["coverage"], "CALLER_SUBMITTED_RECEIPTS_ONLY")
            self.assertFalse(report["official_results_authenticated"])
            self.assertEqual(report["decision"], "NO_EDGE")
            self.assertEqual(report["formal_A"], 0)
            self.assertEqual(len(report["statistical_analysis"]["results"]), 12)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before_sha)

    def test_modified_score_with_rehashed_outer_receipt_still_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "shadow.sqlite3"
            good = self._freeze_and_score(db, "29999")
            tampered = json.loads(json.dumps(good))
            cell = tampered["games"]["SSQ"]["scores"]["hot60"]
            cell["D2"] = 1 - cell["D2"]
            tampered["score_receipt_sha256"] = core.digest({
                key: value for key, value in tampered.items()
                if key != "score_receipt_sha256"
            })
            with self.assertRaisesRegex(core.GateError, "SCORE_RECEIPT_REPLAY_MISMATCH"):
                cycle.summarize_prospective_receipts(db, [tampered])

    def test_changed_outcome_with_valid_self_hash_does_not_replay(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "shadow.sqlite3"
            good = self._freeze_and_score(db, "29999")
            fake = json.loads(json.dumps(good))
            # Force a genuine D2 change rather than relying on a coincidental
            # arbitrary ball swap that could leave every model score unchanged.
            front = fake["scoring_inputs"]["result_bundle"]["DLT"]["front"]
            picks = cycle.frozen_forecast_report(db, good["run_id"])["games"]["DLT"]["models"][0]["primary_d2"]
            if set(picks).issubset(front):
                candidate = [v for v in range(1, 36) if v != picks[0]][:5]
            else:
                candidate = list(picks) + [v for v in range(1, 36) if v not in picks][:3]
            fake["scoring_inputs"]["result_bundle"]["DLT"]["front"] = sorted(candidate)
            fake["scoring_inputs"]["result_bundle_sha256"] = core.digest(
                fake["scoring_inputs"]["result_bundle"]
            )
            fake["score_receipt_sha256"] = core.digest({
                k: v for k, v in fake.items() if k != "score_receipt_sha256"
            })
            with self.assertRaisesRegex(core.GateError, "SCORE_RECEIPT_REPLAY_MISMATCH"):
                cycle.summarize_prospective_receipts(db, [fake])

    def test_duplicate_and_incomplete_receipts_are_denied(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "shadow.sqlite3"
            one = self._freeze_and_score(db, "29999")
            with self.assertRaisesRegex(core.GateError, "DUPLICATE_STUDY_RUN"):
                cycle.summarize_prospective_receipts(db, [one, one])
            with self.assertRaisesRegex(core.GateError, "EMPTY_STUDY_RECEIPTS"):
                cycle.summarize_prospective_receipts(db, [])
            partial = json.loads(json.dumps(one))
            del partial["games"]["DLT"]
            with self.assertRaises(core.GateError):
                cycle.summarize_prospective_receipts(db, [partial])

    def test_unverified_research_evidence_can_never_claim_edge(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "shadow.sqlite3"
            one = self._freeze_and_score(db, "29999")
            study = cycle.summarize_prospective_receipts(db, [one])
            self.assertEqual(study["statistical_analysis"]["decision"], "NO_EDGE")
            self.assertFalse(study["preregistration_verified"])
            self.assertFalse(study["official_results_authenticated"])
            self.assertEqual(study["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
