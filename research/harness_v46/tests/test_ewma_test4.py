"""test4 EWMA independent math oracle and V4.7 admission tests.

Synthetic inputs ONLY. These tests neither admit official G01 source data nor
claim that EWMA predicts independent fair lottery draws.
"""
import copy
import math
import unittest

from research.harness_v46 import core
from research.harness_v46.tests.test_core import fixture


def oracle_ranking(snapshot):
    """Direct closed-form weighted sum; NOT the iterative EWMA implementation."""
    tail = snapshot["draws"][-120:]
    alpha, decay = 0.08, 0.92
    pool = core.RULES[snapshot["lottery"]]["pool"]
    reference = {
        n: math.fsum(
            alpha * decay ** (len(tail) - 1 - i)
            for i, draw in enumerate(tail) if n in draw["front"]
        )
        for n in range(1, pool + 1)
    }
    return sorted(reference, key=lambda n: (-reference[n], n))


def pattern(lottery):
    """Make Hot60 and EWMA disagree predictably without observing a result."""
    s = fixture(lottery, size=120)
    k = core.RULES[lottery]["front"]
    base = list(range(1, k))  # k-1 stable front numbers
    for index, d in enumerate(s["draws"]):
        # Earlier: constant filler. In the latest sixty draws, 30 occurs 40
        # times early and 31 occurs 20 times late. Hot60 favours 30;
        # exponentially decayed EWMA favours the more recent 31.
        final = 6 if index < 60 else (30 if index < 100 else 31)
        if final in base:
            final = 32
        d["front"] = sorted(base + [final])
    return s


class Test4EWMAContract(unittest.TestCase):
    def test_rejects_119_history_even_from_direct_forecast(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                with self.assertRaisesRegex(core.GateError, "requires 120 historical draws"):
                    core.forecast(fixture(game, size=119), "ewma")
                self.assertEqual(core.forecast(fixture(game, size=120), "ewma")["model"], "ewma")

    def test_independent_closed_form_rank_for_both_lotteries(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                s = fixture(game, size=140)
                # Independent closed form instead of calling _rank, _freq or
                # the iterative recurrence as an oracle.
                expected = oracle_ranking(s)
                self.assertEqual(core._model_ranking(s, "ewma"), expected)
                record = core.forecast(s, "ewma")
                self.assertEqual(record["candidates_1_to_5"], expected[:5])
                self.assertEqual(record["primary_d2"], expected[:2])
                self.assertEqual(record["ticket"]["front"],
                                 sorted(expected[:core.RULES[game]["front"]]))
                self.assertTrue(core.validate_forecast(record, s))
                self.assertEqual(record["evidence_class"], "SHADOW")
                self.assertFalse(record["formal_a_eligible"])

    def test_data_older_than_registered_window_cannot_affect_ranking(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                original = fixture(game, size=145)
                changed = copy.deepcopy(original)
                k = core.RULES[game]["front"]
                replacement = list(range(1, k + 1))
                if changed["draws"][0]["front"] == replacement:
                    replacement = list(range(2, k + 2))
                changed["draws"][0]["front"] = replacement
                first = core.forecast(original, "ewma")
                second = core.forecast(changed, "ewma")
                self.assertNotEqual(first["snapshot_sha256"], second["snapshot_sha256"])
                self.assertEqual(first["candidates_1_to_5"],
                                 second["candidates_1_to_5"])
                self.assertEqual(first["ticket"], second["ticket"])

    def test_recent_weight_changes_ranking_relative_to_hot60(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                s = pattern(game)
                hot_rank = core._model_ranking(s, "hot60")
                ewma_rank = core._model_ranking(s, "ewma")
                self.assertLess(hot_rank.index(30), hot_rank.index(31))
                self.assertLess(ewma_rank.index(31), ewma_rank.index(30))
                self.assertNotEqual(hot_rank, ewma_rank)
                # This is a mechanism check, not a future hit-rate result.

    def test_numeric_tie_break_and_future_publication_block(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                s = fixture(game, size=120)
                k = core.RULES[game]["front"]
                for d in s["draws"]:
                    d["front"] = list(range(1, k + 1))
                # All non-selected numbers have identical zero EWMA score.
                self.assertEqual(core._model_ranking(s, "ewma"),
                                 list(range(1, core.RULES[game]["pool"] + 1)))
                s["draws"][-1]["published_at"] = "2026-10-25T00:00:00+00:00"
                with self.assertRaisesRegex(core.GateError, "future data"):
                    core.forecast(s, "ewma")


if __name__ == "__main__":
    unittest.main()
