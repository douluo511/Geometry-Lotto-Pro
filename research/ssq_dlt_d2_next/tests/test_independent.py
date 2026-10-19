"""Adversarial independent finite-state checks; synthetic inputs only."""
import copy
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import combinations
import math
import random
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_next import models, simulation
from research.ssq_dlt_v45 import models as oldmodels


def exact_law(weights, k):
    masses = {tuple(i + 1 for i in subset): math.prod(weights[i] for i in subset)
              for subset in combinations(range(len(weights)), k)}
    total = sum(masses.values())
    return {subset: mass / total for subset, mass in masses.items()}


def joint_from_law(law, n):
    return {pair: sum(mass for subset, mass in law.items() if set(pair) <= set(subset))
            for pair in combinations(range(1, n + 1), 2)}


def small_history(seed=457, size=240):
    rng = random.Random(seed)
    return [dict(game="SSQ", issue=f"{index + 1:07d}",
                 front=sorted(rng.sample(range(1, 7), 3)), back=[1])
            for index in range(size)]


SMALL_RULES = {"SSQ": (6, 3, 3, 1)}


class IndependentJointLawTests(unittest.TestCase):
    def test_all_small_cardinalities_against_exact_rational_subset_masses(self):
        for n in range(2, 9):
            weights = [Fraction((13 * i + 7) % 19 + 1, (5 * i + 3) % 11 + 1)
                       for i in range(n)]
            for k in range(n + 1):
                law = exact_law(weights, k)
                expected = joint_from_law(law, n)
                actual = models.conditional_pair_probabilities(list(map(float, weights)), k)
                for pair in expected:
                    self.assertLessEqual(abs(actual[pair] - float(expected[pair])), 2e-10,
                                         msg=str((n, k, pair)))

    def test_subnormal_normalizer_cannot_pass_only_total_pair_mass_check(self):
        # A positive subnormal normalizer rounds the two last alternatives into
        # a false 0/1 law while preserving total mass exactly. The independent
        # Decimal enumeration keeps both alternatives and requires a fallback.
        weights = [3.3688753701734176e-278, 2.1008280360162472e-254,
                   1.0207488599092183e169, 1.7991755468883943e104,
                   1.1086850155736066e-270, 8.599274466106212e202,
                   6865825761.018712, 1293829365910.6152]
        with localcontext() as context:
            context.prec = 180
            law = exact_law([Decimal(str(weight)) for weight in weights], 4)
            expected = joint_from_law(law, len(weights))
        actual = models.conditional_pair_probabilities(weights, 4)
        for pair in expected:
            self.assertAlmostEqual(actual[pair], float(expected[pair]), places=10,
                                   msg=str(pair))

    def test_sampler_threshold_paths_match_an_independently_enumerated_law(self):
        weights = [Fraction(1, 3), Fraction(4, 5), Fraction(7, 4),
                   Fraction(2, 1), Fraction(5, 7), Fraction(9, 5)]
        law = exact_law(weights, 3)

        class ThresholdPath:
            def __init__(self, wanted):
                self.wanted, self.decisions, self.position = set(wanted), {}, 1

            def random(self):
                support = {subset: mass for subset, mass in law.items()
                           if all((number in subset) == included
                                  for number, included in self.decisions.items())}
                p = float(sum(mass for subset, mass in support.items()
                              if self.position in subset) / sum(support.values()))
                include = self.position in self.wanted
                self.decisions[self.position] = include
                self.position += 1
                return p / 2 if include else p + (1 - p) / 2

        for wanted in law:
            self.assertEqual(models.sample_conditional(list(map(float, weights)), 3,
                                                      ThresholdPath(wanted)), list(wanted))

    def test_unequal_weight_exchange_ranking_and_label_equivariance(self):
        weights = [0.11, 2.9, 0.37, 7.3, 1.7, 0.83]
        q = models.conditional_pair_probabilities(weights, 3)
        top = tuple(sorted(sorted(range(1, 7), key=lambda i: -weights[i - 1])[:2]))
        self.assertEqual(max(q, key=q.get), top)
        for anchor in range(1, 7):
            ordered = sorted((i for i in range(1, 7) if i != anchor),
                             key=lambda i: -weights[i - 1])
            values = [q[tuple(sorted((anchor, i)))] for i in ordered]
            self.assertTrue(all(a > b for a, b in zip(values, values[1:])))
        permutation = [4, 1, 6, 3, 2, 5]
        permuted = [0.0] * 6
        for i, new_label in enumerate(permutation):
            permuted[new_label - 1] = weights[i]
        qp = models.conditional_pair_probabilities(permuted, 3)
        for pair, value in q.items():
            mapped = tuple(sorted(permutation[i - 1] for i in pair))
            self.assertAlmostEqual(value, qp[mapped], places=12)


class IndependentCandidateAndScoringTests(unittest.TestCase):
    def test_cbpair_is_a_realizable_mixture_and_brier_is_draw_level_proper(self):
        supplied = small_history()
        with patch.object(oldmodels, "RULES", SMALL_RULES):
            actual = models.predict_candidates("SSQ", supplied)[models.MODEL_IDS[0]]
        counts = Counter(number for row in supplied for number in row["front"])
        # Fraction arithmetic and subset enumeration are independent of the
        # elementary symmetric polynomial implementation under inspection.
        p = [(Fraction(counts[i]) + 100) / 440 for i in range(1, 7)]
        weights = [probability / (1 - probability) for probability in p]
        prior = exact_law(weights, 3)
        empirical = Counter(tuple(row["front"]) for row in supplied[-60:])
        mixture = {subset: (empirical[subset] + 200 * mass) / 260
                   for subset, mass in prior.items()}
        self.assertEqual(sum(mixture.values()), 1)
        expected = joint_from_law(mixture, 6)
        q = actual["pair_probabilities"]
        for pair, value in expected.items():
            self.assertAlmostEqual(q[pair], float(value), places=12)
        self.assertTrue(actual["diagnostics"]["score_is_probability"])
        all_pairs = tuple(combinations(range(1, 7), 2))
        uniform = {pair: 0.2 for pair in all_pairs}
        risks = [0.0, 0.0]
        for subset, mass in mixture.items():
            indicators = {pair: int(set(pair) <= set(subset)) for pair in all_pairs}
            direct = sum((q[pair] - indicators[pair]) ** 2 for pair in all_pairs) / 15
            self.assertAlmostEqual(simulation.pair_brier(q, list(subset), 6, 3), direct, places=13)
            self.assertAlmostEqual(simulation.pair_brier(uniform, list(subset), 6, 3), 0.16,
                                   places=13)
            risks[0] += float(mass) * direct
            risks[1] += float(mass) * simulation.pair_brier(uniform, list(subset), 6, 3)
        excess = sum((q[pair] - uniform[pair]) ** 2 for pair in all_pairs) / 15
        self.assertAlmostEqual(risks[1] - risks[0], excess, places=13)

    def test_replicated_pair_shared_prior_couples_the_two_block_residuals(self):
        supplied = [dict(game="SSQ", issue=f"{i + 1:07d}",
                         front=[4, 5, 6] if i < 120 else [1, 2, 3], back=[1])
                    for i in range(240)]
        altered = copy.deepcopy(supplied)
        for row in altered[:120]:
            row["front"] = [1, 2, 3]
        # Both evaluation blocks are byte-identical. Only their jointly fitted
        # baseline changes. Both nominal residuals therefore change together.
        self.assertEqual(supplied[-120:], altered[-120:])
        with patch.object(oldmodels, "RULES", SMALL_RULES):
            left = models.predict_candidates("SSQ", supplied)[models.MODEL_IDS[1]]
            right = models.predict_candidates("SSQ", altered)[models.MODEL_IDS[1]]
        self.assertEqual(left["d2"], [1, 2])
        self.assertEqual(right["d2"], [1, 2])
        self.assertEqual(left["diagnostics"]["recent_pair_count"], 60)
        self.assertEqual(left["diagnostics"]["previous_pair_count"], 60)
        self.assertNotEqual(left["diagnostics"]["prior_joint_probability"],
                            right["diagnostics"]["prior_joint_probability"])
        self.assertNotEqual(left["diagnostics"]["score"], right["diagnostics"]["score"])
        self.assertIn("not a normal test or independent replication",
                      models.registry()["residual_calibration"])
        self.assertFalse(left["diagnostics"]["score_is_probability"])

    def test_control_predictions_are_committed_to_prefix_before_scoring_target(self):
        supplied = {}
        for game, (n, k, _, back_count) in oldmodels.RULES.items():
            rng = random.Random(8450 + n)
            supplied[game] = [dict(game=game, issue=f"{i + 1:07d}",
                                   front=sorted(rng.sample(range(1, n + 1), k)),
                                   back=list(range(1, back_count + 1))) for i in range(243)]
        real_predict, real_hit = models.predict_candidates, simulation.full_hit
        spec = dict(simulation.SPEC, scenarios=["FAIR"], replications=1,
                    warmup=240, evaluation_draws=3)

        def run(data):
            calls, pending = [], {"predicted": False}

            def generator(game, scenario, replication):
                return copy.deepcopy(data[game]), [[1, 2]] * 243

            def predictor(game, prefix):
                self.assertEqual(prefix, data[game][:len(prefix)])
                self.assertTrue(240 <= len(prefix) < 243)
                result = real_predict(game, prefix)
                pending["predicted"] = True
                calls.append((game, len(prefix), copy.deepcopy(result)))
                return result

            def scorer(pair, front):
                self.assertTrue(pending["predicted"], "target was scored before prediction")
                return real_hit(pair, front)

            with patch.object(simulation, "SPEC", spec), \
                    patch.object(simulation, "synthetic_history", generator), \
                    patch.object(models, "predict_candidates", predictor), \
                    patch.object(simulation, "full_hit", scorer):
                output = simulation.run_controls()
            return calls, output

        first_calls, first = run(supplied)
        altered = copy.deepcopy(supplied)
        for game, (n, k, _, _) in oldmodels.RULES.items():
            for row in altered[game][240:]:
                row["front"] = list(range(n - k + 1, n + 1))
        second_calls, second = run(altered)
        self.assertEqual(len(first_calls), 6)
        for game in oldmodels.RULES:
            left = next(c for c in first_calls if c[:2] == (game, 240))
            right = next(c for c in second_calls if c[:2] == (game, 240))
            self.assertEqual(left[2], right[2], "target/future mutation affected prior forecast")
            before = next(r for r in first["periods"] if r["game"] == game and r["index"] == 240)
            after = next(r for r in second["periods"] if r["game"] == game and r["index"] == 240)
            self.assertEqual(before["predictions"], after["predictions"])
        self.assertTrue(all(r["training_end"] == r["index"] - 1 for r in first["periods"]))


class IndependentGeneratorTests(unittest.TestCase):
    def test_ring_has_uniform_marginals_but_exact_nonuniform_pair_interactions(self):
        for n, k in ((7, 3), (33, 6), (35, 5)):
            ring = list(range(1, n + 1))
            arcs = [tuple(sorted(ring[(start + j) % n] for j in range(k)))
                    for start in range(n)]
            for number in ring:
                self.assertEqual(sum(number in arc for arc in arcs), k)
            pair_counts = {pair: sum(set(pair) <= set(arc) for arc in arcs)
                           for pair in combinations(ring, 2)}
            p0, rho = Fraction(k * (k - 1), n * (n - 1)), Fraction(1, 4)
            mixture = {pair: (1 - rho) * p0 + rho * Fraction(count, n)
                       for pair, count in pair_counts.items()}
            self.assertEqual(sum(mixture.values()), math.comb(k, 2))
            self.assertEqual(mixture[1, 2], (1 - rho) * p0 + rho * Fraction(k - 1, n))
            self.assertGreater(mixture[1, 2], p0)
            self.assertLess(mixture[1, k + 1], p0)
            # There are n equally favoured adjacent pairs, not one latent pair.
            self.assertEqual(sum(value == max(mixture.values()) for value in mixture.values()), n)

    def test_actual_persistent_and_scrambled_ring_sampling_control_flow(self):
        class ScriptedRingRng:
            def __init__(self):
                self.full_ring_calls, self.start = 0, -1

            def sample(self, population, count):
                self.asserted_population = tuple(population)
                if count != 6:
                    raise AssertionError("uniform branch was unexpectedly selected")
                self.full_ring_calls += 1
                return [3, 1, 6, 2, 5, 4]

            def random(self):
                return 0.0  # Every tested draw takes the registered ring branch.

            def randrange(self, n):
                if n != 6:
                    raise AssertionError("unexpected ring size")
                self.start += 1
                return self.start % n

        spec = dict(simulation.SPEC, warmup=0, evaluation_draws=6, replications=1)
        expected_arcs = [tuple(sorted([3, 1, 6, 2, 5, 4][(start + j) % 6]
                                      for j in range(3))) for start in range(6)]
        for scenario in ("RING_PERSISTENT", "RING_SCRAMBLED"):
            rng = ScriptedRingRng()
            with patch.object(oldmodels, "RULES", SMALL_RULES), \
                    patch.object(simulation, "SPEC", spec), \
                    patch.object(simulation.random, "Random", lambda seed: rng):
                rows, references = simulation.synthetic_history("SSQ", scenario, 0)
            self.assertEqual([tuple(row["front"]) for row in rows], expected_arcs)
            self.assertEqual(rng.full_ring_calls, 1 if scenario == "RING_PERSISTENT" else 7)
            self.assertEqual(references, [[1, 3] if scenario == "RING_PERSISTENT" else [1, 2]] * 6)

    def test_tilted_uniform_obeys_complete_small_support_distribution(self):
        rng, trials, ratio = random.Random(842155), 30000, 7.0
        counts = Counter(tuple(simulation.tilted_uniform(rng, 6, 3, [1, 2], ratio))
                         for _ in range(trials))
        support = tuple(combinations(range(1, 7), 3))
        self.assertEqual(set(counts), set(support))
        for subset in support:
            probability = (ratio if {1, 2} <= set(subset) else 1.0) / 44
            standard_error = math.sqrt(probability * (1 - probability) / trials)
            self.assertLess(abs(counts[subset] / trials - probability),
                            6 * standard_error + 1 / trials)

    def test_label_scramble_is_exactly_fair_and_destroys_a_persistent_pair(self):
        # Enumerate the permutation law independently: each fixed k-subset has
        # k!*(n-k)! label permutations mapping it to every other k-subset.
        from itertools import permutations
        n, k = 5, 2
        support = tuple(combinations(range(1, n + 1), k))
        original = {subset: Fraction(8 if subset == (1, 2) else 1, 17)
                    for subset in support}
        output = Counter()
        for subset, mass in original.items():
            for permutation in permutations(range(1, n + 1)):
                mapped = tuple(sorted(permutation[number - 1] for number in subset))
                output[mapped] += mass / math.factorial(n)
        self.assertEqual(sum(output.values()), 1)
        self.assertTrue(all(value == Fraction(1, 10) for value in output.values()))


if __name__ == "__main__":
    unittest.main()
