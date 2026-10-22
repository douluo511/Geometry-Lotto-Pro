"""test5 / ShrinkMix: independent, synthetic-only V4.7 contract checks.

No fixture is an official draw and none can qualify as prospective evidence.
"""
import copy
import random
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

from research.harness_v46 import core


def synthetic_snapshot(game="SSQ", n=140):
    rule = core.RULES[game]
    begin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        rng = random.Random(54000 + 19 * i + (1 if game == "DLT" else 0))
        timestamp = begin + timedelta(days=i)
        rows.append({
            "issue": str(28001 + i),
            "front": sorted(rng.sample(range(1, rule["pool"] + 1), rule["front"])),
            "back": sorted(rng.sample(range(1, rule["back_pool"] + 1), rule["back"])),
            "drawn_at": timestamp.isoformat(),
            "published_at": (timestamp + timedelta(hours=1)).isoformat(),
        })
    return {
        "lottery": game,
        "as_of": "2026-10-20T00:00:00+00:00",
        "sales_cutoff": "2026-10-23T12:00:00+08:00",
        "target_draw_at": "2026-10-23T21:00:00+08:00",
        "target_issue": "29999",
        "draws": rows,
        "provenance": {"status": "SYNTHETIC_NOT_OFFICIAL"},
    }


def independent_exact_oracle(snapshot):
    """Integer numerator of (60/260)*(recent_count/60)
    + (200/260)*(whole_count/N): (N*recent_count + 200*whole_count)/(260*N).
    This oracle deliberately does not call the model score or _freq functions.
    """
    history = snapshot["draws"]
    N = len(history)
    recent = Counter(ball for d in history[-60:] for ball in d["front"])
    lifetime = Counter(ball for d in history for ball in d["front"])
    return sorted(range(1, core.RULES[snapshot["lottery"]]["pool"] + 1),
                  key=lambda x: (-(N * recent[x] + 200 * lifetime[x]), x))


class ShrinkMixV47IndependentTest(unittest.TestCase):
    def test_reject_119_and_accept_120_draws_both_games(self):
        self.assertEqual(core.PARAMETERS["shrinkmix"],
                         {"recent_window": 60, "tau": 200})
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                short = synthetic_snapshot(game, 119)
                with self.assertRaisesRegex(core.GateError, "120"):
                    core.forecast(short, "shrinkmix")
                enough = synthetic_snapshot(game, 120)
                prediction = core.forecast(enough, "shrinkmix")
                self.assertEqual(len(prediction["candidates_1_to_5"]), 5)
                self.assertEqual(prediction["primary_d2"],
                                 prediction["candidates_1_to_5"][:2])

    def test_exact_integer_oracle_all_numbers_for_both_games(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = synthetic_snapshot(game)
                reference = independent_exact_oracle(snapshot)
                actual = core._model_ranking(snapshot, "shrinkmix")
                self.assertEqual(actual, reference)
                prediction = core.forecast(snapshot, "shrinkmix")
                self.assertEqual(prediction["candidates_1_to_5"], reference[:5])
                self.assertEqual(prediction["primary_d2"], reference[:2])
                self.assertTrue(set(reference[:5]).issubset(prediction["ticket"]["front"]))
                self.assertEqual(prediction["parameters_sha256"],
                                 core.digest(core.parameter_contract("shrinkmix")))
                self.assertEqual(prediction["model_source_sha256"],
                                 core.model_source_sha256())
                self.assertEqual(prediction, core.forecast(snapshot, "shrinkmix"))

    def test_whole_history_matters_and_hot60_does_not_see_older_changes(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                left = synthetic_snapshot(game, 140)
                right = copy.deepcopy(left)
                extras = list(range(3, 3 + core.RULES[game]["front"] - 1))
                for i in range(140):
                    common = 1 if i % 2 == 0 else 2
                    left["draws"][i]["front"] = sorted(extras + [1 if i < 80 else common])
                    right["draws"][i]["front"] = sorted(extras + [2 if i < 80 else common])
                self.assertEqual(left["draws"][-60:], right["draws"][-60:])
                self.assertEqual(core._model_ranking(left, "hot60"),
                                 core._model_ranking(right, "hot60"))
                rank_left = core._model_ranking(left, "shrinkmix")
                rank_right = core._model_ranking(right, "shrinkmix")
                self.assertLess(rank_left.index(1), rank_left.index(2))
                self.assertLess(rank_right.index(2), rank_right.index(1))
                self.assertNotEqual(core.digest(left), core.digest(right))
                self.assertEqual(rank_left, independent_exact_oracle(left))
                self.assertEqual(rank_right, independent_exact_oracle(right))

    def test_numeric_tie_break_and_immutable_d2(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snap = synthetic_snapshot(game, 120)
                k = core.RULES[game]["front"]
                for row in snap["draws"]:
                    row["front"] = list(range(1, k + 1))
                rank = core._model_ranking(snap, "shrinkmix")
                self.assertEqual(rank, list(range(1, core.RULES[game]["pool"] + 1)))
                p = core.forecast(snap, "shrinkmix")
                self.assertEqual(p["primary_d2"], [1, 2])
                p["primary_d2"] = [2, 1]
                with self.assertRaises(core.GateError):
                    core.validate_forecast(p, snap)

    def test_post_asof_publication_fails_closed(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snap = synthetic_snapshot(game, 120)
                snap["draws"][-1]["published_at"] = "2026-10-21T00:00:00+00:00"
                with self.assertRaises(core.GateError):
                    core.forecast(snap, "shrinkmix")


if __name__ == "__main__":
    unittest.main()
