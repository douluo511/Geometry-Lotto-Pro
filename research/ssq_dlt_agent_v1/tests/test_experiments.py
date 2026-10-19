"""Exact synthetic algorithm evidence, never lottery outcome validation."""
import ast
from fractions import Fraction
import inspect
import json
import random
import unittest
from unittest.mock import patch

from research.ssq_dlt_agent_v1 import experiments
from research.ssq_dlt_agent_v1.experiments import (
    DiagnosticBlocked, SYNTHETIC_PARAMETERS, _pair_rankings,
    _shrunken_pair_probability, _synthetic_history, run_diagnostic,
)


class SyntheticPairShrinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_diagnostic("synthetic_pair_shrink", dict(SYNTHETIC_PARAMETERS))

    def test_exact_affine_identity_for_unequal_counts_and_ties(self):
        for prior in (Fraction(15, 528), Fraction(10, 595)):
            for a, b in ((0, 0), (60, 0), (1, 2), (21, 21), (59, 60)):
                qa = _shrunken_pair_probability(a, 60, 200, prior)
                qb = _shrunken_pair_probability(b, 60, 200, prior)
                self.assertIs(type(qa), Fraction)
                self.assertEqual(qa - qb, Fraction(a - b, 260))
                self.assertEqual((qa > qb) - (qa < qb), (a > b) - (a < b))

    def test_exhaustive_legal_pair_rank_and_selected_d2_are_equal(self):
        self.assertEqual(self.result["status"], "PASS")
        self.assertEqual(self.result["case_count"], 40)
        self.assertEqual((self.result["passed_cases"], self.result["failed_cases"]), (40, 0))
        for game, total in (("SSQ", 528), ("DLT", 595)):
            cases = [case for case in self.result["cases"] if case["game"] == game]
            self.assertEqual(len(cases), 20)
            for case in cases:
                self.assertEqual(case["legal_pair_count"], total)
                self.assertEqual(case["adjacent_comparisons"], total - 1)
                self.assertTrue(all(case["checks"].values()))

    def test_all_seeded_histories_have_legal_front_and_back_numbers(self):
        for game, upper, count, back_upper, back_count in (
                ("SSQ", 33, 6, 16, 1), ("DLT", 35, 5, 12, 2)):
            history = _synthetic_history(game, random.Random(20261018), 60)
            self.assertEqual(len(history), 60)
            for row in history:
                self.assertTrue(row["issue"].startswith("SYNTHETIC-"))
                for values, size, limit in ((row["front"], count, upper),
                                            (row["back"], back_count, back_upper)):
                    self.assertEqual(len(set(values)), size)
                    self.assertEqual(tuple(sorted(values)), values)
                    self.assertTrue(all(type(n) is int and 1 <= n <= limit for n in values))

    def test_tie_counterexample_rejects_false_shrinkage_improvement(self):
        # All highest pair counts tie. Marginal sum selects (1, 3), while a
        # shortcut that silently drops that rule selects (1, 2).
        blocks = ((1, 2, 4, 5, 6, 7), (1, 3, 8, 9, 10, 11),
                  (3, 12, 13, 14, 15, 16))
        for upper, count in ((33, 6), (35, 5)):
            fronts = tuple(block[:count] for block in blocks for _ in range(20))
            raw, shrunk, counts, _, scores = _pair_rankings(
                fronts, upper=upper, draw_count=count, tau=200)
            self.assertEqual(raw[0], (1, 3))
            self.assertEqual(raw, shrunk)
            wrong = min(scores, key=lambda pair: (-scores[pair], pair))
            self.assertEqual(wrong, (1, 2))
            self.assertEqual(counts[wrong], counts[raw[0]])
        for example in self.result["tie_counterexamples"]:
            self.assertTrue(example["passed"])
            self.assertTrue(all(example["checks"].values()))
            self.assertEqual(example["preserved_selection_marginal_sum"], 80)
            self.assertEqual(example["ascending_only_selection_marginal_sum"], 60)

    def test_no_evidence_promotion_or_forecast_numbers_in_report(self):
        self.assertEqual(self.result["classification"], "SYNTHETIC_DIAGNOSTIC_NOT_HIT_RATE_EVIDENCE")
        self.assertEqual((self.result["formal_A"], self.result["decision"]), (0, "NO_EDGE"))
        self.assertFalse(self.result["historical_outcomes_used"])
        self.assertFalse(self.result["locked_test_rescored"])
        self.assertFalse(self.result["forecast_registered"])
        self.assertFalse(self.result["parameter_search"])
        self.assertEqual(self.result["independent_prospective_samples"], 0)
        self.assertEqual(json.loads(json.dumps(self.result)), self.result)
        for case in self.result["cases"]:
            self.assertNotIn("history", case)
            self.assertNotIn("selected_d2", case)

    def test_seeded_runner_is_reproducible_and_has_no_shared_mutable_output(self):
        actual = run_diagnostic("synthetic_pair_shrink", dict(SYNTHETIC_PARAMETERS))
        self.assertEqual(actual, self.result)
        actual["parameters"]["seed"] = 0
        actual["cases"].clear()
        fresh = run_diagnostic("synthetic_pair_shrink", dict(SYNTHETIC_PARAMETERS))
        self.assertEqual(fresh, self.result)

    def test_all_extra_missing_changed_and_wrongly_typed_parameters_are_blocked(self):
        defaults = dict(SYNTHETIC_PARAMETERS)
        invalid = [{}, {**defaults, "source": "official.csv"},
                   {**defaults, "seed": 20261019}, {**defaults, "cases_per_game": 1000000},
                   {**defaults, "cases_per_game": 0}, {**defaults, "tau": 0},
                   {**defaults, "window": 59}]
        for key in defaults:
            invalid.append({k: v for k, v in defaults.items() if k != key})
            for value in (True, str(defaults[key]), float(defaults[key]), None):
                invalid.append({**defaults, key: value})
        invalid.extend((None, list(defaults), SYNTHETIC_PARAMETERS))
        for parameters in invalid:
            with self.subTest(parameters=parameters), self.assertRaises(DiagnosticBlocked):
                run_diagnostic("synthetic_pair_shrink", parameters)

    def test_unknown_diagnostic_is_rejected_before_any_generation(self):
        with patch.object(experiments, "_synthetic_history", side_effect=AssertionError("must not execute")):
            for kind in ("", "grid_search", "locked_test", "SYNTHETIC_PAIR_SHRINK", None, True, []):
                with self.subTest(kind=kind), self.assertRaises(DiagnosticBlocked):
                    run_diagnostic(kind, dict(SYNTHETIC_PARAMETERS))

    def test_prospective_is_explicitly_blocked_without_forecast_or_samples(self):
        with patch.object(experiments, "_synthetic_history", side_effect=AssertionError("must not execute")):
            result = run_diagnostic("prospective_d2", {})
        self.assertEqual(result["status"], "BLOCKED_NOT_RUN")
        self.assertFalse(result["executed"])
        self.assertEqual(result["cases"], [])
        self.assertEqual(result["case_count"], 0)
        self.assertEqual(result["missing_requirements"], [
            "OFFICIAL_TARGET_ISSUE_AND_DEADLINE", "INDEPENDENT_PRE_DRAW_TSA_PROOF",
            "INDEPENDENT_FUTURE_ISSUES"])
        self.assertEqual((result["formal_A"], result["decision"]), (0, "NO_EDGE"))
        self.assertFalse(result["forecast_registered"])
        with self.assertRaises(DiagnosticBlocked):
            run_diagnostic("prospective_d2", {"issue": "2026123"})

    def test_implementation_imports_only_approved_pure_standard_library_modules(self):
        tree = ast.parse(inspect.getsource(experiments))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                       for alias in node.names)
        self.assertEqual(imports, {"__future__", "collections", "fractions", "itertools", "random", "types"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "__import__", "input"})
        # Any attempted historical access via ordinary built-in file I/O fails.
        with patch("builtins.open", side_effect=AssertionError("file access forbidden")):
            self.assertEqual(run_diagnostic("synthetic_pair_shrink", dict(SYNTHETIC_PARAMETERS)), self.result)


if __name__ == "__main__":
    unittest.main()
