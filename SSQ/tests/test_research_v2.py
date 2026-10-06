from __future__ import annotations

import math
import random
import unittest

from glp.domain import Draw
from glp.research_v2 import (
    EXCLUDED_DEFAULT_FEATURES,
    FEATURE_NAMES,
    exact_two_dan_random_baseline,
    feature_map,
    fit_ridge_multiscale,
    research_two_dan_and_ticket,
    uniform_marginal_probability,
)


def synthetic_draws(count: int = 180) -> list[Draw]:
    draws: list[Draw] = []
    for i in range(count):
        rng = random.Random(100000 + i)
        front = tuple(sorted(rng.sample(range(1, 34), 6)))
        back = (rng.randint(1, 16),)
        draw = Draw(
            issue=f"2026{i + 1:03d}",
            draw_date="2026-01-01",
            front=front,
            back=back,
        )
        draw.validate()
        draws.append(draw)
    return draws


class ResearchV2Tests(unittest.TestCase):
    def test_game_baselines(self) -> None:
        self.assertAlmostEqual(uniform_marginal_probability("front"), 6 / 33)
        self.assertAlmostEqual(uniform_marginal_probability("back"), 1 / 16)

    def test_two_dan_exact_null_distribution(self) -> None:
        baseline = exact_two_dan_random_baseline()
        self.assertAlmostEqual(sum(baseline[k] for k in ("zero_hits", "one_hit", "two_hits")), 1.0)
        self.assertAlmostEqual(baseline["at_least_one"], baseline["one_hit"] + baseline["two_hits"])
        self.assertAlmostEqual(baseline["two_hits"], math.comb(31, 4) / math.comb(33, 6))

    def test_gap_and_structural_heuristics_are_not_default_features(self) -> None:
        self.assertNotIn("gap", FEATURE_NAMES)
        self.assertIn("gap", EXCLUDED_DEFAULT_FEATURES)
        self.assertIn("parity", EXCLUDED_DEFAULT_FEATURES)
        self.assertIn("zone_ratio", EXCLUDED_DEFAULT_FEATURES)
        self.assertIn("sum_range", EXCLUDED_DEFAULT_FEATURES)

    def test_feature_map_is_prefix_only_and_deterministic(self) -> None:
        draws = synthetic_draws()
        prefix = draws[:150]
        a = feature_map(prefix, "front")
        b = feature_map(list(prefix), "front")
        self.assertEqual(a, b)
        self.assertEqual(set(a), set(range(1, 34)))
        self.assertTrue(all(len(v) == len(FEATURE_NAMES) for v in a.values()))

    def test_rho_zero_is_exact_uniform_fail_closed_front(self) -> None:
        result = fit_ridge_multiscale(synthetic_draws(), "front", rho=0.0)
        self.assertAlmostEqual(sum(result.research_probabilities.values()), 6.0, places=8)
        self.assertTrue(all(
            abs(p - 6 / 33) < 1e-15
            for p in result.production_probabilities.values()
        ))

    def test_rho_zero_is_exact_uniform_fail_closed_back(self) -> None:
        result = fit_ridge_multiscale(synthetic_draws(), "back", rho=0.0)
        self.assertAlmostEqual(sum(result.research_probabilities.values()), 1.0, places=8)
        self.assertTrue(all(
            abs(p - 1 / 16) < 1e-15
            for p in result.production_probabilities.values()
        ))

    def test_fit_is_deterministic(self) -> None:
        draws = synthetic_draws()
        a = fit_ridge_multiscale(draws, "front", rho=0.0)
        b = fit_ridge_multiscale(draws, "front", rho=0.0)
        self.assertEqual(a.research_ranking, b.research_ranking)
        for n in range(1, 34):
            self.assertAlmostEqual(a.research_probabilities[n], b.research_probabilities[n], places=14)

    def test_research_ticket_is_labeled_not_authorized_at_default_rho(self) -> None:
        ticket = research_two_dan_and_ticket(synthetic_draws())
        self.assertEqual(len(ticket["research_dan_front"]), 2)
        self.assertEqual(len(ticket["research_front"]), 6)
        self.assertEqual(len(ticket["research_back"]), 1)
        self.assertFalse(ticket["production_edge_authorized"])
        self.assertEqual(ticket["rho"], 0.0)


if __name__ == "__main__":
    unittest.main()
