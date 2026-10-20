from decimal import Decimal, localcontext
import math
import unittest

from research.ssq_dlt_conditional_inference.core import (
    analyze, coefficient, fair_baseline_hits, holm_log_pvalues,
    intersection_union, paired_hits,
)


class ConditionalBoundsTests(unittest.TestCase):
    def call(self, values, **changes):
        opts = dict(lower=-1, upper=1, center=0, lambdas=["0.1", "0.5"],
                    alpha="0.05", null_mean=0, expected_n=len(values))
        opts.update(changes)
        return analyze(values, **opts)

    def test_zero_discordance_has_zero_residual_variance(self):
        r = self.call([0] * 40, lambdas=["0.5"])
        self.assertEqual(Decimal(r["mean"]), 0)
        self.assertEqual(Decimal(r["normalized_squared_residual_sum"]), 0)
        self.assertEqual(Decimal(r["log_p_one_sided"]), 0)
        with localcontext() as ctx:
            ctx.prec = 80
            expected = -2 * Decimal(20).ln() / (Decimal(".5") * 40)
            self.assertLess(abs(Decimal(r["lower_one_sided"]) - expected), Decimal("1e-75"))

    def test_discordance_factor_four_and_scale_invariance(self):
        d = [-1, 0, 1, 0, 1, 0, -1]
        r = self.call(d)
        x = [(i + 1) / 2 for i in d]
        u = analyze(x, lower=0, upper=1, center=".5", lambdas=[".1", ".5"],
                    alpha=".05", null_mean=".5", expected_n=7)
        self.assertEqual(Decimal(r["normalized_squared_residual_sum"]), 1)
        self.assertEqual(r["normalized_squared_residual_sum"], u["normalized_squared_residual_sum"])
        self.assertEqual(r["log_p_one_sided"], u["log_p_one_sided"])
        with localcontext() as ctx:
            ctx.prec = 80
            for rd, rx in zip(r["ci_two_sided"], u["ci_two_sided"]):
                self.assertLess(abs(Decimal(rd) - (2 * Decimal(rx) - 1)), Decimal("1e-75"))

    def test_swap_reverses_interval(self):
        d = [1] * 300 + [-1] * 20 + [0] * 680
        a, b = self.call(d), self.call([-x for x in d])
        self.assertEqual(Decimal(a["ci_two_sided"][0]), Decimal(b["ci_two_sided"][1]).copy_negate())
        self.assertEqual(Decimal(a["ci_two_sided"][1]), Decimal(b["ci_two_sided"][0]).copy_negate())

    def test_one_sided_p_inverts_lower_bound(self):
        for wins, n in [(0, 80), (6, 80), (20, 80), (30, 80)]:
            for threshold in ["0", ".01", ".1"]:
                r = self.call([1] * wins + [0] * (n-wins), null_mean=threshold)
                self.assertEqual(Decimal(r["log_p_one_sided"]) < Decimal(".05").ln(),
                                 Decimal(r["lower_one_sided"]) > Decimal(threshold))

    def test_grid_pays_for_selection(self):
        data = [1] * 10 + [-1] * 3 + [0] * 87
        grid = self.call(data)
        solo = [self.call(data, lambdas=[x]) for x in [".1", ".5"]]
        with localcontext() as ctx:
            ctx.prec = 80
            untruncated = [Decimal(row["components"][0]["log_e"]) for row in solo]
            expected = min(Decimal(0), Decimal(2).ln() - max(untruncated))
            self.assertEqual(Decimal(grid["log_p_one_sided"]), expected)

    def test_fixed_threshold_changes_claim(self):
        d = [1] * 200 + [0] * 9800
        positive = self.call(d, null_mean=0)
        one_pp = self.call(d, null_mean=".01")
        self.assertLess(Decimal(positive["log_p_one_sided"]), Decimal(one_pp["log_p_one_sided"]))
        self.assertEqual(positive["lower_one_sided"], one_pp["lower_one_sided"])

    def test_tiny_lambda_coefficient_is_not_cancelled(self):
        c = coefficient("1e-30")
        self.assertGreater(c, Decimal("5e-61"))
        self.assertLess(c, Decimal("5.000000000000000000000000000004e-61"))
        self.assertTrue(coefficient("0.999999999999999999999999999999").is_finite())

    def test_log_p_retained_without_underflow(self):
        r = self.call([1] * 10000, lambdas=[".5"])
        self.assertLess(Decimal(r["log_p_one_sided"]), -1000)
        self.assertFalse(r["confirmatory_eligible"])

    def test_one_row_extremes(self):
        for x in [-1, 0, 1]:
            r = self.call([x])
            self.assertEqual(r["ci_two_sided"], ["-1", "1"])
            self.assertGreaterEqual(Decimal(r["log_p_one_sided"]), Decimal(".05").ln())

    def test_reject_invalid_inputs_and_n(self):
        cases = [dict(expected_n=0), dict(expected_n=True), dict(expected_n=2),
                 dict(lower=1), dict(center=2), dict(null_mean=2), dict(alpha=0),
                 dict(alpha=1), dict(alpha="nan"), dict(lambdas=[]),
                 dict(lambdas=[".1", ".10"]), dict(lambdas=[0]), dict(lambdas=[1]),
                 dict(lambdas=["1e-31"]), dict(center="Infinity")]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call([0], **changes)
        for values in [[], [2], [float("nan")], [True], ["bad"]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.call(values)

    def test_paired_hits_share_one_null_and_validate_binary(self):
        opts = dict(lambdas=[".2"], alpha=".05", null_difference=0, expected_n=4)
        r = paired_hits([1, 0, 1, 0], [1, 1, 0, 0], **opts)
        self.assertEqual(Decimal(r["normalized_squared_residual_sum"]), Decimal(".5"))
        for model, null in [([1], [0, 0]), ([True]*4, [0]*4), ([2]*4, [0]*4)]:
            with self.assertRaises(ValueError):
                paired_hits(model, null, **opts)

    def test_marginal_center_is_not_null_threshold(self):
        data = [1, 0, 0, 0]
        opts = dict(p0=".1", lambdas=[".2"], alpha=".05", expected_n=4)
        a = fair_baseline_hits(data, null_increment=0, **opts)
        b = fair_baseline_hits(data, null_increment=".01", **opts)
        self.assertEqual(Decimal(a["normalized_squared_residual_sum"]), Decimal(".84"))
        self.assertEqual(a["normalized_squared_residual_sum"], b["normalized_squared_residual_sum"])
        self.assertEqual(b["null_mean"], "0.11")
        with self.assertRaises(ValueError):
            fair_baseline_hits([True], p0=".1", lambdas=[".2"], alpha=".05", null_increment=0, expected_n=1)

    def test_holm_known_family_and_arbitrary_input_order(self):
        with localcontext() as ctx:
            ctx.prec = 80
            raw = {k: Decimal(v).ln() for k, v in {"a": ".01", "b": ".04", "c": ".03"}.items()}
            adjusted = holm_log_pvalues(raw)
            for k, expected in {"a": ".03", "b": ".06", "c": ".06"}.items():
                self.assertLess(abs(Decimal(adjusted[k]).exp()-Decimal(expected)), Decimal("1e-75"))
            self.assertEqual(adjusted, holm_log_pvalues(dict(reversed(list(raw.items())))))
            self.assertEqual(intersection_union(raw["a"], raw["b"]), raw["b"])
        for bad in [{}, {"a": ".1"}, {"a": "nan"}]:
            with self.assertRaises(ValueError):
                holm_log_pvalues(bad)


if __name__ == "__main__":
    unittest.main()
