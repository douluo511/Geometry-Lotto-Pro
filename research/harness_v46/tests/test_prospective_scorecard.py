"""Synthetic-only tests for the prospective user feedback bridge."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from research.harness_v46 import convergence as cv, core, prospective_scorecard as feedback
from research.harness_v46.tests.test_core import fixture


class ProspectiveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "shadow.sqlite"
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}
        manifest = cv.manifest(self.snaps)
        self.run_id = manifest["run_id"]
        conn = sqlite3.connect(self.db)
        try:
            core.init_ledger(conn)
            cv.init_workflow(conn)
            with conn:
                cv.register_manifest(conn, manifest)
                for game, snap in self.snaps.items():
                    core.register_snapshot(conn, self.run_id, snap)
                    for model in core.MODELS:
                        core.freeze_shadow(
                            conn, self.run_id, snap, core.forecast(snap, model),
                            "2026-10-21T00:00:00+00:00",
                        )
        finally:
            conn.close()

    def outcome(self, game="SSQ"):
        # Pure invented outcome; intentionally NOT a real or verified draw.
        example = core.forecast(self.snaps[game], "hot60")["ticket"]
        return {
            "lottery": game, "issue": "29999",
            "front": example["front"], "back": example["back"],
            "drawn_at": "2026-10-23T21:05:00+08:00",
        }

    def test_replay_is_repeatable_readonly_and_never_formal(self):
        before = self.db.read_bytes()
        a = feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome())
        b = feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome())
        self.assertEqual(a, b)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(a["models"]["hot60"]["D2"], 1)
        self.assertEqual(a["models"]["hot60"]["primary_d2"],
                         a["models"]["hot60"]["d1_to_d5"][:2])
        self.assertEqual(len(a["models"]), 6)
        self.assertEqual(a["formal_A"], 0)
        self.assertEqual(a["decision"], "NO_EDGE")
        self.assertEqual(a["outcome_authenticity"], "CALLER_UNVERIFIED")
        self.assertEqual(a["predraw_external_seal"], "NOT_VERIFIED")

    def test_wrong_target_and_time_before_draw_refuse(self):
        wrong = self.outcome()
        wrong["issue"] = "30000"
        with self.assertRaisesRegex(core.GateError, "OUTCOME_TARGET_ISSUE_MISMATCH"):
            feedback.replay_shadow_feedback(self.db, self.run_id, wrong)
        early = self.outcome()
        early["drawn_at"] = "2026-10-23T18:00:00+08:00"
        with self.assertRaisesRegex(core.GateError, "OUTCOME_CLAIMED_BEFORE_TARGET_DRAW"):
            feedback.replay_shadow_feedback(self.db, self.run_id, early)
        with self.assertRaisesRegex(core.GateError, "STRICT_UNVERIFIED_OUTCOME_SCHEMA"):
            feedback.replay_shadow_feedback(self.db, self.run_id,
                                             {**self.outcome(), "verified": True})

    def test_injected_late_freeze_refuses_even_with_valid_predictions(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER prevent_prediction_update")
            conn.execute(
                "UPDATE predictions SET frozen_at='2026-10-24T00:00:00+08:00' "
                "WHERE run_id=? AND lottery='SSQ' AND model='hot60'",
                (self.run_id,),
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaisesRegex(core.GateError, "FREEZE_OUTSIDE_LOCKED_PREDRAW_WINDOW"):
            feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome())

    def test_cumulative_two_lotteries_with_fixed_random_null_and_no_edge(self):
        a = feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome("SSQ"))
        b = feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome("DLT"))
        summary = feedback.summarize_shadow_feedback([a, b])
        self.assertEqual(summary["unique_lottery_issue_count"], 2)
        self.assertEqual(summary["games"]["SSQ"]["hot60"]["draws"], 1)
        self.assertEqual(summary["games"]["DLT"]["hot60"]["d2_hits"], 1)
        self.assertEqual(summary["formal_A"], 0)
        self.assertEqual(summary["decision"], "NO_EDGE")
        self.assertFalse(summary["preregistration_verified"])

    def test_duplicate_or_tampered_scorecard_blocks(self):
        card = feedback.replay_shadow_feedback(self.db, self.run_id, self.outcome())
        with self.assertRaisesRegex(core.GateError, "DUPLICATE_TARGET_IN_FEEDBACK"):
            feedback.summarize_shadow_feedback([card, card])
        forged = deepcopy(card)
        forged["models"]["hot60"]["D2"] = 0
        with self.assertRaisesRegex(core.GateError, "SHADOW_FEEDBACK_RECEIPT_CHANGED"):
            feedback.summarize_shadow_feedback([forged])
        promoted = deepcopy(card)
        promoted["formal_A"] = 1
        promoted["receipt_sha256"] = core.digest({
            k: v for k, v in promoted.items() if k != "receipt_sha256"
        })
        with self.assertRaisesRegex(core.GateError, "UNVERIFIED_SCORECARD_CANNOT_PROMOTE_AUTHORITY"):
            feedback.summarize_shadow_feedback([promoted])

    def test_missing_source_ledger_and_unregistered_run_block(self):
        with self.assertRaisesRegex(core.GateError, "V47_REGISTERED_RUN_REQUIRED"):
            feedback.replay_shadow_feedback(self.db, "OLD-RUN", self.outcome())
        with self.assertRaisesRegex(core.GateError, "SHADOW_LEDGER_NOT_FOUND"):
            feedback.replay_shadow_feedback(
                Path(self.tmp.name) / "absent.sqlite", self.run_id, self.outcome()
            )


if __name__ == "__main__":
    unittest.main()
