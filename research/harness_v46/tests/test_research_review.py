"""Independent synthetic audit tests. NEVER accepts fake official evidence."""
from __future__ import annotations

from copy import deepcopy
import unittest

from research.harness_v46.research_stack import run_synthetic_stack
from research.harness_v46.research_review import review_synthetic_stack


class ResearchReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_synthetic_stack(seed=8, trials=500, steps=3)

    def test_m1_m2_m3_fusion_physics_calibration_must_be_checked(self):
        review = review_synthetic_stack(self.report)
        self.assertEqual(review["status"], "SYNTHETIC_CONTRACT_PASS_NOT_REAL_CALIBRATION")
        self.assertEqual(review["m1_exact_fair_d2"], "PASS")
        self.assertEqual(review["m2_independent_falsification"], "PASS")
        self.assertEqual(review["m3_null_arithmetic"], "PASS_DIAGNOSTIC_ONLY")
        self.assertEqual(review["unregistered_fusion"], "AUDITED_SHADOW_ONLY")
        self.assertEqual(review["physical_predictor_status"], "DISABLED_UNCALIBRATED")
        self.assertEqual(review["official_prospective_calibration"], "BLOCKED_NO_AUTHENTICATED_FUTURE")
        self.assertEqual(review["formal_A"], 0)
        self.assertEqual(review["edge"], "NO_EDGE")
        for game in ("SSQ", "DLT"):
            row = review["by_game"][game]
            self.assertEqual(row["synthetic_comparison"]["periods"], 2)
            self.assertEqual(row["synthetic_comparison"]["family_eligible_for_inference"], False)
            self.assertGreaterEqual(row["experimental_d2_ci95"][0], 0)
            self.assertLessEqual(row["experimental_d2_ci95"][1], 1)
            self.assertGreaterEqual(row["random_null_d2_ci95"][0], 0)
            self.assertLessEqual(row["random_null_d2_ci95"][1], 1)

    def test_never_accept_forged_provenance(self):
        r = deepcopy(self.report)
        r["official_source_authenticated"] = True
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)

    def test_no_physics_promoted_as_forecast(self):
        r = deepcopy(self.report)
        r["physics"]["physical_forecast_supported"] = True
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)
        r = deepcopy(self.report)
        r["games"]["DLT"]["research_fusion"]["physical_signal_weight"] = 0.01
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)

    def test_original_six_and_null_not_replaced(self):
        r = deepcopy(self.report)
        r["games"]["SSQ"]["m1_math"]["model_ids"].remove("random_null")
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)
        r = deepcopy(self.report)
        r["games"]["SSQ"]["walk_forward"]["experimental_frozen"] = 0
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)

    def test_m3_fake_null_rate_and_d2_bits_cannot_pass(self):
        r = deepcopy(self.report)
        r["games"]["DLT"]["m3_probability"]["fair_rate"] = 0.85
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)
        r = deepcopy(self.report)
        r["games"]["SSQ"]["walk_forward"]["walk_forward"][0]["experimental"]["score"]["D2"] = 3
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)

    def test_wrong_frozen_results_and_outcome_identity_block(self):
        r = deepcopy(self.report)
        r["games"]["DLT"]["walk_forward"]["walk_forward"][0]["experimental"]["frozen_sha256"] = "0"
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)
        r = deepcopy(self.report)
        r["games"]["DLT"]["walk_forward"]["walk_forward"][0]["models"]["random_null"]["synthetic_outcome_front"] = [3] * 5
        with self.assertRaises(ValueError):
            review_synthetic_stack(r)


if __name__ == "__main__":
    unittest.main()
