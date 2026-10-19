"""Independent small-space calibration and complete-family design checks."""
import math
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_next import inference as inf


class NextInferenceTests(unittest.TestCase):
    def test_common_metrics_keeps_distinct_nulls_and_blocks_confirmation(self):
        result = inf.common_metrics("SSQ", [1, 1, 0, 1, 0], [1, 0, 1, 0, 0])
        self.assertEqual((result["wins"], result["losses"]), (2, 1))
        self.assertAlmostEqual(result["p_one_sided"], 0.5)
        self.assertEqual(result["p_iut"], max(result["p_fair_one_sided"], result["p_one_sided"]))
        self.assertEqual(result["fair_d2_p0"], 15 / 528)
        self.assertAlmostEqual(result["paired_delta"], 0.2)
        self.assertEqual(result["independent_prospective_samples"], 0)
        self.assertTrue(result["confirmation_gate"].startswith("BLOCKED"))
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")
        empty = inf.common_metrics("DLT", [], [])
        self.assertEqual(empty["p_iut"], 1.0)
        self.assertIsNone(empty["delta_vs_fair"])

    def test_iut_does_not_substitute_the_better_component(self):
        # A chance low comparator can make paired evidence look stronger than
        # the fair-law component; conjunction must retain the weaker evidence.
        result = inf.common_metrics("SSQ", [1] * 4 + [0] * 996, [0] * 1000)
        self.assertLess(result["p_one_sided"], result["p_fair_one_sided"])
        self.assertEqual(result["p_iut"], result["p_fair_one_sided"])

    def test_all_fourteen_exploratory_hypotheses_required(self):
        metrics = {inf.hypothesis_key(game, model): {
            "p_iut": 0.001 if (game, model) == ("SSQ", inf.CANDIDATES[0]) else 1.0,
            "p_fair_one_sided": 0.001, "p_one_sided": 0.002,
        } for game in inf.GAMES for model in inf.BENCHMARKS + inf.CANDIDATES}
        result = inf.descriptive_family(metrics)
        self.assertEqual(result["family_size"], 14)
        self.assertAlmostEqual(result["p_holm_iut"]["SSQ|R46-CBPAIR-SHRINK"], 0.014)
        self.assertEqual(result["decision"], "NO_EDGE")
        with self.assertRaises(ValueError):
            inf.descriptive_family(dict(list(metrics.items())[:-1]))
        with self.assertRaises(ValueError):
            inf.descriptive_family({**metrics, "SSQ|R45-RANDOM-NULL": metrics[next(iter(metrics))]})

    def test_exact_planner_first_n_by_independent_small_enumeration(self):
        p0, p1, alpha, target = 0.1, 0.6, 0.05, 0.8

        def tail(k, n, p):
            return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j)
                       for j in range(k, n + 1))

        expected = None
        for n in range(1, 50):
            critical = next((k for k in range(n + 1) if tail(k, n, p0) <= alpha), n + 1)
            if tail(critical, n, p1) >= target:
                expected = (n, critical, tail(critical, n, p1))
                break
        result = inf.exact_binomial_plan(p0, p1, alpha, target, maximum_n=50)
        self.assertIsNotNone(expected)
        self.assertEqual((result["n"], result["critical_hits"]), expected[:2])
        self.assertAlmostEqual(result["power"], expected[2], places=12)
        self.assertLessEqual(result["actual_size"], alpha)

    def test_count_sampler_cdf_matches_full_binomial_and_extreme_center(self):
        for n in (0, 1, 8, 25):
            for p in (0.0, 0.03, 0.5, 0.97, 1.0):
                actual = inf._binomial_cdf(n, p)
                expected = 0.0
                for k in range(n + 1):
                    expected += math.comb(n, k) * p ** k * (1 - p) ** (n - k)
                    self.assertAlmostEqual(actual[k], expected, places=12)
        extreme = inf._binomial_cdf(5000, 0.5)
        self.assertEqual(extreme[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(extreme, extreme[1:])))
        self.assertGreater(extreme[2500], 0.5)
        self.assertLess(extreme[2499], 0.5)

    def test_future_design_is_fixed_independent_of_archive_and_blocks_start(self):
        protocol = inf.future_protocol()
        self.assertEqual(protocol["family_size"], 4)
        self.assertEqual(protocol["bonferroni_planning_alpha"], 0.0125)
        self.assertEqual(protocol["simulation"]["seed"], 2026101903)
        self.assertEqual(protocol["simulation"]["replications_per_cell"], 2000)
        self.assertEqual(protocol["delta_planning_alternative"], 0.01)
        self.assertEqual({g: row["fixed_n"] for g, row in protocol["games_planning"].items()},
                         {"SSQ": 8300, "DLT": 5500})
        self.assertEqual(protocol["independent_prospective_samples"], 0)
        self.assertTrue(protocol["prospective_start"].startswith("BLOCKED"))
        self.assertIn("no additional CI lower>0 or observed>=.01 gating", protocol["confirmatory_gate"])
        self.assertTrue(all(row["analytic_power_at_fixed_n"] >= 0.9
                            for row in protocol["games_planning"].values()))
        for row in protocol["one_vs_two_candidate_comparison"]:
            self.assertGreaterEqual(row["analytic_exact_80"]["power"], 0.8)

    def test_small_iid_null_joint_family_fwer_exact_enumeration(self):
        # Enumerate all 2x2 cells for n=5, not a copy of the production sampler.
        # Each component is valid under this synthetic IID joint null. IUT at
        # alpha/4 cannot exceed the analytic component's exact size; union bound
        # therefore controls any false rejection across four dependent tests.
        n, p0, joint, alpha = 5, 0.2, 0.04, 0.05 / 4
        probabilities = (joint, p0 - joint, p0 - joint, 1 - 2 * p0 + joint)
        size, total = 0.0, 0.0
        for both in range(n + 1):
            for wins in range(n - both + 1):
                for losses in range(n - both - wins + 1):
                    cells = (both, wins, losses, n - both - wins - losses)
                    mass = (math.factorial(n) / math.prod(math.factorial(c) for c in cells)
                            * math.prod(p ** c for p, c in zip(probabilities, cells)))
                    pa = inf.stats.binomial_upper_tail(both + wins, n, p0)
                    pp = inf.stats.paired_exact_one_sided(wins, losses)
                    size += mass * (max(pa, pp) <= alpha)
                    total += mass
        self.assertAlmostEqual(total, 1.0, places=12)
        self.assertLessEqual(4 * size, 0.05)

    def test_full_simulator_uses_predeclared_configuration_without_real_data(self):
        # Exercise control flow on a tiny synthetic protocol; the full frozen
        # 2000-replication experiment is run separately after plan sealing.
        small = {"hypotheses": [inf.hypothesis_key(g, m) for g in inf.GAMES for m in inf.CANDIDATES],
                 "games_planning": {g: {"fixed_n": 5} for g in inf.GAMES}}
        with patch.object(inf, "future_protocol", return_value=small), \
                patch.object(inf, "SIMULATION_REPLICATIONS", 5):
            first = inf.simulate_protocol()
            second = inf.simulate_protocol()
        self.assertEqual(first, second)
        self.assertEqual(len(first["cells"]), 12)
        for cell in first["cells"]:
            for row in cell["hypotheses"].values():
                self.assertIn("iut_at_bonferroni", row)
                self.assertIn(row["iut_holm_rejection"]["classification"],
                              {"PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE_FOR_TRUE_NULL"})
            if all(cell["alternative_configuration"]):
                self.assertEqual(cell["true_null_fwer"]["classification"], "NOT_APPLICABLE")
        self.assertEqual(first["scope"], "SIMULATED_IID_BINARY_COUNTS_NOT_REAL_PREDICTIVE_EVIDENCE")
        self.assertTrue(first["no_candidate_outcomes_used"])
        self.assertEqual(first["formal_A"], 0)


if __name__ == "__main__":
    unittest.main()
