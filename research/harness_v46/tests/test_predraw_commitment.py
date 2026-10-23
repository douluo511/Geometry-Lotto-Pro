"""Synthetic adversarial dual-game RFC3161 message-imprint preparation tests.

No test issues or validates a real TSA token or calls official lottery services.
"""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.harness_v46 import core, prospective_cycle as cycle
from research.harness_v46.tests.test_core import fixture


class PredrawCommitmentTests(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}

    def _fresh(self, folder):
        db = Path(folder) / "predraw.sqlite3"
        frozen = cycle.forecast_on_demand(self.snaps, db, now=self.when)
        return db, frozen

    def test_dual_game_commitment_is_deterministic_reproducible_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, forecast = self._fresh(tmp)
            prior = hashlib.sha256(db.read_bytes()).hexdigest()
            a = cycle.build_predraw_commitment(db, forecast["run_id"])
            b = cycle.build_predraw_commitment(db, forecast["run_id"])
            self.assertEqual(a, b)
            self.assertEqual(a["schema"], "V47-DUAL-PREDRAW-COMMITMENT-1")
            self.assertEqual(a["preimage"]["run_id"], forecast["run_id"])
            self.assertEqual(a["message_imprint_sha256"], core.digest(a["preimage"]))
            self.assertEqual(a["message_imprint_hash_algorithm"], "sha256")
            self.assertEqual(set(a["preimage"]["games"]), {"SSQ", "DLT"})
            for game in ("SSQ", "DLT"):
                one = a["preimage"]["games"][game]
                self.assertEqual(one["target_issue"], forecast["games"][game]["target_issue"])
                self.assertEqual(one["prediction_batch_sha256"], forecast["games"][game]["prediction_batch_sha256"])
                self.assertEqual(set(one["prediction_hashes"]), set(core.MODELS))
                self.assertEqual(set(one["local_freeze_times_untrusted"]), set(core.MODELS))
                for model in core.MODELS:
                    expected = next(x["prediction_sha256"] for x in
                                    forecast["games"][game]["models"] if x["model"] == model)
                    self.assertEqual(one["prediction_hashes"][model], expected)
            self.assertEqual(a["external_tsa"], "NOT_REQUESTED")
            self.assertFalse(a["independent_timestamp_verified"])
            self.assertFalse(a["official_source_authenticated"])
            self.assertEqual(a["formal_A"], 0)
            self.assertEqual(a["decision"], "NO_EDGE")
            self.assertTrue(cycle.verify_predraw_commitment(db, a))
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), prior)

    def test_modified_prediction_hash_even_with_rehashed_imprint_fails_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, forecast = self._fresh(tmp)
            committed = cycle.build_predraw_commitment(db, forecast["run_id"])
            modified = json.loads(json.dumps(committed))
            modified["preimage"]["games"]["DLT"]["prediction_hashes"]["hot60"] = "f" * 64
            modified["message_imprint_sha256"] = core.digest(modified["preimage"])
            with self.assertRaisesRegex(core.GateError, "PREDRAW_COMMITMENT_LEDGER_MISMATCH"):
                cycle.verify_predraw_commitment(db, modified)

    def test_forged_external_stamp_authority_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, forecast = self._fresh(tmp)
            committed = cycle.build_predraw_commitment(db, forecast["run_id"])
            forged = json.loads(json.dumps(committed))
            forged["independent_timestamp_verified"] = True
            forged["external_tsa"] = "PASS"
            forged["formal_A"] = 1
            with self.assertRaisesRegex(core.GateError, "PREDRAW_COMMITMENT_LEDGER_MISMATCH"):
                cycle.verify_predraw_commitment(db, forged)

    def test_missing_game_or_false_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, forecast = self._fresh(tmp)
            good = cycle.build_predraw_commitment(db, forecast["run_id"])
            partial = json.loads(json.dumps(good))
            del partial["preimage"]["games"]["SSQ"]
            with self.assertRaises(core.GateError):
                cycle.verify_predraw_commitment(db, partial)
            wrong = json.loads(json.dumps(good))
            wrong["message_imprint_sha256"] = "0" * 64
            with self.assertRaisesRegex(core.GateError, "PREDRAW_COMMITMENT_DIGEST_MISMATCH"):
                cycle.verify_predraw_commitment(db, wrong)

    def test_missing_run_never_creates_a_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "missing.sqlite3"
            with self.assertRaises((core.GateError, OSError, __import__("sqlite3").Error)):
                cycle.build_predraw_commitment(db, "V47-no-such-frozen-run")
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
