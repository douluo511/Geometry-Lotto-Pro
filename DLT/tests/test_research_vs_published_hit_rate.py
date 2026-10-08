from __future__ import annotations

import unittest

from glp.evidence import prospective_hit_rates


def replay_row(front_hits: int, back_hits: int, *, research_front: list[int] | None = None,
               research_back: list[int] | None = None):
    row = {"front_hit_count": front_hits, "back_hit_count": back_hits}
    if research_front is not None and research_back is not None:
        row["front_winner_ranks"] = {str(6+i): rank for i, rank in enumerate(research_front)}
        row["back_winner_ranks"] = {str(3+i): rank for i, rank in enumerate(research_back)}
    return row


class ResearchVersusPublishedHitRateTests(unittest.TestCase):
    def test_research_hits_separate_from_published_random_fallback(self):
        rows = [
            replay_row(0, 0, research_front=[1,2,3,4,5], research_back=[1,2]),
            replay_row(0, 0, research_front=[6,7,8,9,10], research_back=[3,4]),
        ]
        report = prospective_hit_rates(rows, minimum_replays=30)
        self.assertEqual(report["valid_replays"], 2)
        self.assertEqual(report["front_per_ball_hit_rate"], 0.0)
        self.assertEqual(report["back_per_ball_hit_rate"], 0.0)
        self.assertEqual(report["research_ranked_front_hit_total"], 5)
        self.assertEqual(report["research_ranked_back_hit_total"], 2)
        self.assertAlmostEqual(report["research_ranked_front_per_ball_hit_rate"], .5)
        self.assertAlmostEqual(report["research_ranked_back_per_ball_hit_rate"], .5)
        self.assertAlmostEqual(report["research_ranked_front_gain_vs_published"], .5)
        self.assertAlmostEqual(report["research_ranked_back_gain_vs_published"], .5)
        self.assertEqual(report["research_evidence_state"], "INSUFFICIENT_PROSPECTIVE")
        self.assertFalse(report["edge_certified"])

    def test_missing_research_rankings_are_unknown_not_zero(self):
        result = prospective_hit_rates([replay_row(1, 1)], minimum_replays=30)
        self.assertEqual(result["valid_replays"], 1)
        self.assertIsNone(result["research_ranked_front_per_ball_hit_rate"])
        self.assertIsNone(result["research_ranked_back_per_ball_hit_rate"])
        self.assertEqual(result["research_evidence_state"], "RESEARCH_RANKING_NOT_VERIFIED")
        self.assertEqual(result["front_per_ball_hit_rate"], 1 / 5)

    def test_partial_research_rows_must_not_cherry_pick_winners(self):
        rows = [
            replay_row(0, 0, research_front=[1,2,3,4,5], research_back=[1,2]),
            replay_row(0, 0),
        ]
        result = prospective_hit_rates(rows, minimum_replays=30)
        self.assertIsNone(result["research_ranked_front_per_ball_hit_rate"])
        self.assertIsNone(result["research_ranked_front_gain_vs_published"])
        self.assertEqual(result["research_evidence_state"], "RESEARCH_RANKING_NOT_VERIFIED")

    def test_corrupt_research_winner_positions_fail_closed(self):
        for illegal in ([0,2,3,4,5], [1,1,3,4,5], [1,2,3,4,36]):
            with self.subTest(illegal=illegal):
                with self.assertRaises(ValueError):
                    prospective_hit_rates([
                        replay_row(0,0,research_front=illegal,research_back=[1,2])
                    ])
        with self.assertRaises(ValueError):
            prospective_hit_rates([replay_row(0,0,research_front=[1,2,3,4,5],research_back=[1,13])])

    def test_zero_rows_do_not_invent_success(self):
        result = prospective_hit_rates([], minimum_replays=30)
        self.assertIsNone(result["research_ranked_front_per_ball_hit_rate"])
        self.assertIsNone(result["research_ranked_back_per_ball_hit_rate"])
        self.assertEqual(result["research_evidence_state"], "NO_VALID_PROSPECTIVE")
        self.assertFalse(result["edge_certified"])


if __name__ == "__main__":
    unittest.main()
