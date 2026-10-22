"""test6 Pairwise-D2 independent mathematical oracle (synthetic SHADOW only).

This module contains no real draw outcome or claim of predictive advantage.
It does not alter the V4.7 registered model, Random NULL or formal slots.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from itertools import combinations
import unittest

from research.harness_v46 import core
from research.harness_v46.tests.test_core import fixture


WINDOW = 120
TAU = 200


def independent_pair_components(snapshot):
    """Exact-rational oracle, intentionally independent of core._pair_scores."""
    game = snapshot["lottery"]
    pool = core.RULES[game]["pool"]
    rows = snapshot["draws"][-WINDOW:]
    if len(rows) != WINDOW:
        raise ValueError("ORACLE_REQUIRES_120")
    k = core.RULES[game]["front"]
    singles = Counter()
    together = Counter()
    for row in rows:
        balls = tuple(sorted(row["front"]))
        for ball in balls:
            singles[ball] += 1
        for a, b in combinations(balls, 2):
            together[(a, b)] += 1
    components = {}
    n = len(rows)
    for a, b in combinations(range(1, pool + 1), 2):
        marginal = Fraction(singles[a] + singles[b], n)
        expected_pair = Fraction(singles[a] * singles[b] * (k - 1), n * k)
        residual = (Fraction(together[(a, b)]) - expected_pair) / (n + TAU)
        components[(a, b)] = {
            "marginal": marginal,
            "expected": expected_pair,
            "observed": together[(a, b)],
            "residual": residual,
            "combined": marginal + residual,
        }
    return components


def exact_rank(components, key):
    return sorted(components, key=lambda p: (-components[p][key], p))


class PairwiseV47Oracle(unittest.TestCase):
    def test_registry_and_exact_120_window_for_both_games(self):
        self.assertEqual(core.PARAMETERS["pairwise_d2"],
                         {"window": WINDOW, "pair_residual_tau": TAU})
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                with self.assertRaisesRegex(core.GateError, "120"):
                    core.forecast(fixture(game, size=119), "pairwise_d2")
                p = core.forecast(fixture(game, size=120), "pairwise_d2")
                self.assertEqual(p["primary_d2"], p["candidates_1_to_5"][:2])
                self.assertEqual(len(p["parameters_sha256"]), 64)
                self.assertEqual(len(p["model_source_sha256"]), 64)
                self.assertTrue(core.validate_forecast(p, fixture(game, size=120)))

    def test_every_pair_agrees_with_independent_fraction_oracle(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = fixture(game, size=140)
                oracle = independent_pair_components(snapshot)
                implementation = core._pair_scores(
                    snapshot["draws"], core.RULES[game]["pool"], WINDOW
                )
                self.assertEqual(set(oracle), set(implementation))
                self.assertEqual(
                    len(oracle), core.RULES[game]["pool"] *
                    (core.RULES[game]["pool"] - 1) // 2
                )
                for pair, exact in oracle.items():
                    self.assertAlmostEqual(
                        implementation[pair], float(exact["combined"]),
                        places=12, msg=f"{game} {pair}"
                    )
                chosen = exact_rank(oracle, "combined")[0]
                p = core.forecast(snapshot, "pairwise_d2")
                self.assertEqual(tuple(p["primary_d2"]), chosen)
                counts60 = Counter(
                    ball for row in snapshot["draws"][-60:]
                    for ball in row["front"]
                )
                rest = sorted(
                    range(1, core.RULES[game]["pool"] + 1),
                    key=lambda ball: (-counts60[ball], ball)
                )
                expected_five = list(chosen) + [
                    ball for ball in rest if ball not in chosen
                ][:3]
                self.assertEqual(p["candidates_1_to_5"], expected_five)

    def test_old_rows_outside_window_cannot_move_pairwise_d2(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                left = fixture(game, size=160)
                right = deepcopy(left)
                r = core.RULES[game]
                opposite = list(range(r["pool"] - r["front"] + 1, r["pool"] + 1))
                right["draws"][0]["front"] = (
                    opposite if right["draws"][0]["front"] != opposite
                    else list(range(1, r["front"] + 1))
                )
                self.assertNotEqual(core.digest(left), core.digest(right))
                a = core.forecast(left, "pairwise_d2")
                b = core.forecast(right, "pairwise_d2")
                self.assertEqual(a["candidates_1_to_5"], b["candidates_1_to_5"])
                self.assertEqual(a["primary_d2"], b["primary_d2"])
                self.assertEqual(a["ticket"], b["ticket"])
                self.assertNotEqual(a["snapshot_sha256"], b["snapshot_sha256"])

    def test_exact_pair_ties_use_numeric_ascending(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = fixture(game, size=120)
                k = core.RULES[game]["front"]
                for row in snapshot["draws"]:
                    row["front"] = list(range(1, k + 1))
                oracle = independent_pair_components(snapshot)
                # Pairs within the fixed front set have identical exact scores.
                self.assertEqual(oracle[(1, 2)]["combined"],
                                 oracle[(1, 3)]["combined"])
                p = core.forecast(snapshot, "pairwise_d2")
                self.assertEqual(p["primary_d2"], [1, 2])
                self.assertTrue(core.validate_forecast(p, snapshot))

    def test_ablation_scores_are_separate_unregistered_hypotheses(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                oracle = independent_pair_components(fixture(game, size=140))
                for pair, x in oracle.items():
                    self.assertEqual(x["combined"], x["marginal"] + x["residual"])
                    self.assertIsInstance(x["observed"], int)
                    self.assertGreaterEqual(x["expected"], 0)
                # These rankings are arithmetic diagnostics, NOT submitted
                # prospective models. Registration and independent new draws
                # are required before any comparisons or claims of D2 edge.
                for version in ("marginal", "residual", "combined"):
                    self.assertIn(exact_rank(oracle, version)[0], oracle)

    def test_posthoc_d2_and_future_publication_are_rejected(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = fixture(game, size=140)
                p = core.forecast(snapshot, "pairwise_d2")
                changed = deepcopy(p)
                changed["primary_d2"] = list(reversed(changed["primary_d2"]))
                with self.assertRaises(core.GateError):
                    core.validate_forecast(changed, snapshot)
                future = deepcopy(snapshot)
                future["draws"][-1]["published_at"] = "2026-10-24T00:00:00+00:00"
                with self.assertRaises(core.GateError):
                    core.forecast(future, "pairwise_d2")


if __name__ == "__main__":
    unittest.main()
