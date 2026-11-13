"""Synthetic acceptance tests: no real draw or prospective edge claimed."""
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

from research.supercompute import v47_models as m
from research.supercompute.v47_cli import main


def synthetic(game, n=126):
    rng = random.Random(m.seed_from("synthetic", game))
    first = date(2025, 1, 1)
    return [{**m.random_ticket(game, rng.getrandbits(64)),
             "issue": str(1000 + i),
             "draw_date": (first + timedelta(days=i)).isoformat()}
            for i in range(n)]


class TestV47ModelLab(unittest.TestCase):
    def test_m1_ticket_spaces_and_probability_mass(self):
        self.assertEqual(m.m1_math(synthetic("ssq"), "ssq",
                         m.candidates(synthetic("ssq"), "ssq", "HOT60", limit=1)[0])["ticket_space"],
                         17_721_088)
        self.assertEqual(m.m1_math(synthetic("dlt"), "dlt",
                         m.candidates(synthetic("dlt"), "dlt", "HOT60", limit=1)[0])["ticket_space"],
                         21_425_712)
        for game in m.SPECS:
            rows = synthetic(game)
            for model in m.MODELS:
                for area in ("front", "back"):
                    marginal = m.inclusion_probabilities(rows, game, area, model)
                    picked = m.SPECS[game][1 if area == "front" else 3]
                    self.assertAlmostEqual(sum(marginal), picked)

    def test_all_families_produce_legal_candidates(self):
        for game in m.SPECS:
            for model in m.MODELS:
                rows = synthetic(game)
                for ticket in m.candidates(rows, game, model, limit=2):
                    self.assertTrue(m.validate_ticket(ticket, game))
                    self.assertEqual(len(ticket["dan2"]), 2)
                    self.assertTrue(set(ticket["dan2"]).issubset(ticket["front"]))
                    self.assertFalse(ticket["formal_prediction"])

    def test_future_data_cannot_change_past_prediction(self):
        rows = synthetic("ssq", 140)
        old = {name: m.candidates(rows[:126], "ssq", name, seed=7)
               for name in m.MODELS}
        corrupt = copy.deepcopy(rows)
        corrupt[126]["front"] = [1, 2, 3, 4, 5, 6]
        new = {name: m.candidates(corrupt[:126], "ssq", name, seed=7)
               for name in m.MODELS}
        self.assertEqual(old, new)

    def test_geometry_and_pair_sums(self):
        rows = synthetic("dlt")
        counts = m.pair_residuals(rows, "dlt")
        self.assertEqual(len(counts), 35 * 34 // 2)
        prob, fair = m.geometry_transition(rows, "dlt")
        self.assertAlmostEqual(sum(prob.values()), 1)
        self.assertAlmostEqual(sum(fair.values()), 1)
        self.assertEqual(m.geometry_state(rows, "dlt")["samples"], 60)
        self.assertEqual(sum(m.geometry(rows[-1])["gaps"]), m.geometry(rows[-1])["span"])

    def test_validation_rejects_corrupted_history(self):
        rows = synthetic("ssq", 4)
        rows[0]["front"] = [1, 1, 2, 3, 4, 5]
        with self.assertRaises(ValueError):
            m.validate_history(rows, "ssq")
        with self.assertRaises(ValueError):
            m.parameters({"mix": 4})

    def test_physics_uncalibrated_and_monte_carlo_deterministic(self):
        self.assertEqual(m.physics_toy("ssq", 7, steps=5), m.physics_toy("ssq", 7, steps=5))
        self.assertFalse(m.physics_toy("ssq", 7, steps=5)["machine_calibrated"])
        self.assertEqual(m.monte_carlo("dlt", 100, 9), m.monte_carlo("dlt", 100, 9))

    def test_m2_m3_and_exact_fair_chance(self):
        refutation = m.m2_refutation([1, 0, 1], .2)
        self.assertEqual(refutation["hits"], 2)
        self.assertAlmostEqual(refutation["exploratory_one_sided_p"], .104)
        self.assertFalse(refutation["multiple_tests_adjusted"])
        calibration = m.m3_calibration([(.5, 1), (.5, 0)])
        self.assertAlmostEqual(calibration["brier"], .25)
        self.assertAlmostEqual(calibration["ece"], 0)

    def test_challenger_reproducible_and_holdout_sealed(self):
        rows = synthetic("ssq", 126)
        first = m.evolve(rows[:124], "ssq", seed=12)
        second = m.evolve(rows[:124], "ssq", seed=12)
        self.assertEqual(first, second)
        report = m.backtest(rows, "ssq", periods=2, seed=12)
        self.assertEqual(report["models"]["Challenger"]["n"], 2)
        self.assertEqual(report["challenger_selected_before_test"]["trained_through"],
                         rows[-3]["issue"])
        self.assertTrue(report["independent_test_tail"])
        self.assertEqual(report["edge"], "NO_EDGE")

    def test_create_only_freeze_tamper_check(self):
        rows = synthetic("dlt")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "frozen.json"
            receipt = m.freeze(path, rows, "dlt", "ShrinkMix", target_issue="1126")
            with self.assertRaises(FileExistsError):
                m.freeze(path, rows, "dlt", "ShrinkMix", target_issue="1126")
            actual = {**m.random_ticket("dlt", 99), "issue": "1126"}
            result = m.score_frozen(path, actual, receipt["sha256"])
            self.assertEqual(result["status"], "UNVERIFIED_RESULT")
            with self.assertRaises(ValueError):
                m.score_frozen(path, actual, "0" * 64)
            with self.assertRaises(ValueError):
                m.score_frozen(path, {**actual, "issue": "1127"}, receipt["sha256"])

    def test_cli_run_both_and_non_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            args = ["run", "--game", "both", "--periods", "2", "--trials", "30"]
            for game in m.SPECS:
                path = root / (game + ".json")
                path.write_text(json.dumps({"game": game, "draws": synthetic(game)}))
                args.extend(["--" + game + "-data", str(path)])
            dest = root / "report.json"
            args.extend(["--output", str(dest)])
            with redirect_stdout(StringIO()):
                main(args)
            payload = json.loads(dest.read_text())
            self.assertEqual(payload["edge"], "NO_EDGE")
            self.assertEqual(set(payload["games"]), set(m.SPECS))
            with self.assertRaises(FileExistsError), redirect_stdout(StringIO()):
                main(args)


    def test_exactly_five_registered_families_and_fair_m2(self):
        expected = ("HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger")
        self.assertEqual(m.MODELS, expected)
        for game in m.SPECS:
            rows = synthetic(game)
            report = m.backtest(rows, game, periods=2, seed=3)
            self.assertEqual(set(report["models"]), set(expected))
            fair = m.SPECS[game][1] * (m.SPECS[game][1] - 1) / (
                m.SPECS[game][0] * (m.SPECS[game][0] - 1))
            for model in expected:
                self.assertAlmostEqual(report["models"][model]["m2"]["fair_probability"], fair)
        with self.assertRaises(ValueError):
            m.m2_refutation([0, 2], .2)



if __name__ == "__main__":
    unittest.main()
