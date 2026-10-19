"""Independent finite-state identities and synthetic-only candidate checks."""
import copy
import itertools
import math
import random
import unittest

from research.ssq_dlt_d2_next import models
from research.ssq_dlt_v45 import models as oldmodels


def history(game="SSQ", size=300, seed=7301):
    rng = random.Random(seed)
    upper, count, back_upper, back_count = oldmodels.RULES[game]
    return [{"game": game, "issue": str(2000001 + i),
             "front": rng.sample(range(1, upper + 1), count),
             "back": rng.sample(range(1, back_upper + 1), back_count)}
            for i in range(size)]


def brute(weights, k):
    subsets = list(itertools.combinations(range(len(weights)), k))
    masses = {s: math.prod(weights[i] for i in s) for s in subsets}
    z = math.fsum(masses.values())
    return {(i + 1, j + 1): math.fsum(value for s, value in masses.items() if i in s and j in s) / z
            for i, j in itertools.combinations(range(len(weights)), 2)}


class ConditionalPairTest(unittest.TestCase):
    def test_uniform_matches_exact_baseline_and_pair_mass(self):
        for n, k in ((33, 6), (35, 5), (8, 3)):
            actual = models.conditional_pair_probabilities([1.0] * n, k)
            expected = math.comb(k, 2) / math.comb(n, 2)
            self.assertTrue(all(abs(q - expected) < 1e-12 for q in actual.values()))
            self.assertAlmostEqual(math.fsum(actual.values()), math.comb(k, 2), places=10)

    def test_every_joint_matches_independent_n8k3_enumeration(self):
        for weights in ([.1, .3, .5, .7, .9, 1.1, 1.3, 1.7],
                        [2.0, .1, 5.0, .7, 3.0, 1.0, .2, 4.0]):
            actual = models.conditional_pair_probabilities(list(weights), 3)
            expected = brute(weights, 3)
            for pair, probability in expected.items():
                self.assertAlmostEqual(actual[pair], probability, places=12, msg=str(pair))
            # Fixed-k degree identity is stronger than total pair mass.
            subsets = list(itertools.combinations(range(8), 3))
            z = math.fsum(math.prod(weights[i] for i in s) for s in subsets)
            for i in range(8):
                marginal = math.fsum(math.prod(weights[a] for a in s) for s in subsets if i in s) / z
                degree = math.fsum(q for pair, q in actual.items() if i + 1 in pair)
                self.assertAlmostEqual(degree, 2 * marginal, places=12)

    def test_top_two_and_exchange_identity(self):
        weights = [.7, 2.3, .2, 1.1, 3.5, 1.7, .4, 1.3]
        k = 3
        q = models.conditional_pair_probabilities(weights, k)
        self.assertEqual(max(q, key=q.get), (2, 5))
        z = math.fsum(math.prod(weights[i] for i in s) for s in itertools.combinations(range(8), k))
        a, b, j = 4, 2, 7
        rest = [weights[i - 1] for i in range(1, 9) if i not in (a, b, j)]
        e = math.fsum(math.prod(s) for s in itertools.combinations(rest, k - 2))
        delta = weights[j - 1] * (weights[a - 1] - weights[b - 1]) * e / z
        self.assertAlmostEqual(q[tuple(sorted((a, j)))] - q[tuple(sorted((b, j)))], delta, places=12)

    def test_scale_invariance_boundaries_and_extreme_positive_dp_fallback(self):
        weights = [.1, .5, 2.0, 8.0, 1.7, .3, .8, 4.0]
        q = models.conditional_pair_probabilities(weights, 3)
        for scale in (1e-100, 1e100):
            scaled = models.conditional_pair_probabilities([w * scale for w in weights], 3)
            for pair in q:
                self.assertAlmostEqual(q[pair], scaled[pair], places=12)
        for k, expected in ((0, 0), (1, 0), (8, 1)):
            self.assertTrue(all(q == expected for q in models.conditional_pair_probabilities(weights, k).values()))
        extreme = models.conditional_pair_probabilities([1e-300] * 6 + [1e300] * 2, 3)
        self.assertAlmostEqual(math.fsum(extreme.values()), 3, places=9)
        self.assertAlmostEqual(extreme[7, 8], 1.0, places=9)
        for bad, k in (([1.0, 0.0], 1), ([1.0, float("nan")], 1), ([True, 1.0], 1), ([1.0, 1.0], True)):
            with self.assertRaises(ValueError):
                models.conditional_pair_probabilities(bad, k)

    def test_sampler_is_legal_reproducible_and_matches_small_distribution(self):
        weights = [.2, .8, 1.3, 2.0]
        first = random.Random(715)
        second = random.Random(715)
        self.assertEqual([models.sample_conditional(weights, 2, first) for _ in range(50)],
                         [models.sample_conditional(weights, 2, second) for _ in range(50)])
        rng = random.Random(991)
        counts = {pair: 0 for pair in itertools.combinations(range(1, 5), 2)}
        trials = 16000
        for _ in range(trials):
            sample = models.sample_conditional(weights, 2, rng)
            self.assertEqual(sorted(set(sample)), sample)
            self.assertEqual(len(sample), 2)
            counts[tuple(sample)] += 1
        expected = brute(weights, 2)
        for pair in counts:
            se = math.sqrt(expected[pair] * (1 - expected[pair]) / trials)
            self.assertLess(abs(counts[pair] / trials - expected[pair]), 6 * se + 1 / trials)


class CandidateTest(unittest.TestCase):
    def test_registry_and_parameters_are_immutable_or_fresh(self):
        with self.assertRaises(TypeError):
            models.PARAMETERS["recent_window"] = 7
        first = models.registry()
        first["parameters"]["recent_window"] = 7
        first["models"].clear()
        self.assertEqual(models.registry()["parameters"]["recent_window"], 60)
        self.assertEqual(tuple(models.registry()["models"]), models.MODEL_IDS)
        self.assertEqual(len(models.source_sha256()), 64)

    def test_validated_prefix_legal_output_and_no_mutation(self):
        for game in oldmodels.RULES:
            supplied = history(game)
            original = copy.deepcopy(supplied)
            for size in (240, 241, 259, 300):
                result = models.predict_candidates(game, supplied[:size])
                self.assertEqual(set(result), set(models.MODEL_IDS))
                n, k, _, _ = oldmodels.RULES[game]
                for candidate in result.values():
                    self.assertEqual(candidate["d2"], sorted(set(candidate["d2"])))
                    self.assertEqual(len(candidate["d2"]), 2)
                    self.assertTrue(all(1 <= i <= n for i in candidate["d2"]))
                    self.assertAlmostEqual(candidate["diagnostics"]["prior_pair_mass"], math.comb(k, 2), places=10)
                probabilities = result[models.MODEL_IDS[0]]["pair_probabilities"]
                self.assertEqual(len(probabilities), math.comb(n, 2))
                self.assertAlmostEqual(math.fsum(probabilities.values()), math.comb(k, 2), places=10)
                self.assertTrue(all(0 <= q <= 1 for q in probabilities.values()))
                # All pre-base prefix content has zero influence on the same as-of prediction.
                self.assertEqual({m: r["d2"] for m, r in result.items()},
                                 {m: r["d2"] for m, r in models.predict_candidates(game, supplied[size-240:size]).items()})
            self.assertEqual(original, supplied)
            with self.assertRaises(oldmodels.ModelBlocked):
                models.predict_candidates(game, supplied[:239])
            malformed = copy.deepcopy(supplied)
            malformed[-1]["issue"] = malformed[-2]["issue"]
            with self.assertRaises(oldmodels.ModelBlocked):
                models.predict_candidates(game, malformed)
            malformed = copy.deepcopy(supplied)
            malformed[-1]["front"][0] = malformed[-1]["front"][1]
            with self.assertRaises(oldmodels.ModelBlocked):
                models.predict_candidates(game, malformed)

    def test_exact_fixed_spec_and_different_pair_from_marginal_top_two(self):
        supplied = history("SSQ", seed=7301)
        actual = models.predict_candidates("SSQ", supplied)
        n, k = 33, 6
        base, recent, previous = supplied[-240:], supplied[-60:], supplied[-120:-60]
        counts = {i: sum(i in row["front"] for row in base) for i in range(1, n + 1)}
        p = [(counts[i] + 200 * k / n) / 440 for i in range(1, n + 1)]
        q = models.conditional_pair_probabilities([value / (1 - value) for value in p], k)
        paircounts = lambda rows, pair: sum(set(pair).issubset(row["front"]) for row in rows)
        scores = {pair: (paircounts(recent, pair) + 200 * q[pair]) / 260 for pair in q}
        z = {pair: min((paircounts(block, pair) - 60 * q[pair]) / math.sqrt(60 * q[pair] * (1-q[pair]) + 1)
                      for block in (recent, previous)) for pair in q}
        first = min(q, key=lambda pair: (-round(scores[pair], 12), -paircounts(recent, pair), -sum(counts[i] for i in pair), pair))
        top = sorted(range(1, n + 1), key=lambda i: (-counts[i], i))
        second = tuple(sorted(top[:2])) if max(z.values()) <= 0 else min(
            q, key=lambda pair: (-round(z[pair], 12), -round(scores[pair], 12), pair))
        self.assertEqual(actual[models.MODEL_IDS[0]]["d2"], list(first))
        self.assertEqual(actual[models.MODEL_IDS[1]]["d2"], list(second))
        self.assertNotEqual(list(first), sorted(top[:2]))
        self.assertGreater(actual[models.MODEL_IDS[0]]["diagnostics"]["max_abs_conditional_vs_input_marginal"], 0.0)

    def test_ties_reproducible_ascending_and_fallback(self):
        # The same fixed legal set makes all within-set pairs tied in every score.
        for game in oldmodels.RULES:
            n, k, _, back_count = oldmodels.RULES[game]
            supplied = [{"game": game, "issue": str(2000001 + i),
                         "front": list(range(1, k + 1)), "back": list(range(1, back_count + 1))}
                        for i in range(240)]
            first = models.predict_candidates(game, supplied)
            second = models.predict_candidates(game, copy.deepcopy(supplied))
            self.assertEqual(first, second)
            for candidate in first.values():
                self.assertEqual(candidate["d2"], [1, 2])
            # Two blocks with disjoint number supports have no shared positive residual.
            disjoint = [{"game": game, "issue": str(2000001 + i),
                         "front": list(range(2*k+1, 3*k+1) if i < 120 else
                                       range(k+1, 2*k+1) if i < 180 else range(1, k+1)),
                         "back": list(range(1, back_count+1))} for i in range(240)]
            fallback = models.predict_candidates(game, disjoint)[models.MODEL_IDS[1]]
            self.assertTrue(fallback["diagnostics"]["fallback_top_two_odds"])
            self.assertLessEqual(fallback["diagnostics"]["max_min_block_score"], 0)
            self.assertEqual(fallback["d2"], [2*k+1, 2*k+2])


if __name__ == "__main__":
    unittest.main()
