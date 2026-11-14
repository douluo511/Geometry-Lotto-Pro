"""End-to-end acceptance of unified 11-stage research pipeline on synthetic draws."""
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

from research.supercompute import v47_integrated as u
from research.supercompute.v47_forecast import main
from research.supercompute.v47_models import canonical, random_ticket, seed_from


def fake_history(game, n=124):
    rng = random.Random(seed_from("synthetic-eleven", game))
    first = date(2025, 1, 1)
    return [{**random_ticket(game, rng.getrandbits(64)),
             "issue": str(260000 + i),
             "draw_date": (first + timedelta(days=i)).isoformat()}
            for i in range(n)]


class UnifiedPredictionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {game: fake_history(game) for game in ("ssq", "dlt")}
        cls.reports = {game: u.run_all(cls.rows[game], game,
                          target_issue="RESEARCH_NEXT_"+game,
                          seed=19, generations=2, validation=3,
                          holdout=2, mc_trials=30, physics_steps=3)
                       for game in ("ssq", "dlt")}

    def test_all_eleven_have_executed_outputs(self):
        for game, report in self.reports.items():
            self.assertEqual(report["requirement_modules"], list(u.REQUIREMENTS))
            self.assertEqual(set(report["model_family_tickets"]), set(u.FAMILIES))
            self.assertTrue(report["statistics"]["top_pair_residuals"])
            self.assertTrue(report["geometry"]["transition_states"])
            self.assertEqual(report["simulation"]["uniform_monte_carlo"]["trials"], 30)
            self.assertTrue(report["physics"]["pair_collisions"])
            self.assertEqual(set(report["validation"]), {"M1", "M2", "M3"})
            self.assertEqual(set(report["validation"]["M3"]), set(u.FAMILIES))
            self.assertEqual(report["edge"], "NO_EDGE")
            self.assertFalse(report["formal_prediction"])
            self.assertFalse(report["forecast_frozen"])

    def test_ensemble_tickets_legality_and_d2(self):
        for game, report in self.reports.items():
            self.assertEqual(len(report["proposed_tickets"]), 3)
            for ticket in report["proposed_tickets"]:
                self.assertEqual(ticket["after_issue"], self.rows[game][-1]["issue"])
                self.assertTrue(set(ticket["dan2"]).issubset(ticket["front"]))
            self.assertTrue(all(r["status"] == "PASS" for r in report["validation"]["M1"]))
            self.assertAlmostEqual(sum(report["ensemble"]["model_weights"].values()), 1)

    def test_cell_division_parent_selection_children_and_genome(self):
        for report in self.reports.values():
            lineage = report["evolution"]["lineage"]
            self.assertGreaterEqual(len(lineage), 3)
            self.assertTrue(any(cell["origin"] == "crossover_mutation"
                                for stage in lineage[:-1]
                                for cell in stage["evaluated"]))
            self.assertEqual(len(report["evolution"]["champion_id"]), 12)
            self.assertFalse(report["evolution"]["uses_future_draws"])

    def test_holdout_data_never_changes_prior_training(self):
        rows = self.rows["ssq"]
        alternative = copy.deepcopy(rows)
        alternative[-1]["front"] = [1, 2, 3, 4, 5, 6]
        model_a = u.cell_division(rows[:-2], "ssq", seed=11, generations=1, validation=3)
        model_b = u.cell_division(alternative[:-2], "ssq", seed=11, generations=1, validation=3)
        self.assertEqual(model_a, model_b)

    def test_reproducibility_and_next_run_inheritance(self):
        prior = self.reports["ssq"]
        genes = prior["evolution"]["champion"]
        again = u.cell_division(self.rows["ssq"], "ssq", seed=19,
                                generations=2, validation=3,
                                previous_champion=genes)
        self.assertTrue(again["parent_from_prior_run"])
        self.assertEqual(again, u.cell_division(self.rows["ssq"], "ssq", seed=19,
                        generations=2, validation=3, previous_champion=genes))

    def test_freeze_is_create_only_and_scores_after_hash_verification(self):
        report = self.reports["dlt"]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "immutable.json"
            receipt = u.freeze_result(path, report)
            with self.assertRaises(FileExistsError):
                u.freeze_result(path, report)
            actual = {**random_ticket("dlt", 123),
                      "issue": report["target_issue"]}
            outcome = u.score_result(path, receipt["sha256"], actual)
            self.assertEqual(outcome["status"], "UNVERIFIED_DRAW_INPUT")
            self.assertEqual(len(outcome["tickets"]), 3)
            with self.assertRaises(ValueError):
                u.score_result(path, "0" * 64, actual)
            with self.assertRaises(ValueError):
                u.score_result(path, receipt["sha256"], {**actual, "issue": "WRONG"})

    def test_cli_requires_target(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "ssq.json"
            file.write_text(json.dumps({"game": "ssq", "draws": self.rows["ssq"]}),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                main(["generate", "--game", "ssq",
                      "--ssq-data", str(file), "--output", str(Path(d)/"x.json")])

    def test_cli_both_games_emit_full_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            params = ["generate", "--game", "both",
                      "--ssq-target", "TEST_SSQ",
                      "--dlt-target", "TEST_DLT",
                      "--seed", "19", "--generations", "1",
                      "--validation", "3", "--holdout", "2",
                      "--physics-steps", "3", "--mc-trials", "30",
                      "--output", str(root / "out.json"),
                      "--freeze-dir", str(root / "frozen")]
            for game in self.rows:
                path = root / (game + ".json")
                path.write_text(json.dumps({"game": game, "draws": self.rows[game]}),
                                encoding="utf-8")
                params.extend(["--"+game+"-data", str(path)])
            with redirect_stdout(StringIO()):
                main(params)
            saved = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(set(saved["games"]), {"ssq", "dlt"})
            self.assertEqual(len(saved["games"]["ssq"]["requirement_modules"]), 11)
            from research.supercompute.v47_registry import REGISTRY
            for game, payload in saved["games"].items():
                tickets = payload["proposed_tickets"]
                self.assertEqual(payload["ticket_count"], 11)
                self.assertEqual(len(payload["validation"]["M2"]), 11)
                self.assertEqual(len(payload["validation"]["M3"]), 11)
                self.assertEqual(payload["full_model_validation"], "PASS")
                audit = payload["independent_11"]["validation_all_11"]
                self.assertEqual(audit["model_count"], 11)
                self.assertEqual(len(audit["fold_evidence"]), 2)
                self.assertTrue(all(v["m3"]["recalibrated"]["samples"] > 0
                                    for v in audit["models"].values()))
                self.assertEqual(len(tickets), 11)
                self.assertEqual([t["model_number"] for t in tickets], list(range(1, 12)))
                self.assertEqual([t["model_name"] for t in tickets],
                                 [m.label for m in REGISTRY])
                for ticket in tickets:
                    actual = payload["independent_11"]["models"][
                        ticket["model_name"]]["prediction"]["ticket"]
                    self.assertEqual(ticket["front"], actual["front"])
                    self.assertEqual(ticket["back"], actual["back"])
                    self.assertEqual(ticket["dan2"], actual["dan2"])
                frozen = root / "frozen" / f"{game}-{payload['target_issue']}-v47-unified.json"
                sha = __import__("hashlib").sha256(frozen.read_bytes()).hexdigest()
                actual = {**random_ticket(game, 339), "issue": payload["target_issue"]}
                result = u.score_result(frozen, sha, actual)
                self.assertEqual(result["ticket_count"], 11)
                self.assertEqual(len(result["per_model_score"]), 11)
                self.assertEqual([item["model_name"] for item in result["per_model_score"]],
                                 [m.label for m in REGISTRY])
            self.assertEqual(sum(g["ticket_count"] for g in saved["games"].values()), 22)
            from research.supercompute.v47_delivery import export_delivery
            exported = export_delivery(saved,root/'frozen',root/'delivery')
            self.assertEqual(exported['record_count'],22)
            delivered = json.loads((root/'delivery/22_model_predictions.json').read_bytes())
            self.assertEqual(len(delivered['records']),22)
            self.assertEqual(len({(r['lottery'],r['model_number']) for r in delivered['records']}),22)
            for row in delivered['records']:
                frozen_bytes = (root/'delivery'/row['frozen_file']).read_bytes()
                self.assertEqual(row['frozen_sha256'],__import__('hashlib').sha256(frozen_bytes).hexdigest())
            with self.assertRaises(FileExistsError):
                export_delivery(saved,root/'frozen',root/'delivery')
            with redirect_stdout(StringIO()), self.assertRaises(FileExistsError):
                main(params)


    def test_unified_validation_only_five_families(self):
        for game, report in self.reports.items():
            expected = set(u.FAMILIES)
            self.assertEqual(len(expected), 5)
            self.assertEqual(set(report["model_family_tickets"]), expected)
            self.assertEqual(set(report["simulation"]["retrospective_validation"]["models"]), expected)
            self.assertEqual(set(report["validation"]["M2"]), expected)
            self.assertEqual(set(report["validation"]["M3"]), expected)
            fair = report["simulation"]["retrospective_validation"]["mathematical_fair_d2_probability"]
            for model in expected:
                self.assertAlmostEqual(report["validation"]["M2"][model]["fair_probability"], fair)



if __name__ == "__main__":
    unittest.main()
