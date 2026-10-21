"""Isolated synthetic-only checks: never assert official predictive advantage."""
import unittest
from research.ssq_dlt_v46_harness.paired_eval import (
    EvaluationBlocked, MODELS, NULL, exact_paired_upper_tail,
    holm_adjust, evaluate_shadow_d2,
)


def row(game, issue, overrides=None):
    bits = {model: 0 for model in MODELS}
    bits.update(overrides or {})
    return {"game": game, "issue": str(issue), "scores": bits}


class PairedEvalTests(unittest.TestCase):
    def test_one_sided_exact_small_discordant(self):
        self.assertEqual(exact_paired_upper_tail(4, 0), 1 / 16)
        self.assertEqual(exact_paired_upper_tail(0, 4), 1)
        self.assertEqual(exact_paired_upper_tail(0, 0), 1)
        self.assertEqual(exact_paired_upper_tail(2, 2), 11 / 16)

    def test_holm_keeps_twelve_slots_even_if_ten_exploratory_tests(self):
        self.assertEqual(holm_adjust({"a": .01, "b": .02}), {"a": .12, "b": .22})

    def test_no_discordance_no_superiority(self):
        study = evaluate_shadow_d2([row("SSQ", "001"), row("DLT", "002")])
        self.assertEqual(study["hypotheses_tested"], 10)
        self.assertEqual(study["decision"], "NO_EDGE")
        self.assertTrue(all(x["paired_one_sided_p"] == 1 for x in study["results"]))

    def test_perfect_synthetic_win_never_upgrades_status(self):
        study = evaluate_shadow_d2([row("SSQ", i, {"02-HOT60": 1}) for i in range(1, 9)])
        hot = next(x for x in study["results"] if x["model"] == "02-HOT60")
        self.assertEqual(hot["paired_one_sided_p"], 1 / 256)
        self.assertEqual(hot["exploratory_holm12_adjusted_p"], 12 / 256)
        self.assertEqual(study["formal_A"], 0)

    def test_pairing_same_issue_and_distinct_game(self):
        study = evaluate_shadow_d2([row("SSQ", "120", {"02-HOT60": 1}),
                                    row("DLT", "120", {NULL: 1})])
        self.assertEqual({x["lottery"] for x in study["results"]}, {"SSQ", "DLT"})
        self.assertEqual(study["hypotheses_tested"], 10)

    def test_duplicate_issue_cannot_inflate_sample(self):
        with self.assertRaisesRegex(EvaluationBlocked, "DUPLICATE"):
            evaluate_shadow_d2([row("SSQ", "120"), row("SSQ", "120")])

    def test_missing_agent_rejected(self):
        bad = row("SSQ", "120")
        del bad["scores"][NULL]
        with self.assertRaisesRegex(EvaluationBlocked, "INCOMPLETE"):
            evaluate_shadow_d2([bad])

    def test_invalid_bits_not_cast_to_boolean(self):
        for val in [True, -1, 2, "1"]:
            with self.subTest(val=val):
                with self.assertRaisesRegex(EvaluationBlocked, "INVALID_D2_BIT"):
                    evaluate_shadow_d2([row("SSQ", "120", {NULL: val})])

    def test_study_order_does_not_affect_numbers(self):
        a = row("SSQ", "120", {"02-HOT60": 1})
        b = row("SSQ", "121", {NULL: 1})
        self.assertEqual(evaluate_shadow_d2([a, b]), evaluate_shadow_d2([b, a]))

    def test_no_observations_rejected(self):
        with self.assertRaisesRegex(EvaluationBlocked, "EMPTY_STUDY"):
            evaluate_shadow_d2([])


if __name__ == "__main__":
    unittest.main()
