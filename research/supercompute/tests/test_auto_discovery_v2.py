"""V2 experimental integrity, frozen roster, baseline and nonpromotion tests."""
from __future__ import annotations

import copy
import hashlib
import random
import tempfile
import unittest
from pathlib import Path

from research.supercompute import auto_discovery_v2 as v2
from research.supercompute.engine import SPECS


def synthetic(game, n=230):
    fm, fp, bm, bp = SPECS[game]
    rows = []
    for i in range(n):
        rng = random.Random(92000 + i * 17 + (5 if game == "dlt" else 0))
        rows.append({
            "issue": str((2026000 if game == "ssq" else 26000) + i + 1),
            "draw_date": "2026-01-01",
            "front": sorted(rng.sample(range(1, fm + 1), fp)),
            "back": sorted(rng.sample(range(1, bm + 1), bp)),
        })
    return rows


class FalsificationFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssq = synthetic("ssq")
        cls.freeze = v2.frozen_selection(cls.ssq[:205], "ssq", 180, 205)

    def test_selection_is_frozen_on_development_only(self):
        self.assertEqual(self.freeze["candidate_count"], 72)
        self.assertEqual(self.freeze["validation_issues"], 25)
        self.assertEqual(len(self.freeze["expressions"]), 8)
        self.assertFalse(self.freeze["holdout_accessed"])
        self.assertEqual(self.freeze["weights"], "FROZEN_EQUAL")
        self.assertIn("NO_D2_TUNING", self.freeze["selection_objective"])
        ids = [r["expr"]["id"] for r in self.freeze["expressions"]]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(len(set(
            x["validation_prediction_digest"]
            for x in self.freeze["expressions"])), 8)
        self.assertEqual(
            self.freeze["selection_sha256"],
            v2.v1.digest({k: v for k, v in self.freeze.items()
                          if k != "selection_sha256"}),
        )

    def test_future_outcome_cannot_modify_selection_or_predraw_ticket(self):
        before = v2.predict_frozen(self.ssq[:205], "ssq", self.freeze)
        tampered = copy.deepcopy(self.ssq)
        tampered[205]["front"] = [1, 2, 3, 4, 5, 6]
        tampered[205]["back"] = [12]
        after = v2.predict_frozen(tampered[:205], "ssq", self.freeze)
        self.assertEqual(before, after)
        self.assertEqual(before["frozen_selection_sha256"],
                         self.freeze["selection_sha256"])
        self.assertEqual(len(before["candidate"]["front"]), 6)
        self.assertEqual(len(before["candidate"]["back"]), 1)
        self.assertTrue(set(before["candidate"]["d2_pair"])
                        .issubset(before["candidate"]["front"]))

    def test_live_holdout_outcomes_do_not_change_formula_roster(self):
        start = len(self.ssq) - 25
        frozen = v2.frozen_selection(self.ssq[:start], "ssq", 180, start)
        altered = copy.deepcopy(self.ssq)
        for i in range(start, len(altered)):
            altered[i]["front"] = [1, 2, 3, 4, 5, 6]
            altered[i]["back"] = [1]
        unchanged = v2.frozen_selection(altered[:start], "ssq", 180, start)
        self.assertEqual(frozen, unchanged)

    def test_tampered_selection_is_rejected(self):
        changed = copy.deepcopy(self.freeze)
        changed["expressions"][0]["weight"] = 100
        with self.assertRaises(ValueError):
            v2.predict_frozen(self.ssq[:205], "ssq", changed)
        with self.assertRaises(ValueError):
            v2.predict_frozen(self.ssq[:100], "ssq", self.freeze)

    def test_locked_formal_promotion_and_missing_history(self):
        with self.assertRaisesRegex(PermissionError, "FORMAL_BLOCKED"):
            v2.require_formal_promotion(
                official_source_authenticated=True,
                independent_timestamp=True,
                prospective_scored=10000,
            )
        with self.assertRaises(ValueError):
            v2.frozen_selection(self.ssq[:100], "ssq", 50, 100)
        with self.assertRaises(ValueError):
            v2.run_game("ssq", holdout=0)
        with self.assertRaises(ValueError):
            v2.run_game("foo", holdout=40)

    def test_paired_math_and_holm_are_precise(self):
        self.assertEqual(v2.v1.exact_paired_p(0, 0), 1.0)
        self.assertEqual(v2.v1.exact_paired_p(5, 0), 0.0625)
        self.assertEqual(v2.holm_bonferroni([0.01, 0.03, 0.04, 1]),
                         [0.04, 0.09, 0.09, 1])
        with self.assertRaises(ValueError):
            v2.holm_bonferroni([float("nan")])

    def test_same_issue_controls_are_deterministic(self):
        history = self.ssq[:205]
        first = v2.controls(history, "ssq", self.ssq[205]["issue"])
        second = v2.controls(history, "ssq", self.ssq[205]["issue"])
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(v2.CONTROL_IDS))
        for ticket in first.values():
            self.assertTrue(set(ticket["d2_pair"]).issubset(ticket["front"]))

    def test_real_snapshot_cohort_is_complete_and_historically_labeled(self):
        # Both lotteries, same 40-target holdout and 20-target development window.
        report = v2.build_report(holdout=40, validation=20)
        self.assertEqual(report["formal_A"], 0)
        self.assertFalse(report["formal_prediction"])
        self.assertEqual(report["edge"], "NO_EDGE")
        self.assertIsNone(report["next_live_prediction"])
        self.assertEqual(report["prospective_scored"], 0)
        self.assertFalse(report["official_source_authenticated"])
        for game, record in report["games"].items():
            self.assertEqual(record["source"]["status"],
                             "historical_snapshot_not_live_verified")
            self.assertEqual(record["holdout_size"], 40)
            self.assertEqual(len(record["rows"]), 40)
            self.assertTrue(record["all_test_issues_included"])
            self.assertEqual(len(record["paired"]), 3)
            self.assertEqual(set(record["summaries"]),
                             {"FROZEN_FORMULA"} | set(v2.CONTROL_IDS))
            sha = record["selection"]["selection_sha256"]
            self.assertTrue(all(r["selection_sha256"] == sha
                                for r in record["rows"]))
            for item in record["paired"]:
                self.assertEqual(item["same_issue_n"], 40)
                self.assertGreaterEqual(item["p_exploratory_holm"],
                                        item["p_exploratory_raw"])

    def test_receipts_create_only_sha256(self):
        report = {"edge": "NO_EDGE", "games": {}, "search": {"validation": 40}}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "v2"
            digest = v2.write_once(report, directory)
            self.assertEqual(digest, hashlib.sha256(
                (directory / "report.json").read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                v2.write_once(report, directory)


if __name__ == "__main__":
    unittest.main()
