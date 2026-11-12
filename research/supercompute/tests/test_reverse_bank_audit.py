"""Reverse Formula Bank isolation, causal ablation and control audit tests."""
from __future__ import annotations

import copy
import math
import os
import tempfile
import unittest
from pathlib import Path

from research.supercompute import reverse_bank_audit as audit


class ReverseBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generic main-only test discovery may not provide the separately
        # pinned 199cc source; dedicated CI MUST supply it and run all tests.
        if not os.environ.get("FORMULA_CHECKOUT"):
            raise unittest.SkipTest("pinned original formula checkout not supplied")
        cls.dependencies = audit.validate_dependencies(
            Path(os.environ["FORMULA_CHECKOUT"]),
            os.environ["FORMULA_EXPECTED_SHA"],
        )
        cls.ssq, cls.ssq_meta = audit.load_game("ssq", periods=6)
        cls.dlt, cls.dlt_meta = audit.load_game("dlt", periods=6)

    def test_pin_rejects_wrong_commit_and_absent_checkout(self):
        with self.assertRaises(ValueError):
            audit.validate_dependencies(
                Path(os.environ["FORMULA_CHECKOUT"]), "0" * 40)
        with self.assertRaises(ValueError):
            audit.validate_dependencies(Path("/missing/frozen-source"), "0" * 40)

    def test_model_universe_fixed_and_full_decision_reproduced(self):
        self.assertEqual(len(audit.METHODS), 6)
        self.assertEqual(len(audit.ARMS), 8)
        for game, rows in (("ssq", self.ssq), ("dlt", self.dlt)):
            prefix = rows[:-1]
            variants = audit.decide(prefix, game)
            self.assertEqual(set(variants), set(audit.ARMS))
            expected = audit.original_prediction(prefix, game)
            self.assertEqual(variants["FULL_WEIGHTED"]["prediction"],
                             audit.prediction_ticket(expected))
            for name, selected in variants.items():
                pick = selected["prediction"]
                self.assertEqual(len(pick["front"]), audit.GAMES[game].front_pick)
                self.assertEqual(len(pick["back"]), audit.GAMES[game].back_pick)
                self.assertEqual(len(pick["d2_pair"]), 2)
                self.assertTrue(set(pick["d2_pair"]).issubset(pick["front"]))
                self.assertEqual(pick["front"], sorted(set(pick["front"])))
                self.assertEqual(pick["back"], sorted(set(pick["back"])))
                self.assertLessEqual(len(selected["selected_formula_ids"]), 12)

    def test_outcome_mutation_does_not_change_decisions(self):
        prefix = self.ssq[:-1]
        a = audit.decide(prefix, "ssq")
        future = copy.deepcopy(self.ssq)
        future[-1] = type(future[-1])(
            future[-1].issue, (1, 2, 3, 4, 5, 6), (8,))
        b = audit.decide(future[:-1], "ssq")
        self.assertEqual(a, b)

    def test_coverage_and_controls_all_same_issues(self):
        for game in ("ssq", "dlt"):
            result = audit.run_game(game, periods=6)
            self.assertEqual(result["evaluated"], 6)
            self.assertEqual(len(result["rows"]), 6)
            self.assertEqual(len({r["issue"] for r in result["rows"]}), 6)
            self.assertEqual(set(result["arm_summary"]), set(audit.ARMS))
            self.assertEqual(len(result["placebo_d2_hits"]), 32)
            for row in result["rows"]:
                self.assertEqual(set(row["arms"]), set(audit.ARMS))
                self.assertNotEqual(row["issue"], row["asof_issue"])
                self.assertIn(row["control"]["d2_hit"], (0, 1))
            for arm in audit.ARMS:
                self.assertEqual(
                    result["arm_summary"][arm]["d2_hits"],
                    sum(row["arms"][arm]["d2_hit"] for row in result["rows"]))
                self.assertEqual(result["arm_summary"][arm]["evaluated"], 6)

    def test_dropped_issue_is_fatal_not_silently_shrunk(self):
        for game in ("ssq", "dlt"):
            rows, _ = audit.load_game(game, periods=6)
            broken = rows.copy()
            broken.pop(len(rows) // 2)
            with self.assertRaises(ValueError):
                audit.validate_roster(broken)

    def test_exact_mc_nemar_holm_and_candidate_boundaries(self):
        self.assertEqual(audit.exact_two_sided(0, 0), 1)
        self.assertAlmostEqual(audit.exact_two_sided(5, 0), 0.0625)
        self.assertEqual(audit.holm([0.01, 0.03, 0.04, 1.0]),
                         [0.04, 0.09, 0.09, 1.0])
        with self.assertRaises(ValueError):
            audit.exact_two_sided(-1, 2)
        data = audit.build_report(periods=6)
        self.assertEqual(data["prospective_scored"], 0)
        self.assertEqual(data["formal_A"], 0)
        self.assertEqual(data["edge"], "NO_EDGE")
        self.assertEqual(len(data["paired_comparisons"]), 16)
        self.assertEqual(set(data["games"]), {"ssq", "dlt"})
        self.assertTrue(all(row["p_holm"] >= row["p_raw"]
                            for row in data["paired_comparisons"]))
        for record in data["games"].values():
            self.assertEqual(record["source"]["status"],
                             "historical_snapshot_not_live_verified")
            self.assertEqual(record["evaluated"], 6)
            self.assertTrue(record["hypothetical_next_candidate"]["not_live_prediction"])

    def test_write_once_evidence_sha_on_both_games(self):
        report = audit.build_report(periods=6)
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "report"
            sha = audit.write_once(report, target)
            import hashlib
            self.assertEqual(
                hashlib.sha256((target / "report.json").read_bytes()).hexdigest(), sha)
            self.assertEqual((target / "report.sha256").read_text().split()[0], sha)
            self.assertIn("NO_EDGE",
                          (target / "summary.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                audit.write_once(report, target)


if __name__ == "__main__":
    unittest.main()
