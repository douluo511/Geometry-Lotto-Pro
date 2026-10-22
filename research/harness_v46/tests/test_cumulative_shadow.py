"""Fail-first synthetic counterexamples for cumulative SHADOW D2 reporting."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.harness_v46 import core, prospective_cycle as cycle
from research.harness_v46 import cumulative_shadow as cohort
from research.harness_v46.tests.test_core import fixture


class CumulativeShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "ledger.sqlite")
        self.clock = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}

    def add_run(self, index=0, *, database=None):
        db = self.db if database is None else database
        snaps = deepcopy(self.snaps)
        for game in snaps:
            snaps[game]["target_issue"] = str(29999 + index)
            if index:
                snaps[game]["sales_cutoff"] = "2026-10-24T12:00:00+08:00"
                snaps[game]["target_draw_at"] = "2026-10-24T21:00:00+08:00"
        frozen = cycle.forecast_on_demand(snaps, db, now=self.clock)
        outcome = {
            game: {
                "lottery": game,
                "issue": str(29999 + index),
                "front": core.forecast(snaps[game], "hot60")["ticket"]["front"],
                "back": core.forecast(snaps[game], "hot60")["ticket"]["back"],
                "drawn_at": ("2026-10-23T21:30:00+08:00" if not index
                             else "2026-10-24T21:30:00+08:00"),
            }
            for game in ("SSQ", "DLT")
        }
        return {"database": db, "run_id": frozen["run_id"], "results": outcome}

    def test_two_issues_real_frozen_rows_cumulative_and_readonly(self):
        a, b = self.add_run(), self.add_run(1)
        before = Path(self.db).read_bytes()
        review = cohort.cumulative_shadow_review([b, a])
        review_again = cohort.cumulative_shadow_review([a, b])
        self.assertEqual(review, review_again)
        self.assertEqual(Path(self.db).read_bytes(), before)
        self.assertEqual(review["unique_two_game_runs"], 2)
        for game in ("SSQ", "DLT"):
            self.assertEqual(review["games"][game]["draws"], 2)
            self.assertEqual(review["games"][game]["models"]["hot60"]["d2_hits"], 2)
            self.assertEqual(review["games"][game]["models"]["hot60"]["d2_rate"], 1.0)
            self.assertEqual(
                review["games"][game]["models"]["hot60"]["observed_minus_null"],
                (2 - review["games"][game]["models"]["random_null"]["d2_hits"]) / 2)
            self.assertEqual(len(review["games"][game]["observations"]), 2)
        self.assertEqual(review["formal_A"], 0)
        self.assertEqual(review["decision"], "NO_EDGE")
        self.assertFalse(review["preregistration_verified"])

    def test_duplicate_run_and_duplicate_issue_across_different_ledgers_block(self):
        a = self.add_run()
        with self.assertRaisesRegex(core.GateError, "DUPLICATE_RUN"):
            cohort.cumulative_shadow_review([a, a])
        # A distinct manifest can nonetheless use the same issue in a separate ledger.
        second_db = str(Path(self.tmp.name) / "second.sqlite")
        other_snaps = deepcopy(self.snaps)
        other_snaps["SSQ"]["provenance"]["different"] = True
        b_report = cycle.forecast_on_demand(other_snaps, second_db, now=self.clock)
        b = deepcopy(a)
        b["database"], b["run_id"] = second_db, b_report["run_id"]
        with self.assertRaisesRegex(core.GateError, "DUPLICATE_LOTTERY_TARGET"):
            cohort.cumulative_shadow_review([a, b])

    def test_result_before_target_draw_and_wrong_target_refused(self):
        a = self.add_run()
        a["results"]["SSQ"]["drawn_at"] = "2026-10-23T12:00:00+08:00"
        with self.assertRaisesRegex(core.GateError, "CLAIMED_RESULT_BEFORE_TARGET_DRAW"):
            cohort.cumulative_shadow_review([a])
        a = self.add_run()
        a["results"]["DLT"]["issue"] = "30000"
        with self.assertRaisesRegex(core.GateError, "CLAIMED_OUTCOME_TARGET_MISMATCH"):
            cohort.cumulative_shadow_review([a])

    def test_callers_cannot_inject_hit_bits_or_fake_official_verification(self):
        a = self.add_run()
        a["results"]["DLT"]["formal_A"] = 1
        with self.assertRaisesRegex(core.GateError, "STRICT_CLAIMED_OUTCOME_SCHEMA"):
            cohort.cumulative_shadow_review([a])
        a = self.add_run()
        a["results"]["DLT"]["D2"] = 1
        with self.assertRaisesRegex(core.GateError, "STRICT_CLAIMED_OUTCOME_SCHEMA"):
            cohort.cumulative_shadow_review([a])

    def test_missing_or_tampered_batch_blocks(self):
        a = self.add_run()
        db = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM predictions WHERE lottery='SSQ'")
            db.rollback()
            db.execute("DROP TRIGGER prevent_prediction_update")
            db.execute("UPDATE predictions SET prediction_sha256='0' || substr(prediction_sha256,2) "
                       "WHERE lottery='SSQ' AND model='hot60'")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(core.GateError):
            cohort.cumulative_shadow_review([a])

    def test_broken_or_incomplete_cohort_fails_closed(self):
        a = self.add_run()
        a["results"].pop("DLT")
        with self.assertRaisesRegex(core.GateError, "EXACTLY_TWO_UNVERIFIED_OUTCOMES"):
            cohort.cumulative_shadow_review([a])
        with self.assertRaisesRegex(core.GateError, "STRICT_CUMULATIVE_INPUT"):
            cohort.cumulative_shadow_review([{"database": self.db, "run_id": "fake", "results": {}}])
        with self.assertRaisesRegex(core.GateError, "NONEMPTY_PROSPECTIVE_CYCLES"):
            cohort.cumulative_shadow_review([])


if __name__ == "__main__":
    unittest.main()
