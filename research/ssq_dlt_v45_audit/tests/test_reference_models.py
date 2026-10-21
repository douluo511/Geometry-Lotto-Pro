"""Synthetic and exhaustive contracts only; never open historical datasets."""
from copy import deepcopy
from datetime import date, timedelta
from itertools import combinations
from math import comb
import unittest

from research.ssq_dlt_v45_audit.reference_models import (
    MODEL_PARAMETERS, MODELS, ModelInputError, reference_distribution,
    weighted_subset_probabilities,
)


def history(game="SSQ", count=12):
    upper, drawn = (33, 6) if game == "SSQ" else (35, 5)
    return [{"game": game,
             "issue": str(2026001 + i) if game == "SSQ" else str(26001 + i),
             "date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
             "front": sorted({((i + j) % upper) + 1 for j in range(drawn)})}
            for i in range(count)]


def target(game):
    return "2026999" if game == "SSQ" else "26999"


class ExactDistributionTests(unittest.TestCase):
    def test_weighted_distribution_matches_exhaustive_subsets(self):
        weights = [0.25, 0.5, 1.0, 1.5, 3.0, 2.0]
        drawn = 3
        subsets = list(combinations(range(len(weights)), drawn))
        masses = []
        for subset in subsets:
            value = 1.0
            for n in subset:
                value *= weights[n]
            masses.append(value)
        z = sum(masses)
        singles, pairs = weighted_subset_probabilities(weights, drawn)
        for n, actual in enumerate(singles):
            expected = sum(w for s, w in zip(subsets, masses) if n in s) / z
            self.assertAlmostEqual(actual, expected, places=12)
        for pair, actual in zip(combinations(range(len(weights)), 2), pairs):
            expected = sum(w for s, w in zip(subsets, masses)
                           if set(pair) <= set(s)) / z
            self.assertAlmostEqual(actual, expected, places=12)

    def test_uniform_small_population_matches_enumerated_null(self):
        for upper in range(3, 9):
            for drawn in range(2, upper + 1):
                singles, pairs = weighted_subset_probabilities([1.0] * upper, drawn)
                self.assertTrue(all(abs(p - drawn / upper) < 1e-12 for p in singles))
                p0 = comb(drawn, 2) / comb(upper, 2)
                self.assertTrue(all(abs(p - p0) < 1e-12 for p in pairs))

    def test_common_scale_does_not_change_distribution(self):
        _, first = weighted_subset_probabilities([1, 2, 4, 8, 16], 3)
        _, second = weighted_subset_probabilities([0.01, 0.02, 0.04, 0.08, 0.16], 3)
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, places=12)

    def test_invalid_distribution_refused(self):
        for weights, drawn in [([1, 0, 2], 2), ([1, -1, 2], 2),
                               ([1, float("nan"), 2], 2), ([True, 1, 2], 2),
                               ([1, 2], 1), ([1, 2], True), ([1, 2], 3)]:
            with self.subTest(weights=weights, drawn=drawn), self.assertRaises(ModelInputError):
                weighted_subset_probabilities(weights, drawn)


class ModelContractTests(unittest.TestCase):
    def test_all_references_have_coherent_mass_and_generate_no_candidates(self):
        for game, upper, drawn in [("SSQ", 33, 6), ("DLT", 35, 5)]:
            for model in MODELS:
                with self.subTest(game=game, model=model):
                    result = reference_distribution(game, target(game), history(game), model)
                    probabilities = result["pair_probabilities"]
                    self.assertEqual(len(probabilities), comb(upper, 2))
                    self.assertTrue(all(0 <= p <= 1 for p in probabilities))
                    self.assertAlmostEqual(sum(probabilities), comb(drawn, 2), places=9)
                    self.assertAlmostEqual(sum(result["single_probabilities"]), drawn, places=9)
                    self.assertEqual(result["scope"], "MATHEMATICAL_REFERENCE_ONLY")
                    self.assertEqual(result["active_new_primary_challengers"], 0)
                    self.assertEqual(result["formal_A_samples"], 0)
                    self.assertEqual(result["decision"], "NO_EDGE")
                    self.assertFalse(result["asof_verified"])
                    self.assertNotIn("dans", result)
                    self.assertEqual(result["candidate_generation"], "NOT_IMPLEMENTED_REFERENCE_ONLY")

    def test_empty_prefix_is_uniform_for_every_model(self):
        for game, upper, drawn in [("SSQ", 33, 6), ("DLT", 35, 5)]:
            expected = comb(drawn, 2) / comb(upper, 2)
            for model in MODELS:
                p = reference_distribution(game, target(game), [], model)["pair_probabilities"]
                self.assertTrue(all(abs(value - expected) < 1e-12 for value in p))

    def test_null_probabilities_do_not_use_history(self):
        first = reference_distribution("SSQ", "2026999", [], "Random NULL")
        second = reference_distribution("SSQ", "2026999", history(), "Random NULL")
        self.assertEqual(first["pair_probabilities"], second["pair_probabilities"])
        self.assertAlmostEqual(first["pair_probabilities"][0], 15 / 528, places=15)

    def test_null_call_order_game_issue_reproducibility(self):
        first = reference_distribution("SSQ", "2026999", [], "Random NULL")
        reference_distribution("DLT", "26999", [], "Random NULL")
        reference_distribution("SSQ", "2026998", [], "Random NULL")
        again = reference_distribution("SSQ", "2026999", [], "Random NULL")
        self.assertEqual(first, again)

    def test_predictions_do_not_mutate_or_retain_input(self):
        rows = history()
        original = deepcopy(rows)
        params = deepcopy(MODEL_PARAMETERS["Hot60"])
        result = reference_distribution("SSQ", "2026999", rows, "Hot60", params)
        self.assertEqual(rows, original)
        self.assertEqual(params, MODEL_PARAMETERS["Hot60"])
        rows[0]["front"][0] = 33
        result["parameters"]["window"] = -1
        self.assertEqual(MODEL_PARAMETERS["Hot60"]["window"], 60)

    def test_input_order_does_not_change_prediction(self):
        rows = history()
        first = reference_distribution("SSQ", "2026999", rows, "EWMA")
        second = reference_distribution("SSQ", "2026999", list(reversed(rows)), "EWMA")
        self.assertEqual(first, second)

    def test_irrelevant_metadata_not_used_as_predictive_feature(self):
        rows = history()
        metadata = deepcopy(rows)
        for row in metadata:
            row["winning_future"] = [31, 32, 33]
            row["untrusted_model_score"] = 999
        self.assertEqual(reference_distribution("SSQ", "2026999", rows, "Hot60"),
                         reference_distribution("SSQ", "2026999", metadata, "Hot60"))

    def test_fixed_window_ignores_earlier_balls_not_prefix_guard(self):
        rows = history(count=70)
        changed = deepcopy(rows)
        for row in changed[:10]:
            row["front"] = [1, 3, 5, 7, 9, 11]
        for model in ("Hot60", "ShrinkMix", "Pairwise-D2"):
            a = reference_distribution("SSQ", "2026999", rows, model)
            b = reference_distribution("SSQ", "2026999", changed, model)
            self.assertEqual(a["pair_probabilities"], b["pair_probabilities"])
            self.assertNotEqual(a["prefix_sha256"], b["prefix_sha256"])

    def test_shrinkmix_matches_declared_convex_mixture(self):
        hot = reference_distribution("SSQ", "2026999", history(), "Hot60")
        shrink = reference_distribution("SSQ", "2026999", history(), "ShrinkMix")
        p0 = 15 / 528
        for a, b in zip(hot["pair_probabilities"], shrink["pair_probabilities"]):
            self.assertAlmostEqual(b, 0.5 * p0 + 0.5 * a, places=15)

    def test_pairwise_matches_empirical_subset_mixture(self):
        rows = history(count=1)
        result = reference_distribution("SSQ", "2026999", rows, "Pairwise-D2")
        for pair, actual in zip(combinations(range(1, 34), 2), result["pair_probabilities"]):
            expected = (20 * 15 / 528 + int(set(pair) <= set(rows[0]["front"]))) / 21
            self.assertAlmostEqual(actual, expected, places=15)

    def test_pairwise_non_equivalence_under_balanced_cooccurrence(self):
        # Each ball appears six times. Hot60 has no marginal signal while
        # same-group pairs co-occur. This planted mechanism is not actual data.
        rows = []
        for group in range(3):
            for rotation in range(11):
                rows.append({"game": "SSQ", "issue": str(2026001 + len(rows)),
                             "date": (date(2026, 1, 1) + timedelta(days=len(rows))).isoformat(),
                             "front": sorted(group * 11 + (rotation + j) % 11 + 1
                                             for j in range(6))})
        hot = reference_distribution("SSQ", "2026999", rows, "Hot60")
        pairwise = reference_distribution("SSQ", "2026999", rows, "Pairwise-D2")
        p0 = 15 / 528
        self.assertTrue(all(abs(p - p0) < 1e-12 for p in hot["pair_probabilities"]))
        pairs = list(combinations(range(1, 34), 2))
        self.assertGreater(pairwise["pair_probabilities"][pairs.index((1, 2))], p0)
        self.assertLess(pairwise["pair_probabilities"][pairs.index((1, 12))], p0)


class LeakageRejectionTests(unittest.TestCase):
    def test_future_and_target_row_never_silently_truncated(self):
        for future_issue in ["2026999", "2027001"]:
            rows = history()
            rows[0]["issue"] = future_issue
            with self.assertRaisesRegex(ModelInputError, "FUTURE"):
                reference_distribution("SSQ", "2026999", rows, "Hot60")

    def test_duplicate_issue_rejected(self):
        rows = history()
        rows.append(deepcopy(rows[0]))
        with self.assertRaisesRegex(ModelInputError, "DUPLICATE"):
            reference_distribution("SSQ", "2026999", rows, "Hot60")

    def test_cross_game_rejected(self):
        with self.assertRaisesRegex(ModelInputError, "CROSS_GAME"):
            reference_distribution("SSQ", "2026999", history("DLT"), "Hot60")

    def test_target_deadline_requires_prior_day_and_timezone(self):
        rows = history(count=1)
        with self.assertRaisesRegex(ModelInputError, "HISTORY_NOT_BEFORE"):
            reference_distribution("SSQ", "2026999", rows, "Hot60", target_deadline="2026-01-01T23:59:59+08:00")
        with self.assertRaisesRegex(ModelInputError, "TIMEZONE"):
            reference_distribution("SSQ", "2026999", rows, "Hot60", target_deadline="2026-01-02T00:00:00")
        result = reference_distribution("SSQ", "2026999", rows, "Hot60", target_deadline="2026-01-02T00:00:00+08:00")
        self.assertFalse(result["asof_verified"])
        self.assertEqual(result["deadline_scope"], "DATE_AND_ISSUE_PREFIX_ONLY")

    def test_malformed_number_date_and_issue_rejected(self):
        for value in [[1, 1, 2, 3, 4, 5], [True, 2, 3, 4, 5, 6],
                      [1, 2, 3, 4, 5, 34], [1, 2, 3, 4, 5]]:
            rows = history(count=1)
            rows[0]["front"] = value
            with self.subTest(value=value), self.assertRaises(ModelInputError):
                reference_distribution("SSQ", "2026999", rows, "EWMA")
        for field, value in [("date", "2026-02-30"), ("date", "20260101"),
                             ("issue", "２０２６００１"), ("issue", "1")]:
            rows = history(count=1)
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ModelInputError):
                reference_distribution("SSQ", "2026999", rows, "EWMA")

    def test_nonmonotonic_date_rejected(self):
        rows = history(count=2)
        rows[0]["date"] = "2026-01-03"
        with self.assertRaisesRegex(ModelInputError, "NONMONOTONIC"):
            reference_distribution("SSQ", "2026999", rows, "Hot60")

    def test_unregistered_parameters_and_unknown_model_rejected(self):
        with self.assertRaisesRegex(ModelInputError, "PREREGISTRATION"):
            reference_distribution("SSQ", "2026999", [], "Hot60", {"window": 61, "prior_draws": 10})
        with self.assertRaisesRegex(ModelInputError, "UNKNOWN_RESEARCH"):
            reference_distribution("SSQ", "2026999", [], "HighestBacktestWinner")
        with self.assertRaisesRegex(ModelInputError, "UNKNOWN_GAME"):
            reference_distribution("Other", "2026999", [], "Hot60")


if __name__ == "__main__":
    unittest.main()
