"""Adversarial draw-identity checks for SHADOW D2 arithmetic only.

These tests do not certify lottery outcomes, future predictions, or a model edge.
"""
import unittest

from research.harness_v46.core import MODELS
from research.harness_v46.statistics import EvaluationBlocked, evaluate_shadow_d2


def family():
    return [
        {"hypothesis_id": f"V47-{game}-{model}", "lottery": game, "model": model}
        for game in ("SSQ", "DLT") for model in MODELS
    ]


def row(game, issue):
    return {
        "lottery": game,
        "issue": issue,
        "scores": {model: 0 for model in MODELS},
    }


class StatisticalDrawIdentityTests(unittest.TestCase):
    def test_ascii_zero_padded_alias_must_not_double_the_denominator(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game), self.assertRaisesRegex(
                EvaluationBlocked, "DUPLICATE_DRAW"
            ):
                evaluate_shadow_d2(
                    [row(game, "29999"), row(game, "029999")], family()
                )

    def test_unicode_digits_and_non_decimal_numeric_forms_fail_closed(self):
        for issue in ("٢٦١٢١", "２６１２１", "²6121", "2²121"):
            with self.subTest(issue=issue), self.assertRaisesRegex(
                EvaluationBlocked, "INVALID_DRAW_IDENTITY"
            ):
                evaluate_shadow_d2([row("DLT", issue)], family())

    def test_different_games_may_share_the_same_numeric_issue(self):
        report = evaluate_shadow_d2(
            [row("SSQ", "29999"), row("DLT", "29999")], family()
        )
        self.assertTrue(all(x["draws"] == 1 for x in report["results"]))
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_one_valid_padded_issue_keeps_original_spelling(self):
        report = evaluate_shadow_d2([row("SSQ", "029999")], family())
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
