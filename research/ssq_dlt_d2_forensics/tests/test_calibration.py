"""Independent finite support checks; no historical or holdout data are read."""
from itertools import combinations
import math
import unittest

from research.ssq_dlt_d2_forensics import calibration as cal


def enumerate_law(n, k, law, *, favoured=(1, 2), ring=None, rho=0.25):
    """Enumerate actual subset masses independently of oracle formulas."""
    subsets = tuple(combinations(range(1, n + 1), k))
    if law == "UNIFORM":
        mass = dict.fromkeys(subsets, 1.0)
    elif law == "MARGINAL_STRONG":
        mass = {subset: math.prod(3.0 if i in favoured else 1.0 for i in subset) for subset in subsets}
    elif law == "PAIR_STRONG":
        mass = {subset: 8.0 if set(favoured).issubset(subset) else 1.0 for subset in subsets}
    elif law == "RING_PERSISTENT":
        mass = dict.fromkeys(subsets, (1.0 - rho) / len(subsets))
        for start in range(n):
            subset = tuple(sorted(ring[(start + offset) % n] for offset in range(k)))
            mass[subset] += rho / n
    else:
        raise ValueError(law)
    z = math.fsum(mass.values())
    return {subset: value / z for subset, value in mass.items()}


def pair_marginals(mass, n):
    return {pair: math.fsum(value for subset, value in mass.items() if set(pair).issubset(subset))
            for pair in combinations(range(1, n + 1), 2)}


class OracleTest(unittest.TestCase):
    def test_every_oracle_pair_matches_independent_small_enumeration(self):
        n, k, ring = 8, 3, [3, 7, 1, 6, 2, 8, 4, 5]
        for law in ("UNIFORM", "MARGINAL_STRONG", "PAIR_STRONG", "RING_PERSISTENT"):
            with self.subTest(law=law):
                mass = enumerate_law(n, k, law, ring=ring)
                expected = pair_marginals(mass, n)
                actual = cal.true_pair_probabilities(law, n, k, ring=ring)
                self.assertEqual(set(actual), set(expected))
                for pair, value in expected.items():
                    self.assertAlmostEqual(actual[pair], value, places=12)
                self.assertAlmostEqual(math.fsum(actual.values()), math.comb(k, 2), places=12)
                for i in range(1, n + 1):
                    marginal = math.fsum(value for subset, value in mass.items() if i in subset)
                    degree = math.fsum(value for pair, value in actual.items() if i in pair)
                    self.assertAlmostEqual(degree, (k - 1) * marginal, places=12)

    def test_pair_tilt_distinguishes_overlap_and_disjoint_pairs(self):
        n, k = 8, 4
        actual = cal.true_pair_probabilities("PAIR_STRONG", n, k)
        expected = pair_marginals(enumerate_law(n, k, "PAIR_STRONG"), n)
        for pair in ((1, 2), (1, 3), (3, 4)):
            self.assertAlmostEqual(actual[pair], expected[pair], places=13)
        self.assertGreater(actual[1, 2], actual[1, 3])
        self.assertGreater(actual[1, 3], actual[3, 4])
        self.assertNotAlmostEqual(actual[3, 4], math.comb(k, 2) / math.comb(n, 2), places=8)

    def test_ring_formula_wraparound_large_k_and_boundaries(self):
        n, ring = 6, [4, 1, 6, 3, 5, 2]
        for k in range(n + 1):
            expected = pair_marginals(enumerate_law(n, k, "RING_PERSISTENT", ring=ring), n)
            actual = cal.true_pair_probabilities("RING_PERSISTENT", n, k, ring=ring)
            for pair in expected:
                self.assertAlmostEqual(actual[pair], expected[pair], places=13)
        q = cal.true_pair_probabilities("RING_PERSISTENT", n, 3, ring=ring)
        for i in range(1, n + 1):
            self.assertAlmostEqual(math.fsum(value for pair, value in q.items() if i in pair) / 2, 0.5)

    def test_all_negative_law_aliases_are_exactly_uniform(self):
        expected = cal.true_pair_probabilities("UNIFORM", 35, 5)
        for alias in ("FAIR", "SCRAMBLED_PAIR_STRONG", "RING_SCRAMBLED"):
            self.assertEqual(cal.true_pair_probabilities(alias, 35, 5), expected)

    def test_invalid_oracle_laws_and_law_inputs_fail_closed(self):
        for call in (
            lambda: cal.true_pair_probabilities("UNKNOWN", 8, 3),
            lambda: cal.true_pair_probabilities("UNIFORM", True, 3),
            lambda: cal.true_pair_probabilities("PAIR_STRONG", 8, 3, favoured_pair=(1, 1)),
            lambda: cal.true_pair_probabilities("PAIR_STRONG", 8, 3, odds_ratio=0),
            lambda: cal.true_pair_probabilities("RING_PERSISTENT", 8, 3, ring=list(range(8))),
            lambda: cal.true_pair_probabilities("RING_PERSISTENT", 8, 3, ring=list(range(1, 9)), rho=2),
        ):
            with self.assertRaises(ValueError):
                call()


class DecompositionTest(unittest.TestCase):
    def setUp(self):
        self.n, self.k = 6, 3
        self.truth_mass = enumerate_law(self.n, self.k, "PAIR_STRONG")
        self.truth = pair_marginals(self.truth_mass, self.n)
        self.prior = pair_marginals(enumerate_law(self.n, self.k, "MARGINAL_STRONG"), self.n)
        # Four legal draws generate an empirical probability map with exact
        # fixed-k pair mass.  No independent-errors assumption is introduced.
        empirical_mass = {(1, 2, 3): 0.5, (1, 4, 6): 0.25, (2, 3, 5): 0.25}
        self.empirical = pair_marginals(empirical_mass, self.n)

    def test_three_term_mse_and_every_pathwise_brier_identity(self):
        for front in self.truth_mass:
            result = cal.brier_decomposition(self.empirical, self.prior, self.truth, list(front))
            for key in ("mix_mse_identity_residual", "mix_oracle_identity_residual", "mix_uniform_identity_residual"):
                self.assertLess(abs(result[key]), 1e-14)
            self.assertAlmostEqual(result["mix_mse"], result["mix_mse_empirical_term"]
                                   + result["mix_mse_prior_term"] + result["mix_mse_cross_term"], places=14)
        self.assertNotEqual(result["mix_mse_cross_term"], 0.0)

    def test_exact_expectation_is_oracle_mse_without_pair_independence(self):
        weighted = {front: cal.brier_decomposition(self.empirical, self.prior, self.truth, list(front))
                    for front in self.truth_mass}
        mean = lambda key: math.fsum(self.truth_mass[front] * row[key] for front, row in weighted.items())
        first = next(iter(weighted.values()))
        self.assertAlmostEqual(mean("mix_oracle_realized_excess"), first["mix_mse"], places=14)
        self.assertAlmostEqual(mean("mix_uniform_realized_excess"), first["mix_mse"] - first["uniform_mse"], places=14)
        self.assertAlmostEqual(mean("mix_oracle_martingale_term"), 0.0, places=14)
        self.assertAlmostEqual(mean("mix_uniform_martingale_term"), 0.0, places=14)
        self.assertAlmostEqual(mean("oracle_brier"), first["oracle_expected_brier"], places=14)

    def test_fair_expected_excess_is_nonuniform_probability_cost(self):
        uniform = cal.true_pair_probabilities("UNIFORM", self.n, self.k)
        result = cal.brier_decomposition(self.empirical, self.prior, uniform, [1, 2, 3])
        self.assertEqual(result["uniform_mse"], 0.0)
        self.assertGreater(result["mix_uniform_expected_excess"], 0.0)
        p0 = math.comb(self.k, 2) / math.comb(self.n, 2)
        self.assertAlmostEqual(result["uniform_brier"], p0 * (1.0 - p0), places=14)

    def test_alpha_half_preserves_strict_order_mass_and_fair_mse_quarter(self):
        original = dict(self.prior)
        shrunk = cal.uniform_shrink(self.prior, self.n, self.k)
        self.assertEqual(self.prior, original)
        self.assertAlmostEqual(math.fsum(shrunk.values()), math.comb(self.k, 2), places=13)
        for a, b in combinations(self.prior, 2):
            if self.prior[a] < self.prior[b]:
                self.assertLess(shrunk[a], shrunk[b])
        uniform = cal.true_pair_probabilities("UNIFORM", self.n, self.k)
        mean_square = lambda p: math.fsum((p[pair] - uniform[pair]) ** 2 for pair in p) / len(p)
        self.assertAlmostEqual(mean_square(shrunk), mean_square(self.prior) / 4.0, places=14)

    def test_incomplete_probabilities_and_wrong_mass_fail_closed(self):
        missing = dict(self.prior)
        del missing[1, 2]
        with self.assertRaises(ValueError):
            cal.brier_decomposition(self.empirical, missing, self.truth, [1, 2, 3])
        wrong_mass = dict.fromkeys(self.prior, 0.0)
        with self.assertRaises(ValueError):
            cal.brier_decomposition(self.empirical, wrong_mass, self.truth, [1, 2, 3])


class MomentFitTest(unittest.TestCase):
    def test_fit_recovers_independently_enumerated_product_law(self):
        n, k = 8, 3
        weights = [0.2, 0.5, 0.8, 1.1, 1.4, 2.0, 3.0, 4.0]
        masses = {subset: math.prod(weights[i - 1] for i in subset)
                  for subset in combinations(range(1, n + 1), k)}
        z = math.fsum(masses.values())
        mass = {subset: value / z for subset, value in masses.items()}
        target = [math.fsum(value for subset, value in mass.items() if i in subset)
                  for i in range(1, n + 1)]
        original = target[:]
        result = cal.fit_moment_matched_cb(target, k)
        self.assertEqual(target, original)
        self.assertTrue(result["converged"])
        self.assertGreater(result["initial_max_abs_error"], 1e-4)
        self.assertLessEqual(result["max_abs_error"], 1e-9)
        self.assertLessEqual(result["iterations"], 200)
        expected = pair_marginals(mass, n)
        for pair, value in expected.items():
            self.assertLess(abs(result["pair_probabilities"][pair] - value), 1e-8)
        self.assertAlmostEqual(math.fsum(result["pair_probabilities"].values()), math.comb(k, 2), places=11)
        for i, target_i in enumerate(target, 1):
            recovered = math.fsum(value for pair, value in result["pair_probabilities"].items() if i in pair) / (k - 1)
            self.assertLess(abs(recovered - target_i), 1.1e-9)

    def test_uniform_already_matches_and_snapshot_schedule_is_fixed(self):
        result = cal.fit_moment_matched_cb([3.0 / 8.0] * 8, 3)
        self.assertTrue(result["converged"])
        self.assertEqual(result["iterations"], 0)
        self.assertEqual(cal.SNAPSHOT_INDICES, (0, 60, 120, 180, 239))
        self.assertEqual(result["maxiter"], 200)
        self.assertEqual(result["tolerance"], 1e-9)

    def test_nonconvergence_is_exposed_without_restart_or_fallback(self):
        target = [0.01, 0.04, 0.10, 0.20, 0.30, 0.55, 0.80, 1.0 - 1e-10]
        target[5] += 1e-10  # Sum is exactly three within floating precision.
        result = cal.fit_moment_matched_cb(target, 3, maxiter=1, tol=1e-14)
        self.assertFalse(result["converged"])
        self.assertEqual(result["iterations"], 1)
        self.assertGreater(result["max_abs_error"], 1e-14)
        self.assertEqual(result["algorithm"], "CYCLIC_EXACT_COORDINATE_ODDS_SCALING_LOG_SPACE")

    def test_targets_must_be_interior_and_sum_to_k(self):
        for target, k in (([0.0, 0.5, 0.5], 1), ([0.2, 0.2, 0.2], 1),
                          ([0.5, True, 0.5], 2), ([1.0, 1.0], 2), ([float("nan"), 0.5, 0.5], 1)):
            with self.assertRaises(ValueError):
                cal.fit_moment_matched_cb(target, k)


if __name__ == "__main__":
    unittest.main()
