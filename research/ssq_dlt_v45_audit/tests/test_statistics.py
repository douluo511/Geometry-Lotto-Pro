"""Synthetic/exhaustive V4.5 statistical contract tests; no historical data."""
from itertools import combinations, product
from math import comb, log, sqrt
import unittest

from research.ssq_dlt_v45_audit.statistics import (
    StatisticsBlocked, holm, pair_brier, paired_summary, precision_sample_size,
    score_d2, validate_fixed_plan,
)


FAMILY = tuple("RESEARCH_%02d" % i for i in range(12))


class StatisticsTests(unittest.TestCase):
    def test_d2_exhaustive_small_population(self):
        for drawn in combinations(range(1, 7), 3):
            for pair in combinations(range(1, 7), 2):
                self.assertEqual(score_d2(pair, drawn), int(all(x in drawn for x in pair)))

    def test_d2_one_or_zero_ball_is_not_a_hit(self):
        self.assertEqual(score_d2([1, 8], [1, 2, 3, 4, 5, 6]), 0)
        self.assertEqual(score_d2([8, 9], [1, 2, 3, 4, 5, 6]), 0)

    def test_invalid_numbers_fail_closed(self):
        for pair, draw in [([1, 1], [1, 2]), ([True, 2], [1, 2]),
                           ([0, 2], [1, 2]), ([1, 2], [1, 1]),
                           ([1], [1, 2]), ([1, 2], [1])]:
            with self.subTest(pair=pair, draw=draw), self.assertRaises(StatisticsBlocked):
                score_d2(pair, draw)

    def test_brier_perfect_all_pair_vector(self):
        pairs = list(combinations(range(1, 7), 2))
        draw = [1, 3, 5]
        vector = [int(set(pair).issubset(draw)) for pair in pairs]
        self.assertEqual(pair_brier(vector, draw, 6, 3), 0)

    def test_brier_uniform_exact_expected_score(self):
        probability = comb(3, 2) / comb(6, 2)
        self.assertAlmostEqual(pair_brier([probability] * comb(6, 2), [1, 2, 3], 6, 3),
                               probability * (1 - probability))

    def test_brier_uses_lexicographic_not_selected_pair(self):
        vector = [0.5, 0, 0, 0, 0, 0.5]
        self.assertAlmostEqual(pair_brier(vector, [1, 2], 4, 2), 0.5 / 6)
        self.assertAlmostEqual(pair_brier(vector, [1, 3], 4, 2), 1.5 / 6)

    def test_brier_rejects_length_range_nan_and_wrong_normalization(self):
        for vector in [[0.5] * 5, [1 / 6] * 6, [-0.1, 1.1, 0, 0, 0, 0],
                       [float("nan"), 1, 0, 0, 0, 0], [True, 0, 0, 0, 0, 0]]:
            with self.subTest(vector=vector), self.assertRaises(StatisticsBlocked):
                pair_brier(vector, [1, 2, 3], 4, 3)

    def test_brier_degree_bound_and_invalid_draw(self):
        with self.assertRaises(StatisticsBlocked):
            pair_brier([1, 1, 1, 0, 0, 0], [1, 2, 3], 4, 3)
        for draw in [[1, 1, 2], [1, 2, 5], [1, 2]]:
            with self.assertRaises(StatisticsBlocked):
                pair_brier([0.5] * 6, draw, 4, 3)

    def test_exact_conditional_test_exhaustive_signs(self):
        for n in range(1, 8):
            for wins in range(n + 1):
                observations = [(1, 0)] * wins + [(0, 1)] * (n - wins)
                enumerated = sum(sum(bits) >= wins for bits in product((0, 1), repeat=n)) / 2 ** n
                result = paired_summary(observations)
                self.assertEqual(result["p_one_sided"], enumerated)
                self.assertEqual(result["p_exact_denominator_power_two"], n)

    def test_paired_ties_direction_and_interval(self):
        result = paired_summary([(1, 0)] * 10 + [(1, 1), (0, 0)])
        self.assertEqual(result["p_one_sided"], 1 / 1024)
        self.assertEqual(result["ties"], 2)
        self.assertAlmostEqual(result["paired_delta"], 10 / 12)
        radius = sqrt(2 * log(40) / 12)
        self.assertEqual(result["confidence_interval"], [max(-1, 10 / 12 - radius), 1])
        self.assertEqual(result["decision"], "NO_EDGE")
        self.assertEqual(paired_summary([(0, 1)] * 10)["p_one_sided"], 1)

    def test_empty_and_all_tied_pairs(self):
        self.assertIsNone(paired_summary([])["paired_delta"])
        self.assertIsNone(paired_summary([])["confidence_interval"])
        self.assertEqual(paired_summary([(1, 1), (0, 0)])["p_one_sided"], 1)

    def test_paired_invalid_binary_not_silently_coerced(self):
        for pairs in [[(True, 0)], [(2, 0)], [(1,)], [(1.0, 0)], None]:
            with self.assertRaises(StatisticsBlocked):
                paired_summary(pairs)

    def test_holm_known_step_down_and_monotonic_adjustments(self):
        pvalues = dict(zip(FAMILY, [0.001, 0.002, 0.004, 0.02] + [0.5] * 8))
        result = holm(pvalues, FAMILY)
        self.assertEqual(result["rejected"], list(FAMILY[:3]))
        self.assertAlmostEqual(result["adjusted_pvalues"][FAMILY[0]], 0.012)
        self.assertAlmostEqual(result["adjusted_pvalues"][FAMILY[1]], 0.022)
        self.assertAlmostEqual(result["adjusted_pvalues"][FAMILY[2]], 0.04)
        self.assertAlmostEqual(result["adjusted_pvalues"][FAMILY[3]], 0.18)
        self.assertEqual(result["formal_a_samples"], 0)

    def test_holm_missing_and_null_cannot_shrink_twelve(self):
        for pvalues in [{FAMILY[0]: 0.001}, dict.fromkeys(FAMILY, None),
                        {**dict.fromkeys(FAMILY, 0.5), "extra": 0.0}]:
            result = holm(pvalues, FAMILY)
            self.assertEqual(result["family_size"], 12)
            self.assertEqual(result["rejected"], [])
            self.assertIsNone(result["adjusted_pvalues"])

    def test_holm_requires_unique_explicit_twelve_and_valid_p(self):
        for family in [FAMILY[:-1], FAMILY + ("extra",), ("x",) * 12, list(FAMILY)]:
            with self.assertRaises(StatisticsBlocked):
                holm({}, family)
        with self.assertRaises(StatisticsBlocked):
            holm(dict.fromkeys(FAMILY, float("inf")), FAMILY)

    @staticmethod
    def plan():
        return {"scope": "RESEARCH_ONLY", "family_ids": list(FAMILY), "target_n": 3,
                "expected_issue_ids": ["SSQ:future1", "SSQ:future2", "SSQ:future3"],
                "alpha": 0.05, "minimum_effect": 0.01,
                "stop_rule": "FIXED_N_NO_EARLY_SUCCESS_NO_EXTENSION", "replication_required": True}

    def test_fixed_plan_collecting_and_complete_never_promote(self):
        plan = self.plan()
        result = validate_fixed_plan(plan, plan["expected_issue_ids"][:2])
        self.assertEqual(result["status"], "COLLECTING_NO_EARLY_DECISION")
        completed = validate_fixed_plan(plan, plan["expected_issue_ids"])
        self.assertEqual(completed["status"], "RESEARCH_FIXED_N_COMPLETE")
        self.assertEqual(result["plan_sha256"], completed["plan_sha256"])
        self.assertEqual(completed["formal_a_samples"], 0)

    def test_fixed_plan_missing_reordered_duplicate_or_extra_issue_block(self):
        plan = self.plan()
        for issues in [["SSQ:future2"], ["SSQ:future1", "SSQ:future1"],
                       plan["expected_issue_ids"] + ["SSQ:future4"]]:
            with self.assertRaises(StatisticsBlocked):
                validate_fixed_plan(plan, issues)

    def test_fixed_plan_rejects_optional_stop_missing_fields_false_replication(self):
        for field, value in [("stop_rule", "STOP_WHEN_SIGNIFICANT"), ("target_n", True),
                             ("replication_required", False), ("scope", "FORMAL"),
                             ("minimum_effect", 0), ("family_ids", [])]:
            plan = self.plan()
            plan[field] = value
            with self.assertRaises(StatisticsBlocked):
                validate_fixed_plan(plan)
        plan = self.plan()
        del plan["alpha"]
        with self.assertRaises(StatisticsBlocked):
            validate_fixed_plan(plan)

    def test_precision_n_achieves_requested_conservative_radius(self):
        n = precision_sample_size(0.1)
        self.assertLessEqual(sqrt(2 * log(40) / n), 0.1)
        self.assertGreater(sqrt(2 * log(40) / (n - 1)), 0.1)
        for value in [0, -1, float("nan"), True]:
            with self.assertRaises(StatisticsBlocked):
                precision_sample_size(value)


if __name__ == "__main__":
    unittest.main()

