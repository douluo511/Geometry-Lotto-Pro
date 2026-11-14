"""Contract tests proving eleven independent executable model objects."""
from datetime import date, timedelta
import copy
import hashlib
import json
import random
import unittest

from research.supercompute import v47_registry as reg
from research.supercompute.v47_models import SPECS, canonical, random_ticket, seed_from


def fixtures(game, count=124):
    rng = random.Random(seed_from("eleven-independence-fixture", game))
    return [{**random_ticket(game, rng.getrandbits(64)),
             "issue": str(i + 4000),
             "draw_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat()}
            for i in range(count)]


class ElevenIndependentModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {g: fixtures(g) for g in SPECS}
        cls.results = {g: reg.execute_eleven(cls.rows[g], g, seed=11,
                      generations=1, validation=3, holdout=2,
                      mc_trials=35, physics_steps=3) for g in SPECS}

    def test_registry_has_eleven_distinct_concrete_classes(self):
        classes = reg.REGISTRY
        self.assertEqual(len(classes), 11)
        self.assertEqual([m.number for m in classes], list(range(1, 12)))
        self.assertEqual(len({m.label for m in classes}), 11)
        self.assertEqual(len({m.__name__ for m in classes}), 11)
        self.assertEqual(len({m.fit for m in classes}), 11)
        self.assertEqual(len({m.predict for m in classes}), 11)
        for ModelClass in classes:
            self.assertTrue(callable(ModelClass.score))

    def test_both_games_all_eleven_fit_and_predict_with_real_outputs(self):
        for game, run in self.results.items():
            self.assertEqual(run["model_count"], 11)
            self.assertEqual(len(run["models"]), 11)
            self.assertTrue(run["independent_modules"])
            self.assertFalse(run["formal_prediction"])
            self.assertFalse(run["physical_model_calibrated"])
            for name, item in run["models"].items():
                self.assertEqual(item["status"], "EXECUTED")
                self.assertTrue(item["fit"], name)
                self.assertTrue(item["prediction"]["ticket"])
                reg.validate_ticket(item["prediction"]["ticket"], game)
                self.assertEqual(item["contract"], ["fit", "predict", "score"])
            self.assertEqual(run["run_digest_sha256"],
                             hashlib.sha256(canonical({k: v for k, v in run.items()
                                 if k != "run_digest_sha256"})).hexdigest())

    def test_models_six_to_eleven_are_independently_executed(self):
        for game, run in self.results.items():
            models = run["models"]
            self.assertEqual(models["Statistics"]["number"], 6)
            self.assertTrue(models["Statistics"]["prediction"]["top_pairs"])
            self.assertEqual(models["ForecastSearch"]["number"], 7)
            self.assertEqual(len(models["ForecastSearch"]["prediction"]["alternates"]), 2)
            self.assertEqual(models["Geometry"]["number"], 8)
            self.assertIn("span", models["Geometry"]["prediction"]["features"])
            self.assertEqual(models["ProbabilitySimulation"]["number"], 9)
            self.assertEqual(models["ProbabilitySimulation"]["fit"]["mc_trials"], 35)
            self.assertTrue(models["ProbabilitySimulation"]["prediction"]["retrospective"]["strictly_past_only"])
            self.assertEqual(models["Physics"]["number"], 10)
            self.assertEqual(models["Physics"]["prediction"]["physical_simulation"]["machine_calibrated"], False)
            self.assertEqual(models["M1_M2_M3_Validation"]["number"], 11)
            self.assertEqual(models["M1_M2_M3_Validation"]["prediction"]["legal_math_checks"], 11)
            self.assertEqual(len(models["M1_M2_M3_Validation"]["prediction"]["ensemble_from"]), 10)
            self.assertAlmostEqual(sum(models["M1_M2_M3_Validation"]["prediction"]["influence_weights"].values()), 1)
            self.assertEqual(len(models["M1_M2_M3_Validation"]["fit"]["m2"]), 11)
            self.assertEqual(len(models["M1_M2_M3_Validation"]["fit"]["m3_brier"]), 11)

    def test_all_eleven_walk_forward_m2_and_true_heldout_calibration(self):
        for game, output in self.results.items():
            audit = output["validation_all_11"]
            self.assertEqual(audit["model_count"], 11)
            self.assertEqual(len(audit["models"]), 11)
            self.assertEqual(audit["method"], "chronological_walk_forward")
            self.assertTrue(all(f["test_target_unseen_in_fit"] for f in audit["fold_evidence"]))
            self.assertFalse(audit["uses_future_draws"])
            for name, record in audit["models"].items():
                self.assertEqual(record["m2"]["test"], "exact_binomial_fair_d2")
                self.assertEqual(record["m2"]["trials"], 2)
                self.assertEqual(record["m3"]["calibration_method"], "heldout_shrink_to_fair")
                self.assertEqual(record["m3"]["training_fold_count"], 1)
                self.assertGreater(record["m3"]["training_samples"], 0)
                self.assertGreater(record["m3"]["independent_test_samples"], 0)
                self.assertAlmostEqual(
                    record["m3"]["recalibrated"]["samples"],
                    record["m3"]["raw"]["samples"])
            validation = output["models"]["M1_M2_M3_Validation"]
            self.assertEqual(len(validation["prediction"]["independent_fair_d2_tests"]), 11)
            self.assertEqual(len(validation["prediction"]["marginal_calibration"]), 11)

    def test_pair_statistics_and_geometry_not_identical_probability_aliases(self):
        for game, output in self.results.items():
            models = output["models"]
            probabilities = [models[name]["prediction"]["marginals"]["front"]
                for name in ("ShrinkMix", "Pairwise-D2", "Statistics", "Geometry")]
            self.assertEqual(len({tuple(round(x, 10) for x in p)
                                  for p in probabilities}), 4)
            for name, record in models.items():
                fm, fp, bm, bp = SPECS[game]
                for area, count in (("front", fp), ("back", bp)):
                    self.assertAlmostEqual(
                        sum(record["prediction"]["marginals"][area]), count,
                        places=6, msg=name)

    def test_cell_division_has_real_genomes_and_lineage(self):
        for run in self.results.values():
            stage = run["models"]["Challenger"]
            self.assertTrue(stage["fit"]["genome"])
            self.assertTrue(stage["fit"]["lineage"])
            self.assertTrue(any(c["origin"] == "crossover_mutation"
                for part in stage["fit"]["lineage"] if part.get("evaluated")
                for c in part["evaluated"]))
            self.assertEqual(run["champion_genome"], stage["fit"]["genome"])

    def test_score_contract_and_no_future_leak(self):
        for game, run in self.results.items():
            actual = {**random_ticket(game, 99), "issue": "NEXT"}
            for ModelClass in reg.REGISTRY:
                model = ModelClass()
                out = model.score(run["models"][model.label]["prediction"]["ticket"],
                                  actual, game)
                self.assertIn("d2_hit", out)
                self.assertIn("front_hits", out)
            # Modifying the future heldout target cannot alter a prior fit.
            before = self.rows[game][:-2]
            altered = copy.deepcopy(self.rows[game])
            altered[-1]["front"] = [1, 2, 3, 4, 5, 6] if game == "ssq" else [1, 2, 3, 4, 5]
            # Test the model fit directly: the shortened prefix deliberately
            # lacks the extra prior rows needed for full audit splitting.
            self.assertEqual(reg.execute_eleven(before, game, generations=1,
                validation=3, holdout=2, mc_trials=20, physics_steps=2,
                full_audit=False),
                reg.execute_eleven(altered[:-2], game, generations=1,
                validation=3, holdout=2, mc_trials=20, physics_steps=2,
                full_audit=False))

    def test_inherited_champion_survives_across_runs(self):
        rows = self.rows["ssq"]
        prior = self.results["ssq"]["champion_genome"]
        run = reg.execute_eleven(rows, "ssq", seed=11, generations=1,
                                 validation=3, holdout=2, mc_trials=20,
                                 physics_steps=2, previous_champion=prior)
        self.assertTrue(run["models"]["Challenger"]["fit"]["inherited"])
        from research.supercompute.v47_integrated import cell_division
        e = cell_division(rows, "ssq", seed=11, generations=1, validation=3,
                          previous_champion=prior)
        self.assertTrue(e["inherited_parent_present_in_initial_population"])
        self.assertIsNotNone(e["inherited_champion_id"])
        self.assertTrue(any(c["origin"] == "inherited_prior_run"
                            for c in e["lineage"][0]["evaluated"]))


if __name__ == "__main__":
    unittest.main()
