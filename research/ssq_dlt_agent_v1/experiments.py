"""Bounded synthetic diagnostics, isolated from all lottery data and models.

The caller must record the fixed hypothesis and parameters before invoking
``run_diagnostic``. This pure runner neither registers forecasts nor reads or
writes files. A diagnostic PASS establishes an algebra/implementation property;
it is never evidence of a lottery hit rate or predictive edge.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from itertools import combinations
import random
from types import MappingProxyType


class DiagnosticBlocked(ValueError):
    """An unapproved diagnostic or parameter search was requested."""


SYNTHETIC_PARAMETERS = MappingProxyType({
    "window": 60, "tau": 200, "seed": 20261018, "cases_per_game": 20,
})
_RULES = MappingProxyType({"SSQ": (33, 6, 16, 1), "DLT": (35, 5, 12, 2)})
_CLASSIFICATION = "SYNTHETIC_DIAGNOSTIC_NOT_HIT_RATE_EVIDENCE"
_TIE_RULE = ("higher_pair_count", "higher_marginal_sum", "ascending_pair")


def _shrunken_pair_probability(pair_count: int, window: int, tau: int,
                               prior: Fraction) -> Fraction:
    """Exact posterior mean for a shared uniform pair prior."""
    return (Fraction(pair_count) + tau * prior) / (window + tau)


def _pair_rankings(fronts: tuple[tuple[int, ...], ...], *, upper: int,
                   draw_count: int, tau: int) -> tuple:
    """Rank every legal pair with identical, explicit secondary tie rules."""
    pairs = tuple(combinations(range(1, upper + 1), 2))
    counts = Counter(pair for front in fronts for pair in combinations(front, 2))
    marginal = Counter(number for front in fronts for number in front)
    prior = Fraction(draw_count * (draw_count - 1), upper * (upper - 1))
    scores = {pair: _shrunken_pair_probability(counts[pair], len(fronts), tau, prior)
              for pair in pairs}
    raw = tuple(sorted(pairs, key=lambda pair:
                       (-counts[pair], -sum(marginal[n] for n in pair), pair)))
    shrunk = tuple(sorted(pairs, key=lambda pair:
                          (-scores[pair], -sum(marginal[n] for n in pair), pair)))
    return raw, shrunk, counts, marginal, scores


def _synthetic_history(game: str, rng: random.Random, window: int) -> tuple[dict, ...]:
    """Create legal synthetic front/back draws with visibly synthetic IDs."""
    upper, count, back_upper, back_count = _RULES[game]
    return tuple({
        "game": game,
        "issue": f"SYNTHETIC-{index:04d}",
        "front": tuple(sorted(rng.sample(range(1, upper + 1), count))),
        "back": tuple(sorted(rng.sample(range(1, back_upper + 1), back_count))),
    } for index in range(window))


def _legal_history(history: tuple[dict, ...], game: str, window: int) -> bool:
    upper, count, back_upper, back_count = _RULES[game]
    return len(history) == window and all(
        row["game"] == game and row["issue"].startswith("SYNTHETIC-")
        and all(len(values) == required and len(set(values)) == required
                and tuple(sorted(values)) == values
                and all(type(n) is int and 1 <= n <= limit for n in values)
                for values, required, limit in (
                    (row["front"], count, upper), (row["back"], back_count, back_upper)))
        for row in history)


def _case(game: str, index: int, history: tuple[dict, ...], tau: int) -> dict:
    upper, count, _, _ = _RULES[game]
    fronts = tuple(row["front"] for row in history)
    raw, shrunk, counts, _, scores = _pair_rankings(
        fronts, upper=upper, draw_count=count, tau=tau)
    denominator = len(fronts) + tau
    # Adjacent comparisons cover the entire sorted order, including every tie.
    # Positive affine transformation preserves count order; identical tie rules
    # then preserve the complete total order, not merely its first element.
    affine_exact = all(
        scores[a] - scores[b] == Fraction(counts[a] - counts[b], denominator)
        for a, b in zip(raw, raw[1:]))
    checks = {
        "legal_synthetic_history": _legal_history(history, game, SYNTHETIC_PARAMETERS["window"]),
        "exact_fraction_scores": all(type(value) is Fraction for value in scores.values()),
        "affine_identity_for_full_rank": affine_exact,
        "full_pair_rank_equal": raw == shrunk,
        "selected_d2_equal": raw[0] == shrunk[0],
    }
    return {"case_id": f"{game}-SYNTHETIC-{index:02d}", "game": game,
            "history_size": len(history), "legal_pair_count": len(raw),
            "adjacent_comparisons": len(raw) - 1,
            "checks": checks, "passed": all(checks.values())}


def _tie_counterexample(game: str) -> dict:
    """Show why discarding the marginal tie rule can create a false change."""
    upper, count, _, _ = _RULES[game]
    blocks = ((1, 2, 4, 5, 6, 7), (1, 3, 8, 9, 10, 11),
              (3, 12, 13, 14, 15, 16))
    fronts = tuple(block[:count] for block in blocks for _ in range(20))
    raw, shrunk, counts, marginal, scores = _pair_rankings(
        fronts, upper=upper, draw_count=count, tau=SYNTHETIC_PARAMETERS["tau"])
    ascending_only = min(scores, key=lambda pair: (-scores[pair], pair))
    marginal_sum = lambda pair: sum(marginal[n] for n in pair)
    checks = {
        "same_tie_rule_preserves_d2": raw[0] == shrunk[0],
        "ascending_only_shortcut_changes_d2": ascending_only != raw[0],
        "competing_pairs_have_equal_pair_count": counts[ascending_only] == counts[raw[0]],
        "marginal_rule_resolves_tie": marginal_sum(raw[0]) > marginal_sum(ascending_only),
    }
    # Report counts and checks, never synthetic pairs as suggested lottery picks.
    return {"example_id": f"{game}-SYNTHETIC-MARGINAL-TIE", "game": game,
            "history_size": len(fronts), "tied_pair_count": counts[raw[0]],
            "preserved_selection_marginal_sum": marginal_sum(raw[0]),
            "ascending_only_selection_marginal_sum": marginal_sum(ascending_only),
            "checks": checks, "passed": all(checks.values()),
            "interpretation": "A change caused by dropping a tie rule is not shrinkage improvement."}


def _boundary(kind: str, parameters: dict) -> dict:
    return {
        "schema": "ssq-dlt-agent-diagnostic-1", "kind": kind,
        "parameters": dict(parameters), "classification": _CLASSIFICATION,
        "historical_outcomes_used": False, "locked_test_rescored": False,
        "independent_prospective_samples": 0, "forecast_registered": False,
        "parameter_search": False, "formal_A": 0, "decision": "NO_EDGE",
    }


def run_diagnostic(kind: str, parameters: dict) -> dict:
    """Run one approved fixed-cost diagnostic, or report prospective blockage.

    ``synthetic_pair_shrink`` accepts exactly ``SYNTHETIC_PARAMETERS``. No
    alternative seed, window, prior weight, case count, or extra input is
    admitted. ``prospective_d2`` accepts only an empty dict and cannot execute:
    this isolated runner has no official target/deadline, trusted timestamp
    proof, or independent future observations.
    """
    if type(kind) is not str or kind not in {"synthetic_pair_shrink", "prospective_d2"}:
        raise DiagnosticBlocked("UNAPPROVED_DIAGNOSTIC_KIND")
    if type(parameters) is not dict:
        raise DiagnosticBlocked("EXACT_PARAMETER_DICT_REQUIRED")
    if kind == "prospective_d2":
        if parameters:
            raise DiagnosticBlocked("PROSPECTIVE_PARAMETERS_NOT_ADMITTED")
        return {**_boundary(kind, parameters), "status": "BLOCKED_NOT_RUN",
                "executed": False, "case_count": 0, "cases": [],
                "missing_requirements": [
                    "OFFICIAL_TARGET_ISSUE_AND_DEADLINE",
                    "INDEPENDENT_PRE_DRAW_TSA_PROOF",
                    "INDEPENDENT_FUTURE_ISSUES",
                ], "reason": "No actual forecast or future issue may be invented."}
    if (set(parameters) != set(SYNTHETIC_PARAMETERS)
            or any(type(parameters[key]) is not int
                   or parameters[key] != value
                   for key, value in SYNTHETIC_PARAMETERS.items())):
        raise DiagnosticBlocked("FIXED_SYNTHETIC_PARAMETERS_REQUIRED_NO_SEARCH")
    rng = random.Random(parameters["seed"])
    cases = [
        _case(game, index, _synthetic_history(game, rng, parameters["window"]), parameters["tau"])
        for game in _RULES
        for index in range(1, parameters["cases_per_game"] + 1)
    ]
    examples = [_tie_counterexample(game) for game in _RULES]
    passed_cases = sum(case["passed"] for case in cases)
    passed = passed_cases == len(cases) and all(example["passed"] for example in examples)
    return {
        **_boundary(kind, parameters), "status": "PASS" if passed else "FAIL",
        "executed": True, "passed": passed, "case_count": len(cases),
        "passed_cases": passed_cases, "failed_cases": len(cases) - passed_cases,
        "cases": cases, "tie_counterexamples": examples,
        "proof": {
            "uniform_pair_prior": {game: str(Fraction(count * (count - 1), upper * (upper - 1)))
                                   for game, (upper, count, _, _) in _RULES.items()},
            "shrink_formula": "q(pair)=(count(pair)+tau*p0)/(window+tau)",
            "difference_identity": "q(a)-q(b)=(count(a)-count(b))/(window+tau)",
            "positive_affine_slope": str(Fraction(1, parameters["window"] + parameters["tau"])),
            "raw_and_shrunk_tie_order": list(_TIE_RULE),
            "conclusion": "Uniform-prior shrinkage with identical tie rules preserves every pair rank and selected D2.",
        },
        "interpretation": "Synthetic algebra checks provide no hit-rate evidence; no predictive improvement is established.",
    }
