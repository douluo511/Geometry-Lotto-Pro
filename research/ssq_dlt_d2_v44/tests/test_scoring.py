"""Synthetic negative and positive tests: no official-draw certification."""
import copy
import math
import unittest

from research.ssq_dlt_d2_v44.scoring import (
    AdmissionBlocked, evaluate_registered, paired_exact_one_sided, score_d1_d5,
)

NULL = "M07-NULL-SHADOW"
VERSIONS = {"PAIRWISE-D2": "v1", NULL: "seed-001"}


def record(issue, front, rank_a, rank_null):
    return {
        "game": "SSQ",
        "issue": issue,
        "draw_front": front,
        "models": {
            "PAIRWISE-D2": {"version": "v1", "ranked_front": rank_a},
            NULL: {"version": "seed-001", "ranked_front": rank_null},
        },
    }


def fixture():
    return [
        record("SYNTH-01", [1, 2, 3, 4, 5, 6],
               [1, 2, 7, 8, 9], [1, 20, 21, 22, 23]),
        record("SYNTH-02", [10, 11, 12, 13, 14, 15],
               [10, 11, 20, 21, 22], [10, 30, 31, 32, 33]),
    ]


def evaluate(rows=None, issues=None, versions=None):
    return evaluate_registered(
        "SSQ",
        fixture() if rows is None else rows,
        ["SYNTH-01", "SYNTH-02"] if issues is None else issues,
        VERSIONS if versions is None else versions,
    )


class TestScoring(unittest.TestCase):
    def test_ssq_d2_and_d5_p0(self):
        r = score_d1_d5("SSQ", [1, 2, 7, 8, 9], [1, 2, 3, 4, 5, 6])
        self.assertEqual([r[f"D{k}"]["full"] for k in range(1, 6)],
                         [1, 1, 0, 0, 0])
        self.assertAlmostEqual(r["D2"]["p0"], 15 / 528)

    def test_dlt_random_baseline(self):
        r = score_d1_d5("DLT", [1, 2, 3, 4, 5], [1, 2, 6, 7, 8])
        self.assertAlmostEqual(r["D2"]["p0"], 10 / 595)
        self.assertEqual(r["D2"]["full"], 1)

    def test_invalid_bool_or_duplicate_numbers(self):
        for nums in ([True, 2, 3, 4, 5], [1, 1, 3, 4, 5], [1, 2, 3, 4, 36]):
            with self.subTest(nums=nums), self.assertRaises(AdmissionBlocked):
                score_d1_d5("DLT", nums, [1, 2, 3, 4, 5])

    def test_exploratory_pairwise_math(self):
        self.assertAlmostEqual(paired_exact_one_sided(2, 0), 0.25)
        self.assertAlmostEqual(paired_exact_one_sided(2, 2), 0.6875)
        self.assertEqual(paired_exact_one_sided(0, 0), 1)

    def test_same_period_paired_d2(self):
        out = evaluate()
        x = out["pairwise_vs_null"][0]
        self.assertEqual((x["wins"], x["losses"], x["ties"]), (2, 0, 0))
        self.assertEqual(out["research_ranking"][0]["model"], "PAIRWISE-D2")
        self.assertEqual(out["research_ranking"][0]["D2_full"], 2)
        self.assertEqual(out["decision"], "NO_EDGE")
        self.assertEqual(out["formal_a_samples"], 0)
        self.assertEqual(out["admission"], "RESEARCH_ONLY")

    def test_missing_issue_blocked(self):
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=fixture()[:1])

    def test_duplicate_issue_blocked(self):
        rows = fixture()
        rows[1]["issue"] = rows[0]["issue"]
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=rows)

    def test_wrong_model_registry_blocked(self):
        rows = fixture()
        del rows[0]["models"][NULL]
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=rows)

    def test_version_swap_blocked(self):
        rows = fixture()
        rows[0]["models"]["PAIRWISE-D2"]["version"] = "future-v2"
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=rows)

    def test_wrong_game_blocked(self):
        rows = fixture()
        rows[0]["game"] = "DLT"
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=rows)

    def test_invalid_tau_blocked(self):
        for tau in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(tau=tau), self.assertRaises(AdmissionBlocked):
                evaluate_registered("SSQ", fixture(), ["SYNTH-01", "SYNTH-02"],
                                    VERSIONS, tau=tau)

    def test_wrong_draw_length_blocked(self):
        rows = fixture()
        rows[1]["draw_front"] = [1, 2, 3, 4, 5]
        with self.assertRaises(AdmissionBlocked):
            evaluate(rows=rows)


if __name__ == "__main__":
    unittest.main()
