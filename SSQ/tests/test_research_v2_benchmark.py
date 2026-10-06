from __future__ import annotations

import random
import unittest
from datetime import date, timedelta

from glp.domain import Draw
from tools.research_v2_benchmark import exact_red_hit_null, run_shadow_benchmark


def synthetic_draws(count: int = 180) -> list[Draw]:
    start = date(2020, 1, 1)
    draws: list[Draw] = []
    for i in range(count):
        rng = random.Random(700000 + i)
        draw = Draw(
            issue=f"2020{i + 1:03d}",
            draw_date=(start + timedelta(days=i)).isoformat(),
            front=tuple(sorted(rng.sample(range(1, 34), 6))),
            back=(rng.randint(1, 16),),
        )
        draw.validate()
        draws.append(draw)
    return draws


class ResearchV2BenchmarkTests(unittest.TestCase):
    def test_exact_six_red_null_is_normalized_and_has_correct_mean(self) -> None:
        null = exact_red_hit_null()
        self.assertAlmostEqual(sum(null.values()), 1.0, places=14)
        mean = sum(k * p for k, p in null.items())
        self.assertAlmostEqual(mean, 36 / 33, places=14)

    def test_small_sample_executes_but_cannot_claim_protocol_complete(self) -> None:
        report = run_shadow_benchmark(
            synthetic_draws(),
            max_evals=50,
            confirmation_n=20,
            refit_interval=25,
            train_points=40,
            rounds=99,
        )
        self.assertEqual(report["software_status"], "FAIL")
        self.assertFalse(report["promotion_eligible"])
        self.assertEqual(report["rho_recommendation"], 0.0)
        self.assertEqual(report["walk_forward"]["total_oos_n"], 50)
        self.assertEqual(report["walk_forward"]["confirmation_oos_n"], 20)
        self.assertEqual(
            sum(report["development"]["distribution"]["two_dan"]["observed_counts"].values()),
            30,
        )

    def test_no_edge_result_never_authorizes_nonzero_rho(self) -> None:
        report = run_shadow_benchmark(
            synthetic_draws(),
            max_evals=45,
            confirmation_n=15,
            refit_interval=30,
            train_points=30,
            rounds=49,
        )
        self.assertEqual(report["rho_recommendation"], 0.0)
        self.assertFalse(report["promotion_eligible"])
        self.assertIn("prospective immutable pre-draw replay n<120", report["promotion_blockers"])


if __name__ == "__main__":
    unittest.main()
