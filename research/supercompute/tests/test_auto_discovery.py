"""Isolation and deterministic-contract tests for automatic formula discovery."""
import copy
import hashlib
import random
import tempfile
import unittest
from pathlib import Path

from research.supercompute import auto_discovery as auto
from research.supercompute.engine import SPECS


def synthetic(game, length=125):
    fm, fp, bm, bp = SPECS[game]
    rows = []
    for i in range(length):
        rng = random.Random(800000 + i + (17 if game == "dlt" else 0))
        rows.append({
            "issue": str((2026000 if game == "ssq" else 26000) + i + 1),
            "draw_date": "2026-01-01",
            "front": sorted(rng.sample(range(1, fm + 1), fp)),
            "back": sorted(rng.sample(range(1, bm + 1), bp)),
        })
    return rows


class AutoDiscoveryTests(unittest.TestCase):
    def test_candidate_grammar_is_generated_canonical_and_bounded(self):
        self.assertEqual(len(auto.GRAMMAR), 72)
        self.assertEqual(len({x["id"] for x in auto.GRAMMAR}), 72)
        self.assertEqual(set(x["family"] for x in auto.GRAMMAR),
                         set(auto.OPERATIONS))
        self.assertTrue(all(x["window"] in (8, 16)
                            for x in auto.GRAMMAR))
        self.assertFalse(any(x["op"] == "ADD" and x["left"] == x["right"]
                             for x in auto.GRAMMAR))

    def test_math_formula_uses_only_previous_draws(self):
        ssq = synthetic("ssq")
        expr = next(x for x in auto.GRAMMAR
                    if x["op"] == "ADD" and x["left"] == "LAG1")
        original = auto.evaluate_expr(expr, ssq[:120], 120, "front", 0, 33)
        modified = copy.deepcopy(ssq)
        modified[120]["front"] = [1, 2, 3, 4, 5, 6]
        self.assertEqual(original,
                         auto.evaluate_expr(expr, modified[:120], 120,
                                            "front", 0, 33))
        with self.assertRaises(ValueError):
            auto.evaluate_expr(expr, ssq[:2], 2, "front", 0, 33)

    def test_automatic_selected_candidates_predict_legal_ticket(self):
        for game in ("ssq", "dlt"):
            rows = synthetic(game)
            output = auto.discover(rows[:122], game, validation=4)
            p = output["prediction"]
            fm, fp, bm, bp = SPECS[game]
            self.assertEqual(output["candidates_evaluated"], 72)
            self.assertEqual(len(output["selected"]), auto.MAX_EXPERTS)
            self.assertEqual(len(set(x["formula_id"]
                                     for x in output["selected"])),
                             auto.MAX_EXPERTS)
            for area, count, maximum in (("front", fp, fm),
                                         ("back", bp, bm)):
                self.assertEqual(p[area], sorted(set(p[area])))
                self.assertEqual(len(p[area]), count)
                self.assertTrue(all(1 <= x <= maximum for x in p[area]))
            self.assertTrue(set(p["d2_pair"]).issubset(p["front"]))
            self.assertEqual(output["last_validation_observed_issue"],
                             rows[121]["issue"])

    def test_outcome_mutations_do_not_change_predraw_decision(self):
        rows = synthetic("ssq")
        a = auto.discover(rows[:120], "ssq", validation=4)
        rows[120]["front"] = [1, 2, 3, 4, 5, 6]
        rows[120]["back"] = [1]
        b = auto.discover(rows[:120], "ssq", validation=4)
        self.assertEqual(a, b)
        self.assertEqual(a["decision_sha256"], auto.digest({
            key: value for key, value in a.items() if key != "decision_sha256"
        }))

    def test_same_issue_null_is_stable_and_always_legal(self):
        for game in ("ssq", "dlt"):
            p = auto.research_null(game, 2026001)
            self.assertEqual(p, auto.research_null(game, 2026001))
            self.assertTrue(set(p["d2_pair"]).issubset(p["front"]))
        self.assertAlmostEqual(auto.exact_paired_p(5, 0), 0.0625)
        self.assertEqual(auto.exact_paired_p(0, 0), 1.0)

    def test_historical_report_is_never_formally_promoted(self):
        report = auto.build_report(periods=2)
        self.assertEqual(report["edge"], "NO_EDGE")
        self.assertEqual(report["formal_A"], 0)
        self.assertFalse(report["formal_prediction"])
        self.assertEqual(report["prospective_scored"], 0)
        self.assertFalse(report["official_source_authenticated"])
        self.assertFalse(report["pre_draw_independent_seal_verified"])
        self.assertEqual(set(report["games"]), {"ssq", "dlt"})
        for record in report["games"].values():
            self.assertEqual(record["cohort_size"], 2)
            self.assertEqual(len(record["evidence"]), 2)
            self.assertEqual(record["data"]["status"],
                             "historical_snapshot_not_live_verified")
            self.assertTrue(record["offline_next_after_stale_snapshot"]["not_formal"])
            for row in record["evidence"]:
                self.assertNotEqual(row["target_issue"],
                                    row["observed_asof_issue"])

    def test_create_only_digest_receipt_and_no_overwrite(self):
        report = {"edge": "NO_EDGE", "games": {}, "formal_A": 0}
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "audit"
            result = auto.write_once(report, folder)
            self.assertEqual(result, hashlib.sha256(
                (folder / "report.json").read_bytes()).hexdigest())
            self.assertIn("report.json",
                          (folder / "report.sha256").read_text())
            with self.assertRaises(FileExistsError):
                auto.write_once(report, folder)

    def test_input_boundary_fails_closed(self):
        with self.assertRaises(ValueError):
            auto.discover(synthetic("ssq", 80), "ssq")
        with self.assertRaises(ValueError):
            auto.discover(synthetic("ssq"), "ssq", validation=40)
        with self.assertRaises(ValueError):
            auto.run_game("unknown", periods=1)


if __name__ == "__main__":
    unittest.main()
