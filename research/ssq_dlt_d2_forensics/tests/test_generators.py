"""Finite-state generator laws and deterministic domain/integrity regressions."""
from collections import Counter
from fractions import Fraction
import itertools
import math
import random
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_forensics import generators as gen
from research.ssq_dlt_v45 import models as oldmodels


class ScriptedBelow:
    def __init__(self, values):
        self.values = iter(values)

    def randbelow(self, upper):
        value = next(self.values)
        if not 0 <= value < upper:
            raise AssertionError("script outside requested support")
        return value


class ScriptedGroup:
    def __init__(self, choice, chosen, pair):
        self.choice, self.chosen, self.pair = choice, set(chosen), set(pair)

    def randrange(self, upper):
        if not 0 <= self.choice < upper:
            raise AssertionError("script outside categorical support")
        return self.choice

    def sample(self, population, count):
        picked = [x for x in population if x in self.chosen]
        if len(picked) != count:
            raise AssertionError("script has wrong group cardinality")
        return picked


class GeneratorTests(unittest.TestCase):
    def test_partial_fisher_yates_enumerates_uniform_small_subset_law(self):
        for n in range(2, 7):
            for k in range(n + 1):
                counts = Counter()
                ranges = [range(n - i) for i in range(k)]
                for choices in itertools.product(*ranges):
                    counts[tuple(gen._fisher_yates_subset(ScriptedBelow(choices), n, k))] += 1
                expected = set(itertools.combinations(range(1, n + 1), k))
                self.assertEqual(set(counts), expected)
                self.assertEqual(set(counts.values()), {math.factorial(k)})

    def test_exact_small_weighted_group_support_law(self):
        for n, k in ((4, 2), (5, 3), (6, 2), (6, 4)):
            pair = (1, 2)
            for weights in ((1, 1, 8), (1, 3, 9)):
                masses = [math.comb(2, a) * gen._choose(n - 2, k - a) * weights[a]
                          for a in range(3)]
                normalizer = sum(masses)
                total = Fraction()
                for subset in itertools.combinations(range(1, n + 1), k):
                    a = len(set(pair).intersection(subset))
                    within = math.comb(2, a) * gen._choose(n - 2, k - a)
                    probability = Fraction(masses[a], normalizer) / within
                    self.assertEqual(probability, Fraction(weights[a], normalizer))
                    total += probability
                    for category_choice in (sum(masses[:a]), sum(masses[:a + 1]) - 1):
                        rng = ScriptedGroup(category_choice, subset, pair)
                        self.assertEqual(gen._group_weighted_subset(rng, n, k, pair, weights), list(subset))
                self.assertEqual(total, 1)

    def test_uniform_relabelling_enumeration_erases_every_latent_subset(self):
        n, k = 5, 2
        for latent in itertools.combinations(range(1, n + 1), k):
            counts = Counter(tuple(gen._relabel(list(latent), list(p)))
                             for p in itertools.permutations(range(1, n + 1)))
            self.assertEqual(len(counts), math.comb(n, k))
            self.assertEqual(set(counts.values()), {math.factorial(k) * math.factorial(n - k)})

    def test_sha256_rejection_and_bounds_have_no_modulo_truncation(self):
        rng = gen.SHA256CounterRNG(17)
        space = 1 << 256
        # 2**256 % 3 == 1: the top word is rejected, the next accepted.
        with patch.object(rng, "_word", side_effect=[space - 1, 7]) as word:
            self.assertEqual(rng.randbelow(3), 1)
            self.assertEqual(word.call_count, 2)
        with patch.object(rng, "_word", side_effect=AssertionError("must not consume")):
            self.assertEqual(rng.randbelow(1), 0)
        for bound in (2, 3, 17, 35, 1 << 256):
            for _ in range(50):
                self.assertTrue(0 <= rng.randbelow(bound) < bound)
        for invalid in (0, -1, True, 1.5, (1 << 256) + 1):
            with self.assertRaises(ValueError):
                rng.randbelow(invalid)
        first, second = gen.SHA256CounterRNG(12), gen.SHA256CounterRNG(12)
        self.assertEqual([first.randbelow(35) for _ in range(100)],
                         [second.randbelow(35) for _ in range(100)])

    def test_all_streams_are_legal_reproducible_and_have_length_invariant_prefix(self):
        for game in gen.RULES:
            for scenario in gen.SCENARIOS:
                short, metadata = gen.synthetic_history(game, scenario, 0, warmup=4, evaluation_draws=9)
                repeat, repeated_meta = gen.synthetic_history(game, scenario, 0, warmup=4, evaluation_draws=9)
                long, long_meta = gen.synthetic_history(game, scenario, 0, warmup=4, evaluation_draws=25)
                self.assertEqual(short, repeat)
                self.assertEqual(metadata, repeated_meta)
                self.assertEqual(metadata, long_meta)
                self.assertEqual(short, long[:len(short)])
                oldmodels.validate_history(game, "UNASSIGNED", long)
                expected = "UNIFORM" if scenario in gen.NEGATIVE_SCENARIOS else scenario
                self.assertEqual(metadata["law"], expected)
                self.assertEqual(metadata["root_seed"], 2026101921)

    def test_split_streams_use_separate_latent_and_per_row_permutation_domains(self):
        game, scenario, rep = "DLT", "SPLIT_SCRAMBLED_PAIR", 3
        component_seeds = {gen.stream_seed(game, scenario, rep, "LATENT_PAIR")}
        component_seeds.update(gen.stream_seed(game, scenario, rep, "PERMUTATION", i) for i in range(12))
        self.assertEqual(len(component_seeds), 13)
        reference, _ = gen.synthetic_history(game, scenario, rep, warmup=0, evaluation_draws=12)
        original_seed = gen.stream_seed

        def altered_permutation(*args, **kwargs):
            seed = original_seed(*args, **kwargs)
            return seed ^ 17 if args[3] == "PERMUTATION" else seed

        latent_before, latent_after = [], []
        group_sampler = gen._group_weighted_subset

        def capture(destination):
            def wrapped(*args, **kwargs):
                result = group_sampler(*args, **kwargs)
                destination.append(result)
                return result
            return wrapped

        with patch.object(gen, "_group_weighted_subset", side_effect=capture(latent_before)):
            again, _ = gen.synthetic_history(game, scenario, rep, warmup=0, evaluation_draws=12)
        with patch.object(gen, "stream_seed", side_effect=altered_permutation), \
                patch.object(gen, "_group_weighted_subset", side_effect=capture(latent_after)):
            changed, _ = gen.synthetic_history(game, scenario, rep, warmup=0, evaluation_draws=12)
        self.assertEqual(reference, again)
        self.assertEqual(latent_before, latent_after)
        self.assertNotEqual(reference, changed)

        permutations_before, permutations_after = [], []
        relabel = gen._relabel

        def capture_permutation(destination):
            def wrapped(front, permutation):
                destination.append(permutation)
                return relabel(front, permutation)
            return wrapped

        def altered_latent(*args, **kwargs):
            seed = original_seed(*args, **kwargs)
            return seed ^ 17 if args[3] == "LATENT_PAIR" else seed

        with patch.object(gen, "_relabel", side_effect=capture_permutation(permutations_before)):
            gen.synthetic_history(game, scenario, rep, warmup=0, evaluation_draws=12)
        with patch.object(gen, "stream_seed", side_effect=altered_latent), \
                patch.object(gen, "_relabel", side_effect=capture_permutation(permutations_after)):
            gen.synthetic_history(game, scenario, rep, warmup=0, evaluation_draws=12)
        self.assertEqual(permutations_before, permutations_after)

    def test_actual_scenario_paths_use_registered_integer_group_weights(self):
        sampler = gen._group_weighted_subset
        for scenario, weights in (("MARGINAL_STRONG", (1, 3, 9)),
                                  ("PAIR_STRONG", (1, 1, 8)),
                                  ("SPLIT_SCRAMBLED_PAIR", (1, 1, 8))):
            with patch.object(gen, "_group_weighted_subset", wraps=sampler) as observed:
                gen.synthetic_history("SSQ", scenario, 0, warmup=0, evaluation_draws=3)
                self.assertEqual(observed.call_count, 3)
                self.assertEqual([call.args[-1] for call in observed.call_args_list], [weights] * 3)

    def test_new_domain_changes_game_scenario_replication_and_component(self):
        values = set()
        for game in gen.RULES:
            for scenario in gen.SCENARIOS:
                for rep in range(3):
                    for component in ("FRONT", "LATENT_PAIR", "PERMUTATION", "FIXED_RING"):
                        values.add(gen.stream_seed(game, scenario, rep, component))
        self.assertEqual(len(values), 2 * len(gen.SCENARIOS) * 3 * 4)
        self.assertNotEqual(gen.DOMAIN, "SCRAMBLED_PAIR_STRONG")
        for args in (("BAD", "MT_DIRECT", 0, "FRONT"),
                     ("DLT", "BAD", 0, "FRONT"),
                     ("DLT", "MT_DIRECT", True, "FRONT")):
            with self.assertRaises(ValueError):
                gen.stream_seed(*args)

    def test_ring_mixture_has_uniform_marginals_and_nonuniform_joint_law(self):
        n, k = 7, 3
        ring = [4, 1, 7, 2, 5, 3, 6]
        arcs = [set(ring[(start + j) % n] for j in range(k)) for start in range(n)]
        self.assertEqual({sum(x in arc for arc in arcs) for x in ring}, {k})
        pair_counts = {pair: sum(set(pair) <= arc for arc in arcs)
                       for pair in itertools.combinations(ring, 2)}
        self.assertEqual(max(pair_counts.values()), k - 1)
        self.assertGreater(len(set(pair_counts.values())), 1)
        rows, meta = gen.synthetic_history("SSQ", "RING_PERSISTENT", 0,
                                            warmup=0, evaluation_draws=10)
        self.assertEqual(sorted(meta["ring"]), list(range(1, 34)))
        self.assertEqual(meta["rho"], .25)
        self.assertEqual(len(rows), 10)

    def test_legacy_shared_scramble_follows_original_rng_consumption_on_new_seed(self):
        from research.ssq_dlt_d2_next import simulation as original_simulation
        original_spec = dict(original_simulation.SPEC)
        for game in gen.RULES:
            scenario, replication = "LEGACY_SHARED_SCRAMBLE", 2
            rows, metadata = gen.synthetic_history(game, scenario, replication,
                                                    warmup=0, evaluation_draws=17)
            n, k, _, _ = gen.RULES[game]
            new_seed = gen.stream_seed(game, scenario, replication, "FRONT")
            self.assertNotEqual(new_seed, original_simulation.stream_seed(game, "SCRAMBLED_PAIR_STRONG", replication))
            rng = random.Random(new_seed)
            rng.sample(range(1, n + 1), n)  # Original unused initialization.
            expected = []
            for _ in rows:
                latent = original_simulation.tilted_uniform(rng, n, k, [1, 2], 8)
                permutation = rng.sample(range(1, n + 1), n)
                expected.append(sorted(permutation[number - 1] for number in latent))
            self.assertEqual([row["front"] for row in rows], expected)
            self.assertTrue(metadata["legacy_shared_rng"])
            self.assertTrue(metadata["legacy_initial_unused_ring_sample"])
            self.assertEqual(metadata["law"], "UNIFORM")
        self.assertEqual(original_simulation.SPEC, original_spec)


if __name__ == "__main__":
    unittest.main()
