"""Complete synthetic adaptive probability trees; no lottery/model/archive IO.

Probabilities and conditional means use exact Fraction arithmetic. Numerical
boundaries are independently checked with 100-digit Decimal arithmetic. Every
lambda, alpha, center and horizon in this file is a test fixture, not a registered
method parameter, chosen model, future trial or power claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
import unittest

from research.ssq_dlt_conditional_inference.core import (
    analyze, fair_baseline_hits, paired_hits,
)


AUDIT_RECEIPTS: list[dict] = []
TOLERANCE = Decimal("1e-65")


def decimal_fraction(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


@dataclass(frozen=True)
class Leaf:
    probability: Fraction
    values: tuple[int, ...]
    conditional_means: tuple[Fraction, ...]


def complete_tree(depth, transition):
    """Return every positive-mass prefix; enumerate, never sample a path."""
    leaves = (Leaf(Fraction(1), (), ()),)
    levels = []
    for _ in range(depth):
        children = []
        for leaf in leaves:
            branches = tuple(transition(leaf.values))
            assert sum((p for _, p in branches), Fraction(0)) == 1
            assert all(p > 0 for _, p in branches)
            assert len({value for value, _ in branches}) == len(branches)
            mu = sum((value * p for value, p in branches), Fraction(0))
            for value, probability in branches:
                children.append(Leaf(
                    leaf.probability * probability,
                    leaf.values + (value,), leaf.conditional_means + (mu,),
                ))
        leaves = tuple(children)
        assert sum((x.probability for x in leaves), Fraction(0)) == 1
        levels.append(leaves)
    return tuple(levels)


def varying_difference_law(past):
    """Conditional advantage and discordance both vary with the exact past."""
    if not past or past[-1] == 0:
        return ((-1, Fraction(1, 4)), (0, Fraction(1, 2)), (1, Fraction(1, 4)))
    if past[-1] == 1:
        return ((-1, Fraction(1, 2)), (0, Fraction(1, 4)), (1, Fraction(1, 4)))
    return ((-1, Fraction(1, 8)), (0, Fraction(1, 4)), (1, Fraction(5, 8)))


def adaptive_null_difference_law(past):
    """Every conditional mean is <=0; the law is demonstrably non-IID."""
    if not past or past[-1] == 0:
        return ((-1, Fraction(1, 4)), (0, Fraction(1, 2)), (1, Fraction(1, 4)))
    if past[-1] == 1:
        return ((-1, Fraction(1, 2)), (0, Fraction(1, 4)), (1, Fraction(1, 4)))
    return ((-1, Fraction(1, 8)), (0, Fraction(3, 4)), (1, Fraction(1, 8)))


def varying_hit_law(past):
    p = Fraction(1, 8) if past and past[-1] == 1 else Fraction(5, 8)
    return ((0, 1 - p), (1, p))


def adaptive_null_hit_law(past):
    p = Fraction(1, 8) if past and past[-1] == 1 else Fraction(1, 4)
    return ((0, 1 - p), (1, p))


def compensated_endpoint_null_law(past):
    """Early positive means, later compensation; only endpoint mean is <=0."""
    if len(past) < 3:
        return ((-1, Fraction(1, 4)), (0, Fraction(1, 4)), (1, Fraction(1, 2)))
    if past[-1] == -1:
        return ((-1, Fraction(5, 8)), (0, Fraction(1, 4)), (1, Fraction(1, 8)))
    return ((-1, Fraction(1, 2)), (0, Fraction(1, 4)), (1, Fraction(1, 4)))


class AdaptiveTreeTests(unittest.TestCase):
    def check_tree(self, *, label, law, depth, lower, upper, center,
                   lambdas, alpha, null_mean, null_every_node=False,
                   check_wrapper=False, endpoint_null_only=False):
        """Audit exact path masses, actual API coverage and independent formula."""
        with localcontext() as context:
            context.prec = 100
            lo, hi, m, a, null = map(Decimal, (lower, upper, center, alpha, null_mean))
            scale = hi - lo
            ls = tuple(map(Decimal, lambdas))
            cs = tuple(-(1 - lam).ln() - lam for lam in ls)
            levels = complete_tree(depth, law)
            level_receipts = []
            for leaves in levels:
                n = len(leaves[0].values)
                expectations = [Decimal(0) for _ in ls]
                bad_one, bad_two, false_rejection = (Fraction(0),) * 3
                for leaf in leaves:
                    if null_every_node:
                        self.assertTrue(all(decimal_fraction(x) <= null
                                            for x in leaf.conditional_means))
                    result = analyze(
                        leaf.values, lower=lower, upper=upper, center=center,
                        lambdas=lambdas, alpha=alpha, null_mean=null_mean,
                        expected_n=n,
                    )
                    total = sum(map(Decimal, leaf.values), Decimal(0))
                    true_total = sum(map(decimal_fraction, leaf.conditional_means), Decimal(0))
                    true_mean = true_total / n
                    null_is_required = null_every_node or (endpoint_null_only and n == depth)
                    if null_is_required:
                        self.assertLessEqual(true_mean, null)
                    v = sum((((Decimal(x) - m) / scale) ** 2 for x in leaf.values), Decimal(0))
                    self.assertLessEqual(abs(Decimal(result["mean"]) - total / n), TOLERANCE)
                    self.assertLessEqual(abs(Decimal(result["normalized_squared_residual_sum"]) - v),
                                         TOLERANCE)
                    independently_computed_logs = []
                    for index, (lam, coefficient) in enumerate(zip(ls, cs)):
                        log_m = lam * (total - true_total) / scale - coefficient * v
                        expectations[index] += decimal_fraction(leaf.probability) * log_m.exp()
                        log_e_null = lam * (total - n * null) / scale - coefficient * v
                        independently_computed_logs.append(log_e_null)
                        self.assertLessEqual(
                            abs(Decimal(result["components"][index]["log_e"]) - log_e_null),
                            TOLERANCE,
                        )
                    expected_log_p = min(Decimal(0), Decimal(len(ls)).ln()
                                         - max(independently_computed_logs))
                    self.assertLessEqual(abs(Decimal(result["log_p_one_sided"]) - expected_log_p),
                                         TOLERANCE)
                    if Decimal(result["lower_one_sided"]) > true_mean + TOLERANCE:
                        bad_one += leaf.probability
                    left, right = map(Decimal, result["ci_two_sided"])
                    if true_mean < left - TOLERANCE or true_mean > right + TOLERANCE:
                        bad_two += leaf.probability
                    if null_is_required and Decimal(result["log_p_one_sided"]) <= a.ln():
                        false_rejection += leaf.probability
                    if check_wrapper:
                        if (lower, upper, center) == ("-1", "1", "0"):
                            # One legal binary pair realizes each D. At D=0,
                            # alternate 00/11 according to the prior observed
                            # history; never pretend both hits are independent.
                            model, baseline = [], []
                            for index, difference in enumerate(leaf.values):
                                common = int(sum(leaf.values[:index]) > 0)
                                model.append(1 if difference == 1 else 0 if difference == -1 else common)
                                baseline.append(0 if difference == 1 else 1 if difference == -1 else common)
                            wrapped = paired_hits(model, baseline, lambdas=lambdas, alpha=alpha,
                                                  null_difference=null_mean, expected_n=n)
                            self.assertEqual(result, wrapped)
                            discordance = sum(x != 0 for x in leaf.values)
                            self.assertEqual(Decimal(result["normalized_squared_residual_sum"]),
                                             Decimal(discordance) / 4)
                        else:
                            wrapped = fair_baseline_hits(
                                leaf.values, p0=center, lambdas=lambdas, alpha=alpha,
                                null_increment=str(null - m), expected_n=n,
                            )
                            self.assertEqual(result, wrapped)
                for expectation in expectations:
                    self.assertLessEqual(expectation, Decimal(1) + TOLERANCE)
                # Failure events have exact rational probability even though
                # membership uses the independently audited numeric boundary.
                self.assertLessEqual(bad_one, Fraction(alpha))
                self.assertLessEqual(bad_two, Fraction(alpha))
                if null_is_required:
                    self.assertLessEqual(false_rejection, Fraction(alpha))
                level_receipts.append({
                    "n_fixture": n, "complete_path_count": len(leaves),
                    "total_path_probability_exact": "1",
                    "true_centered_e_expectations": [str(x) for x in expectations],
                    "one_sided_noncoverage_probability_exact": str(bad_one),
                    "two_sided_noncoverage_probability_exact": str(bad_two),
                    "null_rejection_probability_exact": str(false_rejection)
                    if null_is_required else "NOT_REQUIRED_NULL_AT_THIS_PREFIX",
                })
            receipt = {
                "fixture": label, "alpha_fixture": alpha,
                "lambda_fixtures_not_registered_grid": list(lambdas),
                "fixed_center_fixture": center, "null_mean_fixture": null_mean,
                "levels": level_receipts,
            }
            AUDIT_RECEIPTS.append(receipt)
            return receipt

    def test_variable_conditional_means_paired_tree(self):
        receipt = self.check_tree(
            label="VARIABLE_MEAN_NON_IID_PAIRED", law=varying_difference_law,
            depth=6, lower="-1", upper="1", center="0", lambdas=("0.6",),
            alpha="0.6", null_mean="0", check_wrapper=True,
        )
        # This fixture has actual failure events, so coverage is not checked
        # solely against an interval that contains the entire support.
        self.assertGreater(Fraction(receipt["levels"][-1]["two_sided_noncoverage_probability_exact"]), 0)

    def test_adaptive_null_paired_tree_with_explicit_grid(self):
        receipt = self.check_tree(
            label="NON_IID_PAIRED_NULL_GRID", law=adaptive_null_difference_law,
            depth=6, lower="-1", upper="1", center="0", lambdas=("0.2", "0.6"),
            alpha="0.6", null_mean="0", null_every_node=True,
        )
        self.assertGreater(Fraction(receipt["levels"][-1]["null_rejection_probability_exact"]), 0)

    def test_marginal_tree_distinguishes_center_and_null(self):
        self.check_tree(
            label="VARIABLE_MEAN_MARGINAL_DISTINCT_CENTER_NULL", law=varying_hit_law,
            depth=6, lower="0", upper="1", center="0.25", lambdas=("0.2", "0.6"),
            alpha="0.6", null_mean="0.35", check_wrapper=True,
        )

    def test_adaptive_marginal_null_tree(self):
        receipt = self.check_tree(
            label="NON_IID_MARGINAL_NULL", law=adaptive_null_hit_law,
            depth=6, lower="0", upper="1", center="0.25", lambdas=("0.2", "0.6"),
            alpha="0.6", null_mean="0.25", null_every_node=True,
        )
        self.assertGreater(Fraction(receipt["levels"][-1]["null_rejection_probability_exact"]), 0)


    def test_endpoint_average_null_allows_early_positive_means(self):
        self.check_tree(
            label="ENDPOINT_AVERAGE_NULL_WITH_EARLY_POSITIVE_MEANS",
            law=compensated_endpoint_null_law,
            depth=6, lower="-1", upper="1", center="0", lambdas=("0.2", "0.6"),
            alpha="0.6", null_mean="0", endpoint_null_only=True,
        )
        leaves = complete_tree(6, compensated_endpoint_null_law)[-1]
        self.assertTrue(all(any(mu > 0 for mu in leaf.conditional_means) for leaf in leaves))
        self.assertTrue(all(sum(leaf.conditional_means, Fraction(0)) <= 0 for leaf in leaves))


if __name__ == "__main__":
    unittest.main()
