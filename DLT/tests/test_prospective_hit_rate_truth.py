from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from glp.domain import Draw, Prediction
from glp.engine import replay_prediction
from glp.storage import Store
from glp.evidence import prospective_hit_rates


class ProspectiveHitRateTruthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlt-predraw-hit-rate-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.actual = Draw("26113", "2026-10-07", (6, 7, 8, 9, 10), (3, 4))

    def freeze(self, *, created_at="2026-10-06T01:00:00Z", model_hash="m"*64,
               selector_hash="s"*64, target_date="2026-10-07"):
        return self.store.freeze(Prediction(
            prediction_id="research-prediction-1",
            target_issue=self.actual.issue,
            target_date=target_date,
            created_at=created_at,
            front=[1, 2, 3, 4, 5], back=[1, 2],
            front_ranking=list(range(1, 36)), back_ranking=list(range(1, 13)),
            dan_state="NULL_DAN", edge_state="NO_EDGE",
            research_dan_front=[1, 2], research_dan_back=[1],
            canonical_hash="c"*64, model_hash=model_hash,
            selector_hash=selector_hash, score_hash="x"*64,
        ))

    def valid_rows(self):
        return self.store.prospective_replays(
            "s"*64, model_hash="m"*64, draws=[self.actual],
        )

    def test_valid_frozen_before_draw_counts_actual_zero_hits(self):
        pred = self.freeze()
        self.store.save_replay(pred.prediction_id, self.actual.issue,
                               replay_prediction(pred, self.actual))
        rows = self.valid_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["front_hit_count"], 0)
        self.assertEqual(rows[0]["back_hit_count"], 0)

    def test_post_draw_freeze_cannot_inflate_prospective_hit_rate(self):
        pred = self.freeze(created_at="2026-10-08T00:00:00Z")
        self.store.save_replay(pred.prediction_id, self.actual.issue,
                               replay_prediction(pred, self.actual))
        self.assertEqual(self.valid_rows(), [],
                         "FALSE BUSINESS PASS: post-draw prediction counted as prospective")

    def test_same_day_freeze_is_not_trusted_without_official_draw_timestamp(self):
        pred = self.freeze(created_at="2026-10-07T01:00:00Z")
        self.store.save_replay(pred.prediction_id, self.actual.issue,
                               replay_prediction(pred, self.actual))
        self.assertEqual(self.valid_rows(), [])

    def test_tampered_replay_cannot_report_perfect_hit_rate(self):
        pred = self.freeze()
        wrong = replay_prediction(pred, self.actual)
        wrong["front_hit_count"] = 5
        wrong["back_hit_count"] = 2
        self.store.save_replay(pred.prediction_id, self.actual.issue, wrong)
        with self.assertRaisesRegex(ValueError, "replay|hit|mismatch|tamper"):
            self.valid_rows()

    def test_mismatched_model_identity_is_not_prospective(self):
        pred = self.freeze(model_hash="n"*64)
        self.store.save_replay(pred.prediction_id, self.actual.issue,
                               replay_prediction(pred, self.actual))
        self.assertEqual(self.valid_rows(), [])

    def test_wrong_target_date_cannot_be_prospective(self):
        pred = self.freeze(target_date="2026-10-08")
        self.store.save_replay(pred.prediction_id, self.actual.issue,
                               replay_prediction(pred, self.actual))
        self.assertEqual(self.valid_rows(), [])

    def test_hit_rates_report_measured_denominator_and_uniform_baseline(self):
        rows = [
            {"front_hit_count": 1, "back_hit_count": 0},
            {"front_hit_count": 0, "back_hit_count": 1},
        ]
        report = prospective_hit_rates(rows, minimum_replays=30)
        self.assertEqual(report["valid_replays"], 2)
        self.assertEqual(report["front_hit_total"], 1)
        self.assertEqual(report["back_hit_total"], 1)
        self.assertAlmostEqual(report["front_per_ball_hit_rate"], 0.1)
        self.assertAlmostEqual(report["back_per_ball_hit_rate"], 0.25)
        self.assertAlmostEqual(report["uniform_front_per_ball_baseline"], 5 / 35)
        self.assertAlmostEqual(report["uniform_back_per_ball_baseline"], 2 / 12)
        self.assertEqual(report["evidence_state"], "INSUFFICIENT_PROSPECTIVE")
        self.assertFalse(report["edge_certified"])

    def test_no_valid_replays_is_unknown_not_zero_percent_observed(self):
        report = prospective_hit_rates([], minimum_replays=30)
        self.assertEqual(report["valid_replays"], 0)
        self.assertIsNone(report["front_per_ball_hit_rate"])
        self.assertIsNone(report["back_per_ball_hit_rate"])
        self.assertFalse(report["edge_certified"])


if __name__ == "__main__":
    unittest.main()
