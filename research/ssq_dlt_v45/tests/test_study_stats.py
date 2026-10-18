"""Independent combinatorial checks and sparse-event statistical edge cases."""
import itertools
import math
import unittest
from fractions import Fraction

from research.ssq_dlt_v45 import study_stats as stats


class StudyStatisticsTests(unittest.TestCase):
    def test_wilson_known_score_and_boundary(self):
        lower, upper = stats.wilson_interval(50, 100)
        self.assertAlmostEqual(lower, 0.4038315303659956, places=12)
        self.assertAlmostEqual(upper, 0.5961684696340044, places=12)
        self.assertEqual(stats.wilson_interval(0, 0), [0.0, 1.0])
        self.assertAlmostEqual(stats.wilson_interval(0, 100)[1], 0.03699349820698568)
        self.assertAlmostEqual(stats.wilson_interval(100, 100)[0], 1 - 0.03699349820698568)

    def test_binomial_tail_matches_small_exact_enumerations(self):
        for n in (0, 1, 2, 7, 20):
            for p in (0.0, 0.1, 0.5, 0.91, 1.0):
                for k in range(n + 2):
                    expected = sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j)
                                   for j in range(k, n + 1))
                    self.assertAlmostEqual(stats.binomial_upper_tail(k, n, p), expected, places=12)

    def test_exact_mcnemar_thousands_and_ties(self):
        self.assertEqual(stats.paired_exact_one_sided(0, 0), 1.0)
        self.assertAlmostEqual(stats.paired_exact_one_sided(5, 0), 1 / 32)
        for wins, losses in ((3, 7), (20, 11), (1500, 1700), (2600, 2400)):
            n = wins + losses
            expected = sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n)
            self.assertAlmostEqual(stats.paired_exact_one_sided(wins, losses), expected, places=10)
        self.assertGreater(stats.paired_exact_one_sided(2000, 2000), 0.5)
        self.assertLess(stats.paired_exact_one_sided(4000, 0), 1e-100)

    def test_sparse_paired_interval_and_cp_equations(self):
        lower, upper = stats.paired_difference_interval(0, 0, 100)
        exact_upper = 1 - (0.05 / 4) ** (1 / 100)
        self.assertAlmostEqual(lower, -exact_upper, places=12)
        self.assertAlmostEqual(upper, exact_upper, places=12)
        self.assertEqual(stats.paired_difference_interval(0, 0, 0), [-1.0, 1.0])
        for count in (1, 8, 40, 99):
            lo, hi = stats._cp_bounds(count, 100, 0.0125)
            self.assertAlmostEqual(stats.binomial_upper_tail(count, 100, lo), 0.0125, places=11)
            self.assertAlmostEqual(stats.binomial_upper_tail(100 - count, 100, 1 - hi), 0.0125, places=11)

    def test_paired_ci_conservative_multinomial_coverage(self):
        # Complete trinomial enumeration, not a simulation or implementation mirror.
        n, p_win, p_loss = 8, 0.12, 0.04
        truth, coverage = p_win - p_loss, 0.0
        for wins in range(n + 1):
            for losses in range(n - wins + 1):
                ties = n - wins - losses
                probability = (math.factorial(n) / math.prod(math.factorial(c) for c in (wins, losses, ties))
                               * p_win ** wins * p_loss ** losses * (1 - p_win - p_loss) ** ties)
                lo, hi = stats.paired_difference_interval(wins, losses, n)
                if lo <= truth <= hi:
                    coverage += probability
        self.assertGreaterEqual(coverage, 0.95)

    def test_paired_summary_uses_only_discordant_differences(self):
        summary = stats.paired_summary([1, 1, 0, 1, 0], [1, 0, 1, 0, 0])
        self.assertEqual((summary["wins"], summary["losses"], summary["both_hit"], summary["both_miss"]), (2, 1, 1, 1))
        self.assertAlmostEqual(summary["paired_delta"], 0.2)
        self.assertAlmostEqual(summary["p_one_sided"], 0.5)
        self.assertEqual(summary["formal_A"], 0)
        self.assertEqual(summary["decision"], "NO_EDGE")
        self.assertIsNone(stats.paired_summary([], [])["model_rate"])

    def test_holm_all_ten_game_candidates_not_per_game(self):
        raw = {f"game-candidate-{i}": p for i, p in enumerate([0.001, 0.006, 0.008, 0.02, 0.1, 0.2, 0.3, 0.4, 0.8, 1.0])}
        result = stats.holm_adjust(raw)
        self.assertAlmostEqual(result["game-candidate-0"], 0.01)
        self.assertAlmostEqual(result["game-candidate-1"], 0.054)
        self.assertAlmostEqual(result["game-candidate-2"], 0.064)
        self.assertTrue(all(result[key] >= raw[key] for key in raw))
        self.assertEqual(stats.holm_adjust({"a": 0.04, "b": 0.03, "c": 0.02}), {"c": 0.06, "b": 0.06, "a": 0.06})

    def test_exact_uniform_pair_overlaps_by_full_draw_enumeration(self):
        for game, (upper, count) in stats.GAMES.items():
            left = {1, 2}
            for overlap, right in ((0, {3, 4}), (1, {2, 3}), (2, {1, 2})):
                both = disagreement = model_only = denominator = 0
                # ~1.1 million SSQ outcomes, 324632 DLT outcomes, all enumerated.
                for draw in itertools.combinations(range(1, upper + 1), count):
                    actual = set(draw)
                    a, b = left <= actual, right <= actual
                    both += a and b
                    disagreement += a != b
                    model_only += a and not b
                    denominator += 1
                result = stats.uniform_pair_probabilities(game, overlap)
                for key, numerator in (("both_hit", both), ("disagreement", disagreement), ("model_only", model_only)):
                    fraction = result[key]
                    self.assertEqual(Fraction(fraction["numerator"], fraction["denominator"]), Fraction(numerator, denominator))
        self.assertEqual(stats.uniform_pair_probabilities("SSQ", 0)["marginal_hit"], {"numerator": 5, "denominator": 176, "value": 15 / 528})
        self.assertEqual(stats.uniform_pair_probabilities("DLT", 0)["marginal_hit"]["value"], 10 / 595)

    def test_power_fixed_targets_scenarios_and_monotonicity(self):
        report = stats.power_report()
        self.assertEqual(report["family_size"], 10)
        self.assertEqual(report["bonferroni_planning_alpha"], 0.005)
        self.assertEqual(report["primary_absolute_delta"], 0.01)
        for game in report["games"].values():
            scenarios = game["sample_size_scenarios"]
            self.assertEqual(len(scenarios), 6)
            conservative = [row for row in scenarios if row["scenario"] == "MAXIMUM_DISCORDANCE_FRECHET"]
            self.assertGreater(conservative[0]["n_approx"], conservative[1]["n_approx"])
            self.assertGreater(conservative[1]["n_approx"], conservative[2]["n_approx"])
            for row in scenarios:
                self.assertFalse(row["guaranteed_power"])
                self.assertGreater(row["n_approx"], 1000)
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_eprocess_fair_draw_one_step_expectation_is_one(self):
        # Analytic exhaustive D in {-1,0,1}, independently verify normalized mgf.
        for game in stats.GAMES:
            for overlap, left, right in ((0, [1, 2], [3, 4]), (1, [1, 2], [2, 3]), (2, [1, 2], [1, 2])):
                probabilities = stats.uniform_pair_probabilities(game, overlap)
                expected = 0.0
                for x, y, probability in ((1, 0, probabilities["model_only"]["value"]),
                                          (0, 1, probabilities["null_only"]["value"]),
                                          (0, 0, probabilities["neither_hit"]["value"]),
                                          (1, 1, probabilities["both_hit"]["value"])):
                    if probability:
                        expected += probability * stats.fair_null_eprocess(game, [left], [right], [x], [y])["final_e_value"]
                self.assertAlmostEqual(expected, 1.0, places=13)

    def test_eprocess_stable_long_series_and_identical_pairs(self):
        n = 3000
        result = stats.fair_null_eprocess("SSQ", [[1, 2]] * n, [[3, 4]] * n, [1] * n, [0] * n)
        self.assertTrue(result["e_value_overflow_use_log"])
        self.assertIsNone(result["final_e_value"])
        self.assertTrue(math.isfinite(result["final_log_e_value"]))
        self.assertLessEqual(result["anytime_p_markov"], result["fixed_final_p_markov"])
        identical = stats.fair_null_eprocess("SSQ", [[1, 2]], [[2, 1]], [0], [0])
        self.assertEqual(identical["final_e_value"], 1.0)
        self.assertEqual(identical["anytime_p_markov"], 1.0)
        with self.assertRaises(ValueError):
            stats.fair_null_eprocess("SSQ", [[1, 2]], [[2, 1]], [1], [0])

    def test_reject_malformed_or_infeasible_statistics(self):
        cases = [(stats.wilson_interval, (-1, 10)), (stats.wilson_interval, (11, 10)),
                 (stats.wilson_interval, (True, 10)), (stats.paired_exact_one_sided, (1.0, 2)),
                 (stats.paired_difference_interval, (3, 4, 6)),
                 (stats.paired_summary, ([1], [0, 1])), (stats.paired_summary, ([True], [0])),
                 (stats.holm_adjust, ({"a": float("nan")},)), (stats.holm_adjust, ({},)),
                 (stats.uniform_pair_probabilities, ("SSQ", 3)),
                 (stats.paired_sample_size, (0.02, 0.01, 0.001)),
                 (stats.paired_sample_size, (0.02, 0.01, 0.9))]
        for function, args in cases:
            with self.subTest(function=function.__name__, args=args), self.assertRaises(ValueError):
                function(*args)


if __name__ == "__main__":
    unittest.main()
