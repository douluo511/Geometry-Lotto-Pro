from __future__ import annotations

import random
import unittest

from glp.domain import Draw
from glp.research_v2_audit import ALLOWED_DECISIONS, audit_feature_utility


class ResearchV2FeatureAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(20261006)
        draws = []
        for index in range(150):
            front = tuple(sorted(rng.sample(range(1, 36), 5)))
            back = tuple(sorted(rng.sample(range(1, 13), 2)))
            draws.append(
                Draw(
                    issue=f"{70001 + index:05d}",
                    draw_date=f"{2020 + index // 140:04d}-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}",
                    front=front,
                    back=back,
                )
            )
        cls.draws = sorted(draws, key=lambda d: (d.draw_date, d.issue))

    def test_random_world_does_not_authorize_promotion(self):
        result = audit_feature_utility(
            self.draws,
            eval_points=12,
            bootstrap_rounds=80,
            permutation_rounds=120,
        )
        self.assertEqual(result["predictive_edge_claim"], "NOT_VERIFIED")
        self.assertEqual(result["production_rho"], 0.0)
        self.assertFalse(result["promotion_authorized"])
        self.assertNotIn("gap", result["feature_names"])
        self.assertIn("gap", result["forbidden_default_features"])
        for row in result["combined"].values():
            self.assertIn(row["overall"], ALLOWED_DECISIONS)


if __name__ == "__main__":
    unittest.main()
