from __future__ import annotations

import random
import unittest
from datetime import date, timedelta

from glp.domain import Draw
from glp.research_v2_model_audit import audit_joint_ridge


class JointRidgeShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(991177)
        start = date(2024, 1, 1)
        draws = []
        for i in range(140):
            day = start + timedelta(days=i)
            draws.append(
                Draw(
                    issue=f"2024{i+1:03d}",
                    draw_date=day.isoformat(),
                    front=tuple(sorted(rng.sample(range(1, 34), 6))),
                    back=(rng.randrange(1, 17),),
                )
            )
        cls.draws = draws

    def test_random_world_never_authorizes_production(self):
        x = audit_joint_ridge(self.draws, eval_points=4, train_points=8)
        self.assertEqual(x["predictive_edge_claim"], "NOT_VERIFIED")
        self.assertEqual(x["production_rho"], 0.0)
        self.assertFalse(x["promotion_authorized"])
        self.assertIn(x["shadow_decision"], {"NO_EDGE", "SHADOW_EDGE_CANDIDATE"})
        self.assertIn("two_dan_hits", x["exact_null"])
        self.assertAlmostEqual(x["exact_null"]["blue_hit_rate"], 1.0 / 16.0)

    def test_null_distributions_are_normalized(self):
        x = audit_joint_ridge(self.draws, eval_points=4, train_points=8)
        self.assertAlmostEqual(sum(x["exact_null"]["two_dan_hits"][str(k)] for k in range(3)), 1.0)
        self.assertAlmostEqual(sum(x["exact_null"]["red_ticket_hits"].values()), 1.0)


if __name__ == "__main__":
    unittest.main()
