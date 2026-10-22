"""Synthetic arithmetic tests only; they never assert official evidence or predictive edge."""
import unittest

from research.harness_v46.core import MODELS
from research.harness_v46.statistics import (
    EvaluationBlocked, FAIR_D2, clopper_pearson, exact_binomial_upper_tail,
    evaluate_shadow_d2, holm_adjust,
)


def family():
    return [
        {"hypothesis_id": f"registered-slot-{game}-{model}",
         "lottery": game, "model": model}
        for game in ("SSQ", "DLT") for model in MODELS
    ]


def row(game, issue, overrides=None):
    scores = {model: 0 for model in MODELS}
    scores.update(overrides or {})
    return {"lottery": game, "issue": str(issue), "scores": scores}


class StatisticsTests(unittest.TestCase):
    def test_exact_binomial_tail_small_counts(self):
        self.assertEqual(exact_binomial_upper_tail(4, 4, 0.5), 1 / 16)
        self.assertEqual(exact_binomial_upper_tail(0, 4, 0.5), 1.0)
        self.assertEqual(exact_binomial_upper_tail(1, 4, 0.0), 0.0)
        self.assertEqual(exact_binomial_upper_tail(1, 4, 1.0), 1.0)
        self.assertAlmostEqual(exact_binomial_upper_tail(2, 4, 0.5), 11 / 16)

    def test_exact_ci_boundaries(self):
        low, high = clopper_pearson(0, 10, 0.95)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.0)
        low, high = clopper_pearson(10, 10, 0.95)
        self.assertLess(low, 1.0)
        self.assertEqual(high, 1.0)
        low, high = clopper_pearson(4, 10, 0.95)
        self.assertLessEqual(low, 0.4)
        self.assertGreaterEqual(high, 0.4)

    def test_holm_requires_exact_named_family(self):
        ids = [f"h{i}" for i in range(12)]
        adjusted = holm_adjust({"h0": 0.01, **{f"h{i}": 1.0 for i in range(1, 12)}}, ids)
        self.assertGreaterEqual(adjusted["h0"], 0.01)
        with self.assertRaisesRegex(EvaluationBlocked, "COMPLETE_HOLM_FAMILY"):
            holm_adjust({"h0": 0.01}, ids)

    def test_no_hits_no_edge_and_fixed_baseline(self):
        report = evaluate_shadow_d2([row("SSQ", i) for i in range(1, 6)], family())
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")
        self.assertFalse(report["preregistration_verified"])
        hot = next(x for x in report["results"] if x["lottery"] == "SSQ" and x["model"] == "hot60")
        self.assertEqual(hot["hits"], 0)
        self.assertEqual(hot["fair_baseline"], FAIR_D2["SSQ"])
        self.assertEqual(hot["p_exact_vs_fair"], 1.0)
        self.assertEqual(hot["p_exact_paired_vs_null"], 1.0)

    def test_joint_test_requires_both_baseline_and_null(self):
        rows = [row("SSQ", i, {"hot60": 1}) for i in range(1, 9)]
        report = evaluate_shadow_d2(rows, family())
        hot = next(x for x in report["results"] if x["lottery"] == "SSQ" and x["model"] == "hot60")
        self.assertAlmostEqual(hot["p_exact_paired_vs_null"], 1 / 256)
        self.assertAlmostEqual(hot["p_joint_intersection_union"],
                               max(hot["p_exact_vs_fair"], hot["p_exact_paired_vs_null"]))
        self.assertAlmostEqual(hot["holm_adjusted_p_unverified_family"], 12 / 256)
        estimate = (hot["paired_wins_vs_null"] - hot["paired_losses_vs_null"]) / hot["draws"]
        lo, hi = hot["paired_rate_difference_ci95_conservative"]
        self.assertLessEqual(lo, estimate)
        self.assertGreaterEqual(hi, estimate)
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_same_issue_must_be_unique(self):
        with self.assertRaisesRegex(EvaluationBlocked, "DUPLICATE_DRAW"):
            evaluate_shadow_d2([row("DLT", "26121"), row("DLT", "26121")], family())

    def test_boolean_is_not_a_d2_bit(self):
        with self.assertRaisesRegex(EvaluationBlocked, "INVALID_D2_BIT"):
            evaluate_shadow_d2([row("SSQ", "2026121", {"hot60": True})], family())

    def test_family_mapping_must_not_duplicate_a_model_game(self):
        bad = family()
        bad[-1] = dict(bad[0], hypothesis_id="different-name")
        with self.assertRaisesRegex(EvaluationBlocked, "DUPLICATE_HYPOTHESIS"):
            evaluate_shadow_d2([row("SSQ", 1)], bad)

    def test_missing_game_data_keeps_family_slot_at_p_one(self):
        report = evaluate_shadow_d2([row("SSQ", 1)], family())
        dlt = next(x for x in report["results"] if x["lottery"] == "DLT")
        self.assertEqual(dlt["status"], "NO_DATA")
        self.assertEqual(dlt["p_joint_intersection_union"], 1.0)
        self.assertEqual(dlt["holm_adjusted_p_unverified_family"], 1.0)

    def test_empty_study_blocked(self):
        with self.assertRaisesRegex(EvaluationBlocked, "EMPTY_STUDY"):
            evaluate_shadow_d2([], family())


if __name__ == "__main__":
    unittest.main()
