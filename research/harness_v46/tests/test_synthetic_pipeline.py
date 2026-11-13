"""Synthetic-only end-to-end tests: ranked forecast -> local freeze -> future score.

Nothing is an authenticated official draw, a trusted predraw seal, or a
real prospective performance statistic. Tests do not touch owner host files.
"""
from __future__ import annotations

from copy import deepcopy
from math import comb
import sqlite3
import unittest

from research.harness_v46 import core
from research.harness_v46.research_stack import synthetic_fixture, run_synthetic_stack
from research.harness_v46.synthetic_pipeline import (
    run_synthetic_walk_forward,
    score_frozen_synthetic,
)


class SyntheticPipelineTests(unittest.TestCase):
    def test_both_games_all_six_models_are_locally_frozen_and_scored(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                report = run_synthetic_walk_forward(game, seed=42, periods=2)
                self.assertEqual(report["game"], game)
                self.assertEqual(report["status"], "SYNTHETIC_LOCAL_ONLY")
                self.assertEqual(report["periods"], 2)
                self.assertEqual(report["frozen_predictions"], 12)
                self.assertEqual(report["scores_computed"], 12)
                self.assertEqual(report["formal_A"], 0)
                self.assertEqual(report["edge"], "NO_EDGE")
                self.assertFalse(report["trusted_predraw_seal"])
                self.assertFalse(report["official_draws_admitted"])
                self.assertEqual(set(report["models"]), set(core.MODELS))
                self.assertEqual(report["random_null_model"], "random_null")
                self.assertEqual(len(report["walk_forward"]), 2)
                for period in report["walk_forward"]:
                    self.assertEqual(set(period["models"]), set(core.MODELS))
                    self.assertEqual(period["frozen_count"], 6)
                    self.assertEqual(period["score_count"], 6)
                    for model in core.MODELS:
                        item = period["models"][model]
                        self.assertEqual(len(item["frozen_sha256"]), 64)
                        self.assertEqual(item["D2"], int(item["D1"] == 1 and len(item["ranking_first_two"]) == 2
                                                           and item["ranking_first_two"][1] in item["synthetic_outcome_front"]))
                        self.assertIn("ticket_front_hits", item)
                        self.assertIn("ticket_back_hits", item)

    def test_replay_reproducible_and_do_not_modify_real_record(self):
        a = run_synthetic_walk_forward("DLT", seed=91, periods=2)
        b = run_synthetic_walk_forward("DLT", seed=91, periods=2)
        self.assertEqual(a, b)
        self.assertEqual(a["source"], "INVENTED_DRAW_HISTORY")
        self.assertEqual(a["db_location"], "MEMORY_ONLY")

    def test_wrong_target_or_mutated_prediction_is_refused(self):
        snapshot = synthetic_fixture("SSQ", seed=31)
        forecast = core.forecast(snapshot, "random_null")
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        with db:
            core.freeze_shadow(db, "SYNTHETIC-TEST", snapshot, forecast,
                               "2026-10-21T00:00:00+00:00")
        outcome = {
            "lottery": "SSQ", "issue": snapshot["target_issue"],
            "front": [1, 2, 3, 4, 5, 6], "back": [1],
        }
        scores = score_frozen_synthetic(db, "SYNTHETIC-TEST", snapshot, outcome)
        self.assertEqual(list(scores), ["random_null"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 1)
        bad = dict(outcome, issue="2026998")
        with self.assertRaises(core.GateError):
            score_frozen_synthetic(db, "SYNTHETIC-TEST", snapshot, bad)
        altered = deepcopy(forecast)
        altered["primary_d2"] = altered["primary_d2"][::-1]
        with self.assertRaises(core.GateError):
            with db:
                core.freeze_shadow(db, "SYNTHETIC-TEST", snapshot, altered,
                                   "2026-10-21T00:00:00+00:00")

    def test_untrusted_official_provenance_is_never_admitted(self):
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_ONLY"):
            run_synthetic_walk_forward("SSQ", seed=7, periods=1,
                                       allow_real_outcomes=True)
        with self.assertRaises(ValueError):
            run_synthetic_walk_forward("SSQ", seed=7, periods=0)

    def test_main_stack_exposes_synthetic_replay_not_prediction_advantage(self):
        report = run_synthetic_stack(seed=12, trials=200, steps=3)
        for game in ("SSQ", "DLT"):
            self.assertEqual(report["games"][game]["walk_forward"]["status"],
                             "SYNTHETIC_LOCAL_ONLY")
            self.assertEqual(report["games"][game]["walk_forward"]["frozen_predictions"], 12)
            self.assertNotIn("prospective_edge", report["games"][game])
        self.assertFalse(report["prospective_calibration_valid"])
        self.assertEqual(report["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
