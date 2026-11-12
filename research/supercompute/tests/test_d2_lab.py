"""No-network adversarial tests for exact D2 coverage and paired research."""
from __future__ import annotations
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from research.supercompute.engine import SPECS, snapshot
from research.supercompute.d2_lab import (
    coverage_count, greedy_coverage, holm_adjust, paired_two_sided,
    evaluate_history, build_report, write_report,
)


class CoverageTests(unittest.TestCase):
    def test_formula_equals_independent_bruteforce(self):
        for n, k in ((7, 3), (8, 4), (9, 3)):
            for chosen in (
                [(1, 2)], [(1, 2), (1, 3)],
                [(1, 2), (3, 4)], [(1, 2), (1, 4), (3, 5)],
            ):
                true_count = sum(
                    any(set(pair).issubset(front) for pair in chosen)
                    for front in combinations(range(1, n + 1), k)
                )
                self.assertEqual(coverage_count(n, k, chosen), true_count)

    def test_single_pair_is_theoretical_random_baseline(self):
        for game, (n, k, _, _) in SPECS.items():
            self.assertEqual(coverage_count(n, k, [(1, 2)]),
                             math.comb(n - 2, k - 2), game)

    def test_invalid_inputs_block(self):
        cases = [
            (7, 3, [(1, 1)]), (7, 3, [(0, 2)]),
            (7, 3, [(2, 1)]), (7, 3, [(1, 2), (1, 2)]),
            (7, 3, [(True, 3)]), (7, 3, [(1, 9)]),
            (7, 3, [(1, 2)] * 5), (2, 3, [(1, 2)]),
        ]
        for n, k, edges in cases:
            with self.subTest(n=n, k=k, edges=edges):
                with self.assertRaises(ValueError):
                    coverage_count(n, k, edges)

    def test_greedy_fixed_size_is_reproducible_and_monotone(self):
        for name, (n, k, _, _) in SPECS.items():
            x = greedy_coverage(n, k, 4)
            y = greedy_coverage(n, k, 4)
            self.assertEqual(x, y)
            self.assertEqual(len(x["greedy_pairs"]), 4)
            self.assertEqual(len(set(map(tuple, x["greedy_pairs"]))), 4)
            self.assertEqual(x["coverage_count"],
                             coverage_count(n, k, x["greedy_pairs"]))
            self.assertGreaterEqual(x["coverage_count"], x["baseline_coverage_count"], name)
            self.assertEqual(len(x["baseline_pairs"]), 4)
            self.assertEqual(x["baseline_coverage_count"],
                             coverage_count(n, k, x["baseline_pairs"]))
            self.assertLess(x["coverage_count"], math.comb(n, k))
        with self.assertRaises(ValueError):
            greedy_coverage(33, 6, 0)
        with self.assertRaises(ValueError):
            greedy_coverage(33, 6, 5)


class PairedStudyTests(unittest.TestCase):
    def test_exact_paired_test_and_holm(self):
        self.assertEqual(paired_two_sided(0, 0), 1.0)
        self.assertEqual(paired_two_sided(5, 0), 0.0625)
        self.assertEqual(paired_two_sided(0, 5), 0.0625)
        self.assertEqual(holm_adjust([0.01, 0.03, 0.04, 1.0]),
                         [0.04, 0.09, 0.09, 1.0])
        with self.assertRaises(ValueError):
            paired_two_sided(-1, 3)

    def test_past_only_complete_roster_and_same_issue_null(self):
        for game in SPECS:
            draws, _ = snapshot(game)
            study = evaluate_history(draws[:170], game, 20, seed=2026)
            self.assertEqual(study["evaluated"], 20)
            self.assertEqual(len(study["rows"]), 20)
            self.assertEqual(len({r["issue"] for r in study["rows"]}), 20)
            for row in study["rows"]:
                self.assertEqual(set(row["arms"]), {"RANDOM_NULL", "HOT60", "EWMA30"})
                for arm in row["arms"].values():
                    self.assertIn(arm["d2_hit"], (0, 1))
                    self.assertIn(arm["full_hit"], (0, 1))
                self.assertNotEqual(row["issue"], row["asof_issue"])
            for arm, agg in study["models"].items():
                self.assertEqual(agg["d2_hits"],
                                 sum(r["arms"][arm]["d2_hit"] for r in study["rows"]))
                self.assertEqual(agg["evaluated"], 20)

    def test_mutating_future_does_not_change_past_predictions(self):
        draws, _ = snapshot("ssq")
        orig = evaluate_history(draws[:151], "ssq", 1, seed=2026)
        changes = json.loads(json.dumps(draws[:151]))
        changes[150]["front"] = [1, 2, 3, 4, 5, 6]
        altered = evaluate_history(changes, "ssq", 1, seed=2026)
        self.assertEqual(
            {arm: v["ticket"] for arm, v in orig["rows"][0]["arms"].items()},
            {arm: v["ticket"] for arm, v in altered["rows"][0]["arms"].items()},
        )

    def test_insufficient_samples_fail_instead_of_shrink(self):
        draws, _ = snapshot("dlt")
        with self.assertRaises(ValueError):
            evaluate_history(draws[:130], "dlt", 11, seed=2026)

    def test_two_game_report_holm_and_evidence_warnings(self):
        report = build_report(periods=30, max_pairs=2, seed=2026)
        self.assertEqual(set(report["games"]), {"ssq", "dlt"})
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["edge"], "NO_EDGE")
        self.assertEqual(report["research_valid"], "NOT_YET")
        self.assertEqual(report["engineering_pass"], "NOT_YET")
        self.assertEqual(report["prospective_sample_size"], 0)
        self.assertEqual(len(report["model_comparisons"]), 4)
        for entry in report["model_comparisons"]:
            self.assertGreaterEqual(entry["p_holm"], entry["p_raw"])
            self.assertEqual(entry["evaluated"], 30)
            self.assertEqual(entry["model_only"] + entry["null_only"]
                             + entry["both_hit"] + entry["both_miss"], 30)
        for game in report["games"].values():
            self.assertEqual(game["source"]["status"],
                             "historical_snapshot_not_live_verified")
            self.assertEqual(game["historical_study"]["evaluated"], 30)
            self.assertEqual(len(game["historical_study"]["rows"]), 30)

    def test_hash_receipt_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "report"
            report = build_report(periods=6, max_pairs=2, seed=2026)
            write_report(report, out)
            raw = (out / "report.json").read_bytes()
            expected = (out / "report.sha256").read_text().split()[0]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
            self.assertIn("NOT_YET", (out / "summary.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_report(report, out)


if __name__ == "__main__":
    unittest.main()
