from __future__ import annotations

import random
import unittest

from glp.domain import Draw
from glp.research_v2 import FEATURE_NAMES, fit_ridge_multiscale


class RidgeMultiscaleResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(20261006)
        draws = []
        for index in range(180):
            front = tuple(sorted(rng.sample(range(1, 36), 5)))
            back = tuple(sorted(rng.sample(range(1, 13), 2)))
            draws.append(
                Draw(
                    issue=f"{26001 + index:05d}",
                    draw_date=f"2026-01-{(index % 28) + 1:02d}",
                    front=front,
                    back=back,
                )
            )
        cls.draws = draws

    def test_gap_is_not_a_default_feature(self):
        self.assertNotIn("gap", FEATURE_NAMES)
        self.assertNotIn("omission", FEATURE_NAMES)
        self.assertEqual(
            FEATURE_NAMES,
            (
                "frequency_20_z",
                "frequency_60_z",
                "frequency_120_z",
                "ewma_120_z",
                "trend_20_120",
                "trend_20_60",
            ),
        )

    def test_default_rho_zero_falls_back_to_uniform_front_baseline(self):
        result = fit_ridge_multiscale(
            self.draws,
            "front",
            rho=0.0,
            train_points=30,
        )
        baseline = 5.0 / 35.0
        self.assertAlmostEqual(
            sum(result.research_probabilities.values()),
            5.0,
            places=10,
        )
        self.assertAlmostEqual(
            sum(result.production_probabilities.values()),
            5.0,
            places=10,
        )
        for value in result.production_probabilities.values():
            self.assertAlmostEqual(value, baseline, places=12)

    def test_default_rho_zero_falls_back_to_uniform_back_baseline(self):
        result = fit_ridge_multiscale(
            self.draws,
            "back",
            rho=0.0,
            train_points=30,
        )
        baseline = 2.0 / 12.0
        self.assertAlmostEqual(
            sum(result.research_probabilities.values()),
            2.0,
            places=10,
        )
        self.assertAlmostEqual(
            sum(result.production_probabilities.values()),
            2.0,
            places=10,
        )
        for value in result.production_probabilities.values():
            self.assertAlmostEqual(value, baseline, places=12)

    def test_rho_one_exposes_research_probabilities_without_recalibration_drift(self):
        result = fit_ridge_multiscale(
            self.draws,
            "front",
            rho=1.0,
            train_points=30,
        )
        self.assertEqual(
            set(result.research_probabilities),
            set(range(1, 36)),
        )
        for number in range(1, 36):
            self.assertAlmostEqual(
                result.production_probabilities[number],
                result.research_probabilities[number],
                places=12,
            )

    def test_training_is_deterministic_for_identical_history(self):
        first = fit_ridge_multiscale(
            self.draws,
            "front",
            rho=0.0,
            train_points=30,
        )
        second = fit_ridge_multiscale(
            self.draws,
            "front",
            rho=0.0,
            train_points=30,
        )
        self.assertEqual(first.research_ranking, second.research_ranking)
        self.assertEqual(first.coefficients, second.coefficients)
        self.assertEqual(
            first.research_probabilities,
            second.research_probabilities,
        )


if __name__ == "__main__":
    unittest.main()
