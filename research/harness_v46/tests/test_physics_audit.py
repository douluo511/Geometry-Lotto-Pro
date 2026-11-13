"""Adversarial synthetic tests for a non-predictive V4.7 maths/physics sidecar.

No live lottery data, changed formal selectors, or physics forecast claims.
"""
from __future__ import annotations

from fractions import Fraction
import math
import random
import unittest
from datetime import datetime, timedelta, timezone

from research.harness_v46 import core
from research.harness_v46.physics_audit import (
    Ball,
    audit_model_contracts,
    collide,
    d2_probability,
    kinetic_energy,
    linear_momentum,
)


def synthetic_snapshot(game: str) -> dict:
    rules = core.RULES[game]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(120):
        rng = random.Random(73000 + i + (0 if game == "SSQ" else 1000))
        when = start + timedelta(days=i)
        rows.append({
            "issue": str(26001 + i),
            "front": sorted(rng.sample(range(1, rules["pool"] + 1), rules["front"])),
            "back": sorted(rng.sample(range(1, rules["back_pool"] + 1), rules["back"])),
            "drawn_at": when.isoformat(),
            "published_at": (when + timedelta(hours=1)).isoformat(),
        })
    return {
        "lottery": game, "draws": rows,
        "as_of": "2026-10-20T00:00:00+00:00",
        "sales_cutoff": "2026-10-23T12:00:00+08:00",
        "target_draw_at": "2026-10-23T21:00:00+08:00",
        "target_issue": "29999",
        "provenance": {"status": "SYNTHETIC_FIXTURE_NOT_OFFICIAL"},
    }


class MathsAndPhysicsAuditTests(unittest.TestCase):
    def test_exact_fair_d2_baselines(self):
        self.assertEqual(d2_probability(33, 6), Fraction(15, 528))
        self.assertEqual(d2_probability(35, 5), Fraction(10, 595))
        with self.assertRaises(ValueError):
            d2_probability(3, 4)

    def test_m1m2_m3_contracts_keep_shadow_and_six_original_arms(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = synthetic_snapshot(game)
                report = audit_model_contracts(snapshot)
                self.assertEqual(report["model_ids"], list(core.MODELS))
                self.assertEqual(report["verified_deterministic_models"], len(core.MODELS))
                self.assertEqual(report["fair_d2"], float(d2_probability(
                    core.RULES[game]["pool"], core.RULES[game]["front"])))
                self.assertEqual(report["formal_A"], 0)
                self.assertEqual(report["edge"], "NO_EDGE")
                self.assertFalse(report["physical_forecast_supported"])
                self.assertEqual(report["status"], "SYNTHETIC_SHADOW_AUDIT_ONLY")
                self.assertEqual(snapshot["provenance"]["status"],
                                 "SYNTHETIC_FIXTURE_NOT_OFFICIAL")

    def test_equal_mass_elastic_collision_exchanges_normal_velocities(self):
        a = Ball(1.0, 0.5, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        b = Ball(1.0, 0.5, (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
        before_energy = kinetic_energy(a) + kinetic_energy(b)
        before_momentum = tuple(x + y for x, y in zip(linear_momentum(a), linear_momentum(b)))
        new_a, new_b = collide(a, b, restitution=1.0)
        self.assertEqual(new_a.velocity, (-1.0, 0.0, 0.0))
        self.assertEqual(new_b.velocity, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(before_energy, kinetic_energy(new_a) + kinetic_energy(new_b))
        self.assertEqual(before_momentum,
                         tuple(x + y for x, y in zip(linear_momentum(new_a), linear_momentum(new_b))))

    def test_inelastic_collision_cannot_create_energy(self):
        a = Ball(2.0, 0.5, (0.0, 0.0, 0.0), (2.0, 0.0, 0.0))
        b = Ball(1.0, 0.5, (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
        x, y = collide(a, b, restitution=0.4)
        self.assertLessEqual(kinetic_energy(x) + kinetic_energy(y),
                             kinetic_energy(a) + kinetic_energy(b) + 1e-12)
        for i in range(3):
            self.assertAlmostEqual(linear_momentum(a)[i] + linear_momentum(b)[i],
                                   linear_momentum(x)[i] + linear_momentum(y)[i])

    def test_non_contact_and_separating_balls_unchanged(self):
        a = Ball(1.0, 0.5, (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
        b = Ball(1.0, 0.5, (3.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(collide(a, b), (a, b))
        touching = Ball(1.0, 0.5, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(collide(a, touching), (a, touching))

    def test_unphysical_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            Ball(float("nan"), 1.0, (0, 0, 0), (0, 0, 0))
        with self.assertRaises(ValueError):
            Ball(True, 1.0, (0, 0, 0), (0, 0, 0))
        a = Ball(1.0, 0.5, (0, 0, 0), (1, 0, 0))
        b = Ball(1.0, 0.5, (0, 0, 0), (-1, 0, 0))
        with self.assertRaises(ValueError):
            collide(a, b)
        with self.assertRaises(ValueError):
            collide(a, b, restitution=float("nan"))
        with self.assertRaises(ValueError):
            collide(a, b, restitution=1.1)



class AdversarialMathsAuditTests(unittest.TestCase):
    def test_independent_integer_oracle_catches_forged_pair_scores(self):
        from itertools import combinations
        from unittest.mock import patch

        snapshot = synthetic_snapshot("SSQ")
        good = core.forecast(snapshot, "pairwise_d2")["primary_d2"]
        pairs = list(combinations(range(1, 34), 2))
        malicious = next(pair for pair in pairs if list(pair) != good)
        fake = {pair: float(pair == malicious) for pair in pairs}
        with patch.object(core, "_pair_scores", return_value=fake):
            with self.assertRaisesRegex(ValueError, "PAIRWISE_INDEPENDENT_DISAGREEMENT"):
                audit_model_contracts(snapshot)

    def test_claimed_official_data_not_promoted_by_synthetic_auditor(self):
        snapshot = synthetic_snapshot("DLT")
        snapshot["provenance"]["status"] = "OFFICIAL_VERIFIED"
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_ONLY"):
            audit_model_contracts(snapshot)


if __name__ == "__main__":
    unittest.main()
