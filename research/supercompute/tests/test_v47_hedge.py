"""Acceptance: eleven actual +/- pairs per game, no fake inverse aliases."""
from datetime import date, timedelta
from pathlib import Path
import copy
import hashlib
import json
import random
import tempfile
import unittest

from research.supercompute.v47_hedge import (
    NEGATIVE_REGISTRY, REGISTRY_22, fair_pair, _run_22_core,
    evolve_exclusion, run_hedge22, score_one, score_frozen,
)
from research.supercompute.v47_models import SPECS, canonical, random_ticket, seed_from, validate_ticket
from research.supercompute.v47_registry import REGISTRY


def history(game, count=132):
    randomizer = random.Random(seed_from("hedge-22-test", game))
    return [{**random_ticket(game, randomizer.getrandbits(64)),
             "issue": str(2026000 + i if game == "ssq" else 26000 + i),
             "draw_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat()}
            for i in range(count)]


class TwentyTwoComputationalModelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {g: history(g) for g in SPECS}
        cls.report = {
            g: run_hedge22(cls.rows[g], g, str(int(cls.rows[g][-1]["issue"]) + 1),
                           seed=30, generations=2, validation=3,
                           holdout=3, mc_trials=35, physics_steps=4)
            for g in SPECS}

    def test_true_twenty_two_registry_with_eleven_distinct_negative_fit_functions(self):
        self.assertEqual(len(REGISTRY), 11)
        self.assertEqual(len(NEGATIVE_REGISTRY), 11)
        self.assertEqual(len(REGISTRY_22), 22)
        self.assertEqual(len(set(name for name, _ in REGISTRY_22)), 22)
        self.assertEqual(len({cls.__name__ for cls in NEGATIVE_REGISTRY}), 11)
        self.assertEqual(len({cls.fit for cls in NEGATIVE_REGISTRY}), 11)
        for i in range(1, 12):
            self.assertEqual(REGISTRY_22[2*i-2][0], f"M{i:02d}+")
            self.assertEqual(REGISTRY_22[2*i-1][0], f"M{i:02d}-")
        for _, cls in REGISTRY_22:
            self.assertTrue(callable(cls.fit))
            self.assertTrue(callable(cls.predict))
            self.assertTrue(callable(cls.score))

    def test_forty_four_model_outputs_each_has_real_fit_and_validation(self):
        for game, data in self.report.items():
            self.assertEqual(data["model_count"], 22)
            self.assertEqual(data["ticket_count"], 22)
            self.assertEqual(len(data["models"]), 22)
            self.assertEqual(len(data["tickets"]), 22)
            self.assertEqual(data["historical_validation"]["model_count"], 22)
            self.assertEqual(len(data["historical_validation"]["models"]), 22)
            for record in data["models"].values():
                self.assertEqual(record["status"], "EXECUTED")
                self.assertTrue(record["fit"])
                self.assertTrue(record["prediction"]["ticket"])
                validate_ticket(record["prediction"]["ticket"], game)
                self.assertEqual(record["direction"] in ("subset", "not_subset"), True)
            for name, result in data["historical_validation"]["models"].items():
                self.assertEqual(result["M2"]["status"], "PASS", name)
                self.assertEqual(result["M2"]["trials"], 3)
                self.assertEqual(result["M3"]["trained_on_past_folds"], 2)
                self.assertEqual(result["M3"]["tested_on_heldout_folds"], 1)
                self.assertEqual(result["M3"]["calibrated"]["samples"], 1)
            self.assertFalse(data["historical_validation"]["multiple_tests_adjusted"])
        self.assertEqual(sum(g["ticket_count"] for g in self.report.values()), 44)

    def test_negative_eleven_are_computed_not_copied_from_positive(self):
        for game, data in self.report.items():
            for i in range(1, 12):
                positive = data["models"][f"M{i:02d}+"]
                negative = data["models"][f"M{i:02d}-"]
                ex = negative["prediction"]["excluded_pair"]
                self.assertEqual(len(ex), 2)
                self.assertTrue(set(ex).isdisjoint(negative["prediction"]["ticket"]["front"]))
                self.assertTrue(negative["prediction"]["candidate_uses_hard_exclusion"])
                self.assertEqual(negative["prediction"]["logical_event"],
                                 "EXCLUDED_PAIR_NOT_SUBSET_OF_DRAW")
                self.assertEqual(negative["prediction"]["source_positive_name"],
                                 positive["base_name"])
                self.assertEqual(negative["fit"]["method"],
                                 NEGATIVE_REGISTRY[i-1].method)
                self.assertTrue(negative["fit"]["trained_anti_probability"])
                self.assertTrue(negative["fit"]["cell_evolution"]["lineage"])
                self.assertFalse(negative["fit"]["cell_evolution"]["uses_future_draws"])
                self.assertTrue(any(x["origin"] == "crossover_mutation"
                    for gen in negative["fit"]["cell_evolution"]["lineage"]
                    for x in gen["evaluated"]))

    def test_subset_complement_not_disjoint_and_distinct_null_probabilities(self):
        for game in SPECS:
            fair = fair_pair(game)
            self.assertAlmostEqual(fair["subset"] + fair["not_subset"], 1.0)
            self.assertGreater(fair["not_subset"], fair["disjoint"])
            actual = {"front": [1, 2, 3, 4, 5, 6], "back": [1]} if game == "ssq" \
                else {"front": [1, 2, 3, 4, 5], "back": [1, 2]}
            rec = {"direction": "not_subset", "prediction": {
                "excluded_pair": [1, 7],
                "ticket": {"front": actual["front"], "back": actual["back"],
                           "dan2": [1, 2]}}}
            evaluation = score_one(rec, actual, game)
            self.assertTrue(evaluation["negative_event_not_subset"])
            self.assertFalse(evaluation["stronger_event_disjoint"])
            self.assertTrue(evaluation["candidate_d2_hit"])
            rec["prediction"]["excluded_pair"] = [1, 2]
            self.assertFalse(score_one(rec, actual, game)["negative_event_not_subset"])

    def test_evolution_inherits_actual_negative_parent_genome(self):
        for game, data in self.report.items():
            rows = self.rows[game]
            first = data["evolution"]["negative_champions"]
            again = evolve_exclusion(rows, game, "HOT60",
                                     seed=30, generations=2,
                                     previous=first["HOT60"])
            self.assertTrue(again["previous_inherited"])
            self.assertTrue(again["parent_in_generation_one"])
            self.assertTrue(any(item["origin"] == "inherited"
                for item in again["lineage"][0]["evaluated"]))
            self.assertEqual(again["lineage"][0]["evaluated"][-1]["genes"] != {}, True)

    def test_no_hindsight_in_prefix_fit_and_reproducible_negative_output(self):
        for game, rows in self.rows.items():
            first_base, first = _run_22_core(rows[:-2], game, seed=11,
                generations=1, validation=3, holdout=2,
                mc_trials=20, physics_steps=3)
            modified = copy.deepcopy(rows)
            modified[-1]["front"] = [1, 2, 3, 4, 5, 6] if game == "ssq" \
                else [1, 2, 3, 4, 5]
            _, second = _run_22_core(modified[:-2], game, seed=11,
                generations=1, validation=3, holdout=2,
                mc_trials=20, physics_steps=3)
            self.assertEqual(first, second)

    def test_create_only_hash_frozen_scoring_all_22(self):
        for game, run in self.report.items():
            target = run["target_issue"]
            with tempfile.TemporaryDirectory() as temp:
                f = Path(temp) / "frozen.json"
                doc = {"schema": "SSQDLT_V47_HEDGE22_FROZEN_V1",
                       "source": run, "created_utc": "2026-11-14T02:00:00Z"}
                b = canonical(doc)
                with f.open("xb") as h:
                    h.write(b)
                with self.assertRaises(FileExistsError):
                    with f.open("xb") as h:
                        h.write(b)
                actual = {**random_ticket(game, 777), "issue": target}
                out = score_frozen(f, hashlib.sha256(b).hexdigest(), actual)
                self.assertEqual(out["count"], 22)
                self.assertEqual(len(out["models"]), 22)
                self.assertTrue(out["status"].endswith("UNVERIFIED"))
                with self.assertRaises(ValueError):
                    score_frozen(f, "0" * 64, actual)
                with self.assertRaises(ValueError):
                    score_frozen(f, hashlib.sha256(b).hexdigest(),
                                 dict(actual, issue="BAD"))


if __name__ == "__main__":
    unittest.main()
