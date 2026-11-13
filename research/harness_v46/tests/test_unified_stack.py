"""Integration tests for the existing, SHADOW-only V4.7 research stack.

Run each case on Ubuntu and Windows. Nothing is a physical lottery forecast,
qualified future prediction, or official source admission.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from research.harness_v46 import core
from research.harness_v46.research_stack import (
    synthetic_fixture, run_synthetic_stack, simulate_fair_d2,
)
from research.harness_v46.physics_sim import (
    Chamber, simulate_chamber, step_chamber,
)
from research.harness_v46.physics_audit import Ball


class UnifiedStackTests(unittest.TestCase):
    def test_integrated_two_game_synthetic_run_and_six_original_models(self):
        report = run_synthetic_stack(seed=42, trials=2000, steps=8)
        self.assertEqual(report["status"], "SYNTHETIC_RESEARCH_ONLY")
        self.assertEqual(set(report["games"]), {"SSQ", "DLT"})
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["edge"], "NO_EDGE")
        self.assertFalse(report["official_source_authenticated"])
        self.assertFalse(report["physical_forecast_supported"])
        for game in ("SSQ", "DLT"):
            row = report["games"][game]
            self.assertEqual(row["m1_math"]["model_ids"], list(core.MODELS))
            self.assertEqual(row["m2_adversarial"]["independent_pairwise_check"], "PASS")
            self.assertEqual(row["m2_adversarial"]["null_history_invariance"], "PASS")
            self.assertEqual(row["m3_probability"]["status"], "SYNTHETIC_NULL_CALIBRATION_ONLY")
            self.assertEqual(row["geometry"]["status"], "RESEARCH_FEATURES_NOT_PHYSICS")
            self.assertIn("geometry_state", row["geometry"]["features"]["front"])
            self.assertIn("geometry_transition", row["geometry"]["features"]["back"])
            self.assertEqual(row["geometry"]["source_engine"], game)
        self.assertEqual(report["physics"]["status"], "UNCALIBRATED_TWO_BALL_BOX_DIAGNOSTIC")
        self.assertNotIn("ticket", report)
        self.assertNotIn("recommendation", report)

    def test_exact_replay_across_runs(self):
        self.assertEqual(run_synthetic_stack(seed=13, trials=500, steps=4),
                         run_synthetic_stack(seed=13, trials=500, steps=4))

    def test_monte_carlo_with_replacement_bug_not_allowed(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                r = core.RULES[game]
                report = simulate_fair_d2(pool=r["pool"], picks=r["front"],
                                          trials=16000, seed=77)
                self.assertEqual(report["status"], "SYNTHETIC_NULL_CALIBRATION_ONLY")
                self.assertEqual(report["trials"], 16000)
                self.assertAlmostEqual(report["fair_rate"], r["d2"], places=12)
                self.assertLess(abs(report["observed_rate"] - report["fair_rate"]), 0.013)
                self.assertLessEqual(report["brier_empirical"], 1.0)
                self.assertGreaterEqual(report["brier_empirical"], 0.0)
        with self.assertRaises(ValueError):
            simulate_fair_d2(pool=33, picks=6, trials=0, seed=77)
        with self.assertRaises(ValueError):
            simulate_fair_d2(pool=33, picks=6, trials=100, seed=True)

    def test_synthetic_fixture_cannot_claim_official_authentication(self):
        snap = synthetic_fixture("SSQ", seed=33)
        self.assertEqual(snap["provenance"]["status"], "SYNTHETIC_FIXTURE_NOT_OFFICIAL")
        self.assertEqual(len(snap["draws"]), 120)
        self.assertTrue(core.validate_study_snapshot(snap))
        with self.assertRaises(ValueError):
            synthetic_fixture("UNKNOWN", seed=33)

    def test_cli_is_runnable_and_fails_closed_without_synthetic_opt_in(self):
        args = [sys.executable, "-m", "research.harness_v46.research_stack"]
        blocked = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(blocked.returncode, 0)
        success = subprocess.run(args + ["--synthetic", "--seed", "99",
                                          "--trials", "500", "--steps", "3"],
                                 capture_output=True, text=True, timeout=35)
        self.assertEqual(success.returncode, 0, success.stderr[-1000:])
        output = json.loads(success.stdout)
        self.assertEqual(output["formal_A"], 0)
        self.assertFalse(output["physical_forecast_supported"])

    def test_mechanical_box_air_drag_and_wall_collision(self):
        chamber = Chamber(lengths=(4.0, 4.0, 4.0), gravity=(0.0, 0.0, 0.0),
                          air_velocity=(0.0, 0.0, 0.0), drag_rate=0.2,
                          shake_acceleration=0.0, shake_frequency_hz=1.0,
                          restitution=1.0)
        a = Ball(1.0, .1, (1.0, 1.0, 1.0), (2.0, 0.0, 0.0))
        after = step_chamber(chamber, [a], dt=.05, time=0.0)[0]
        self.assertLess(after.velocity[0], a.velocity[0])
        self.assertGreater(after.position[0], a.position[0])
        edge = Ball(1.0, .1, (3.89, 1.0, 1.0), (3.0, 0.0, 0.0))
        bounced = step_chamber(chamber, [edge], dt=.1, time=0.0)[0]
        self.assertLess(bounced.velocity[0], 0)
        self.assertLessEqual(bounced.position[0], 3.9)

    def test_deterministic_motion_and_collision_have_no_numbers_or_edge(self):
        chamber = Chamber(lengths=(3.0, 3.0, 3.0), gravity=(0.0, 0.0, -9.81),
                          air_velocity=(0.0, 0.0, 0.3), drag_rate=0.15,
                          shake_acceleration=2.0, shake_frequency_hz=2.0,
                          restitution=0.8)
        a = Ball(1.0, .25, (.9, 1.5, 1.5), (.8, 0.0, .0))
        b = Ball(1.0, .25, (1.8, 1.5, 1.5), (-.8, 0.0, .0))
        x = simulate_chamber(chamber, [a, b], steps=10, dt=.025)
        y = simulate_chamber(chamber, [a, b], steps=10, dt=.025)
        self.assertEqual(x, y)
        self.assertEqual(x["status"], "UNCALIBRATED_TWO_BALL_BOX_DIAGNOSTIC")
        self.assertFalse(x["physical_forecast_supported"])
        self.assertEqual(x["formal_A"], 0)
        self.assertEqual(len(x["ball_state"]), 2)
        self.assertNotIn("draw", x)
        self.assertNotIn("predicted_numbers", x)

    def test_invalid_machine_geometry_and_unsupported_number_of_balls(self):
        with self.assertRaises(ValueError):
            Chamber(lengths=(0, 1, 1))
        with self.assertRaises(ValueError):
            Chamber(lengths=(3, 3, 3), drag_rate=-1)
        chamber = Chamber(lengths=(3.0, 3.0, 3.0))
        ball = Ball(1.0, .5, (1, 1, 1), (0, 0, 0))
        with self.assertRaises(ValueError):
            simulate_chamber(chamber, [ball], steps=10, dt=.02)
        with self.assertRaises(ValueError):
            simulate_chamber(chamber, [ball, ball, ball], steps=10, dt=.02)
        with self.assertRaises(ValueError):
            simulate_chamber(chamber, [ball, ball], steps=-1, dt=.02)


if __name__ == "__main__":
    unittest.main()
