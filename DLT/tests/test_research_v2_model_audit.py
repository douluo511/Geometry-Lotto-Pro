from __future__ import annotations

import random
import unittest

from glp.domain import Draw
from glp.research_v2_model_audit import audit_joint_ridge


class JointRidgeShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(887766)
        draws = []
        for i in range(140):
            draws.append(
                Draw(
                    issue=f"{80001+i:05d}",
                    draw_date=f"{2024 + i // 336:04d}-{(i % 12)+1:02d}-{(i % 28)+1:02d}",
                    front=tuple(sorted(rng.sample(range(1,36),5))),
                    back=tuple(sorted(rng.sample(range(1,13),2))),
                )
            )
        cls.draws = sorted(draws, key=lambda d:(d.draw_date,d.issue))

    def test_random_world_never_authorizes_production(self):
        x = audit_joint_ridge(self.draws, eval_points=4, train_points=8)
        self.assertEqual(x["predictive_edge_claim"], "NOT_VERIFIED")
        self.assertEqual(x["production_rho"], 0.0)
        self.assertFalse(x["promotion_authorized"])
        self.assertIn(x["shadow_decision"], {"NO_EDGE","SHADOW_EDGE_CANDIDATE"})


if __name__ == "__main__":
    unittest.main()
