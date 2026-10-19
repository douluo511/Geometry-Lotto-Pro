"""Independent finite-support audits; never generate the registered study.

Rational path masses and Decimal probability recurrences provide references
that do not call the production probability or sampling routines.  These are
checks of the stated synthetic assumptions, not evidence about lottery draws.
"""
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import combinations, product
import math
import unittest

from research.ssq_dlt_d2_forensics import calibration, protocol


def product_law(weights, k):
    subsets = tuple(combinations(range(1, len(weights) + 1), k))
    raw = {s: math.prod(weights[i - 1] for i in s) for s in subsets}
    total = math.fsum(raw.values())
    return {s: value / total for s, value in raw.items()}


def single_and_pair_moments(mass, n):
    singles = [math.fsum(value for s, value in mass.items() if i in s)
               for i in range(1, n + 1)]
    pairs = {pair: math.fsum(value for s, value in mass.items()
                             if set(pair).issubset(s))
             for pair in combinations(range(1, n + 1), 2)}
    return singles, pairs


def decimal_binomial_masses(n, probability):
    """Forward PMF recurrence at 70 digits, independent of log-tail code."""
    with localcontext() as context:
        context.prec = 70
        p = Decimal(probability.numerator) / Decimal(probability.denominator)
        q = Decimal(1) - p
        masses = [q ** n]
        for h in range(n):
            masses.append(masses[-1] * Decimal(n - h) * p / (Decimal(h + 1) * q))
        return masses


class PredictablePairLawTests(unittest.TestCase):
    def test_adaptive_hit_paths_have_exact_bernoulli_product_law(self):
        # Six possible 2-of-4 draws.  The two predictors adapt differently to
        # the entire prefix, including a rule that changes after every hit.
        # Enumeration integrates all hidden prior outcomes, not only counts.
        n, k, periods = 4, 2, 4
        draws = tuple(combinations(range(1, n + 1), k))
        patterns = [Counter(), Counter()]
        pair_changes = [False, False]
        for path in product(draws, repeat=periods):
            history, hit_history = [], [[], []]
            previous = [None, None]
            for front in path:
                scores = Counter(i for past in history for i in past)
                hot = tuple(sorted(sorted(range(1, n + 1),
                                          key=lambda i: (-scores[i], i))[:2]))
                # Even a rule driven by its own prior successes remains
                # predictable; no current front is passed to either rule.
                rotating = draws[(sum(hit_history[1]) + len(history)) % len(draws)]
                for model, pair in enumerate((hot, rotating)):
                    pair_changes[model] |= previous[model] is not None and previous[model] != pair
                    previous[model] = pair
                    hit_history[model].append(int(set(pair).issubset(front)))
                history.append(front)
            for model, hits in enumerate(hit_history):
                patterns[model][tuple(hits)] += 1
        p0 = Fraction(math.comb(n - 2, k - 2), math.comb(n, k))
        for model in range(2):
            self.assertTrue(pair_changes[model])
            self.assertEqual(len(patterns[model]), 2 ** periods)
            for hits, count in patterns[model].items():
                expected = p0 ** sum(hits) * (1 - p0) ** (periods - sum(hits))
                self.assertEqual(Fraction(count, len(draws) ** periods), expected)

        oracle = calibration.true_pair_probabilities("UNIFORM", n, k)
        self.assertTrue(all(value == float(p0) for value in oracle.values()))

    def test_current_outcome_pair_is_an_explicit_leakage_counterexample(self):
        # This diagnostic must distinguish predictability from mere legality:
        # a legal pair selected after observing the draw succeeds every time.
        draws = tuple(combinations(range(1, 6), 3))
        successes = sum(set(front[:2]).issubset(front) for front in draws)
        fair = Fraction(math.comb(3, 1), math.comb(5, 3))
        self.assertEqual(Fraction(successes, len(draws)), 1)
        self.assertNotEqual(fair, 1)


class IndependentInferenceTests(unittest.TestCase):
    def test_two_sided_values_are_discretely_superuniform_for_asymmetric_nulls(self):
        # Exact rational PMFs check both equality to the declared doubled-tail
        # convention and its frequentist calibration at every attained level.
        for n in (1, 2, 7, 19):
            for p in (Fraction(1, 33), Fraction(1, 7), Fraction(2, 5), Fraction(5, 6)):
                masses = [Fraction(math.comb(n, h)) * p ** h * (1 - p) ** (n - h)
                          for h in range(n + 1)]
                expected = [min(Fraction(1), 2 * min(sum(masses[:h + 1]), sum(masses[h:])))
                            for h in range(n + 1)]
                for h, value in enumerate(expected):
                    actual = protocol.two_sided_binomial(h, n, float(p))
                    self.assertAlmostEqual(actual, float(value), delta=2e-13)
                for alpha in set(expected):
                    rejection_probability = sum(mass for mass, pvalue in zip(masses, expected)
                                                if pvalue <= alpha)
                    self.assertLessEqual(rejection_probability, alpha)

    def test_registered_power_and_both_critical_boundaries_against_decimal_pmf(self):
        # This reads design constants only.  It never generates predictions,
        # outcomes, or any complete registered stream at the study root seed.
        with localcontext() as context:
            context.prec = 65
            n = 24 * 240
            alpha_tail = Decimal(1) / Decimal(960)
            for game, upper, count in (("SSQ", 33, 6), ("DLT", 35, 5)):
                p0 = Fraction(count * (count - 1), upper * (upper - 1))
                masses = decimal_binomial_masses(n, p0)
                self.assertLess(abs(sum(masses) - Decimal(1)), Decimal("1e-60"))
                low_tail, high_tail = [], [Decimal(0)] * (n + 1)
                running = Decimal(0)
                for mass in masses:
                    running += mass
                    low_tail.append(running)
                running = Decimal(0)
                for h in range(n, -1, -1):
                    running += masses[h]
                    high_tail[h] = running
                low = max(h for h, value in enumerate(low_tail) if value <= alpha_tail)
                high = min(h for h, value in enumerate(high_tail) if value <= alpha_tail)
                alternative = decimal_binomial_masses(n, p0 + Fraction(1, 100))
                reference_power = sum(alternative[:low + 1]) + sum(alternative[high:])
                actual = protocol.exact_negative_power(game)
                self.assertEqual(actual["n"], n)
                self.assertEqual(actual["critical_low"], low)
                self.assertEqual(actual["critical_high"], high)
                self.assertAlmostEqual(actual["bonferroni_two_sided_power"],
                                       float(reference_power), delta=2e-10)
                self.assertLessEqual(low_tail[low], alpha_tail)
                self.assertGreater(low_tail[low + 1], alpha_tail)
                self.assertLessEqual(high_tail[high], alpha_tail)
                self.assertGreater(high_tail[high - 1], alpha_tail)

    def test_holm_24_handles_maximally_dependent_valid_pvalues(self):
        # A single discrete Uniform p copied to 24 perfectly dependent tests
        # is a worst-case dependence fixture.  Enumerate its entire support.
        alpha = Fraction(1, 20)
        rejections = 0
        support_size = 960
        for index in range(1, support_size + 1):
            p = Fraction(index, support_size)
            family = {f"hypothesis_{h:02d}": float(p) for h in range(24)}
            adjusted = protocol.stats.holm_adjust(family)
            rejections += any(value <= float(alpha) for value in adjusted.values())
            expected = min(Fraction(1), 24 * p)
            for value in adjusted.values():
                self.assertAlmostEqual(value, float(expected), delta=1e-15)
        self.assertLessEqual(Fraction(rejections, support_size), alpha)
        self.assertGreater(rejections, 0)


class IndependentMomentStructureTests(unittest.TestCase):
    def test_fitted_product_law_commutes_with_complementation(self):
        n, k = 7, 3
        weights = [0.3, 0.7, 1.1, 1.8, 2.4, 3.2, 5.0]
        target, true_pairs = single_and_pair_moments(product_law(weights, k), n)
        direct = calibration.fit_moment_matched_cb(target, k, tol=1e-11)
        complement = calibration.fit_moment_matched_cb([1 - p for p in target], n - k,
                                                     tol=1e-11)
        self.assertTrue(direct["converged"])
        self.assertTrue(complement["converged"])
        for pair, expected in true_pairs.items():
            i, j = pair
            self.assertAlmostEqual(direct["pair_probabilities"][pair], expected, delta=2e-10)
            # P(i,j both absent) = 1 - P(i) - P(j) + P(i,j).
            expected_complement = 1 - target[i - 1] - target[j - 1] + expected
            self.assertAlmostEqual(complement["pair_probabilities"][pair],
                                   expected_complement, delta=2e-10)

    def test_ring_interaction_survives_exact_population_marginal_matching(self):
        # Enumerate the actual ring-mixture law, rather than invoking oracle q
        # to form targets.  Uniform population marginals cannot encode its
        # distance-dependent pair structure in a fixed-k product-weight law.
        n, k, rho = 8, 3, Fraction(1, 4)
        ring = [3, 7, 1, 6, 2, 8, 4, 5]
        subsets = tuple(combinations(range(1, n + 1), k))
        mass = dict.fromkeys(subsets, (1 - rho) / len(subsets))
        for start in range(n):
            front = tuple(sorted(ring[(start + offset) % n] for offset in range(k)))
            mass[front] += rho / n
        self.assertEqual(sum(mass.values()), 1)
        target, truth = single_and_pair_moments(mass, n)
        self.assertTrue(all(p == k / n for p in target))
        fit = calibration.fit_moment_matched_cb(target, k)
        self.assertTrue(fit["converged"])
        self.assertEqual(fit["iterations"], 0)
        p0 = math.comb(k, 2) / math.comb(n, 2)
        for value in fit["pair_probabilities"].values():
            self.assertAlmostEqual(value, p0, delta=1e-14)
        gap = math.fsum((fit["pair_probabilities"][pair] - value) ** 2
                        for pair, value in truth.items()) / len(truth)
        self.assertGreater(gap, 1e-4)
        self.assertGreater(max(truth.values()), max(fit["pair_probabilities"].values()))


if __name__ == "__main__":
    unittest.main()
