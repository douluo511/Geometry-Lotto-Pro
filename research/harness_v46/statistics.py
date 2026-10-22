"""V4.7 SHADOW D2 statistics arithmetic; never verifies data or promotes a model.

The caller must supply an explicitly enumerated 12-hypothesis family. This
module deliberately labels that family UNVERIFIED: it cannot prove historical
registration, trusted pre-draw existence, or the authenticity of draw results.
"""
from __future__ import annotations

from math import exp, lgamma, log, log1p
from typing import Any

from .core import MODELS, RULES, GateError

class EvaluationBlocked(ValueError):
    """Malformed or mixed-protocol rows must fail closed."""


FAIR_D2 = {game: rules["d2"] for game, rules in RULES.items()}
DEFAULT_FAMILY_SIZE = 12


def _validate_binomial(k: int, n: int, p: float) -> None:
    if type(k) is not int or type(n) is not int or n < 0 or k < 0 or k > n:
        raise EvaluationBlocked("INVALID_BINOMIAL_COUNTS")
    if type(p) not in (int, float) or not 0 <= p <= 1:
        raise EvaluationBlocked("INVALID_BINOMIAL_PROBABILITY")


def _pmf(k: int, n: int, p: float) -> float:
    if p == 0:
        return 1.0 if k == 0 else 0.0
    if p == 1:
        return 1.0 if k == n else 0.0
    log_value = (lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
                 + k * log(p) + (n - k) * log1p(-p))
    return exp(log_value)


def exact_binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P[X >= k] for X~Binomial(n,p), using a stable recurrence."""
    _validate_binomial(k, n, p)
    if k == 0:
        return 1.0
    if p == 0:
        return 0.0
    if p == 1:
        return 1.0
    term = _pmf(k, n, p)
    total = term
    for x in range(k, n):
        term *= ((n - x) / (x + 1)) * (p / (1 - p))
        total += term
    return min(1.0, max(0.0, total))


def _lower_tail(k: int, n: int, p: float) -> float:
    """P[X <= k], using a downward recurrence."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p == 0:
        return 1.0
    if p == 1:
        return 0.0
    term = _pmf(k, n, p)
    total = term
    for x in range(k, 0, -1):
        term *= (x / (n - x + 1)) * ((1 - p) / p)
        total += term
    return min(1.0, max(0.0, total))


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided exact binomial interval via inversion of exact tail probabilities."""
    if type(confidence) not in (float, int) or not 0 < confidence < 1:
        raise EvaluationBlocked("INVALID_CONFIDENCE_LEVEL")
    _validate_binomial(k, n, 0.5)
    if n == 0:
        raise EvaluationBlocked("CI_REQUIRES_OBSERVATIONS")
    alpha = 1.0 - confidence
    if k == 0:
        lower = 0.0
    else:
        target = alpha / 2
        lo, hi = 0.0, 1.0
        for _ in range(64):
            mid = (lo + hi) / 2
            if exact_binomial_upper_tail(k, n, mid) < target:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2
    if k == n:
        upper = 1.0
    else:
        target = alpha / 2
        lo, hi = 0.0, 1.0
        for _ in range(64):
            mid = (lo + hi) / 2
            if _lower_tail(k, n, mid) > target:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2
    return lower, upper


def holm_adjust(pvalues: dict[str, float], family_ids: list[str]) -> dict[str, float]:
    """Holm step-down adjusted p-values over the exact named family, no implicit slots."""
    if (not isinstance(family_ids, list) or not family_ids
            or any(not isinstance(x, str) or not x for x in family_ids)
            or len(set(family_ids)) != len(family_ids)
            or not isinstance(pvalues, dict) or set(pvalues) != set(family_ids)):
        raise EvaluationBlocked("EXPLICIT_COMPLETE_HOLM_FAMILY_REQUIRED")
    for value in pvalues.values():
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise EvaluationBlocked("INVALID_P_VALUE")
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    m = len(family_ids)
    for rank, (hypothesis_id, pvalue) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * pvalue))
        adjusted[hypothesis_id] = running
    return adjusted


def _validate_family(family: list[dict[str, Any]], expected_size: int) -> list[dict[str, str]]:
    if type(expected_size) is not int or expected_size < 1:
        raise EvaluationBlocked("INVALID_EXPECTED_FAMILY_SIZE")
    if not isinstance(family, list) or len(family) != expected_size:
        raise EvaluationBlocked("FAMILY_SIZE_MISMATCH")
    clean = []
    seen_ids, seen_pairs = set(), set()
    for item in family:
        if not isinstance(item, dict) or set(item) != {"hypothesis_id", "lottery", "model"}:
            raise EvaluationBlocked("INVALID_HYPOTHESIS_SCHEMA")
        hid, game, model = item["hypothesis_id"], item["lottery"], item["model"]
        if not isinstance(hid, str) or not hid or game not in RULES or model not in MODELS:
            raise EvaluationBlocked("INVALID_HYPOTHESIS_IDENTITY")
        if hid in seen_ids or (game, model) in seen_pairs:
            raise EvaluationBlocked("DUPLICATE_HYPOTHESIS")
        seen_ids.add(hid)
        seen_pairs.add((game, model))
        clean.append({"hypothesis_id": hid, "lottery": game, "model": model})
    return sorted(clean, key=lambda x: x["hypothesis_id"])


def evaluate_shadow_d2(
    rows: list[dict[str, Any]],
    family: list[dict[str, str]],
    *,
    expected_family_size: int = DEFAULT_FAMILY_SIZE,
) -> dict[str, Any]:
    """Evaluate baseline + same-draw NULL arithmetic without asserting data provenance.

    Each row is one unique (lottery, issue) and contains D2 bits for every model:
    {"lottery":"SSQ","issue":"2026121","scores":{"hot60":0,...,"random_null":1}}.
    The family must explicitly map all hypotheses. Candidate p_joint is the
    intersection-union p-value max(p_exact_vs_fair_baseline, p_exact_paired_vs_NULL).
    """
    hypotheses = _validate_family(family, expected_family_size)
    if not isinstance(rows, list) or not rows:
        raise EvaluationBlocked("EMPTY_STUDY")
    seen = set()
    by_game: dict[str, list[dict[str, Any]]] = {g: [] for g in RULES}
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationBlocked("INVALID_DRAW_ROW")
        game, issue, scores = row.get("lottery"), row.get("issue"), row.get("scores")
        if game not in RULES or not isinstance(issue, str) or not issue.isdigit():
            raise EvaluationBlocked("INVALID_DRAW_IDENTITY")
        key = (game, issue)
        if key in seen:
            raise EvaluationBlocked("DUPLICATE_DRAW")
        seen.add(key)
        if not isinstance(scores, dict) or set(scores) != set(MODELS):
            raise EvaluationBlocked("INCOMPLETE_MODEL_D2_VECTOR")
        if any(type(value) is not int or value not in (0, 1) for value in scores.values()):
            raise EvaluationBlocked("INVALID_D2_BIT")
        by_game[game].append({"issue": issue, "scores": scores})

    p_joint: dict[str, float] = {}
    results = []
    for hyp in hypotheses:
        hid, game, model = hyp["hypothesis_id"], hyp["lottery"], hyp["model"]
        draws = sorted(by_game[game], key=lambda x: int(x["issue"]))
        n = len(draws)
        if n == 0:
            result = {
                **hyp, "draws": 0, "hits": 0, "d2_rate": None,
                "fair_baseline": FAIR_D2[game], "rate_difference_vs_fair": None,
                "p_exact_vs_fair": 1.0, "paired_wins_vs_null": 0,
                "paired_losses_vs_null": 0, "p_exact_paired_vs_null": 1.0,
                "p_joint_intersection_union": 1.0, "d2_rate_exact_ci95": None,
                "paired_rate_difference_ci95_conservative": None,
                "status": "NO_DATA",
            }
            p_joint[hid] = 1.0
            results.append(result)
            continue
        hits = sum(x["scores"][model] for x in draws)
        rate = hits / n
        p_base = exact_binomial_upper_tail(hits, n, FAIR_D2[game])
        ci_rate = clopper_pearson(hits, n, 0.95)
        if model == "random_null":
            wins = losses = 0
            p_pair = 1.0
            paired_ci = None
        else:
            wins = sum(x["scores"][model] == 1 and x["scores"]["random_null"] == 0 for x in draws)
            losses = sum(x["scores"][model] == 0 and x["scores"]["random_null"] == 1 for x in draws)
            discordant = wins + losses
            p_pair = exact_binomial_upper_tail(wins, discordant, 0.5)
            # Bonferroni combination of 97.5% exact marginal intervals yields
            # a conservative >=95% interval for (wins-losses)/n.
            win_ci = clopper_pearson(wins, n, 0.975)
            loss_ci = clopper_pearson(losses, n, 0.975)
            paired_ci = (max(-1.0, win_ci[0] - loss_ci[1]),
                         min(1.0, win_ci[1] - loss_ci[0]))
        joint = max(p_base, p_pair)
        p_joint[hid] = joint
        results.append({
            **hyp, "draws": n, "hits": hits, "d2_rate": rate,
            "fair_baseline": FAIR_D2[game], "rate_difference_vs_fair": rate - FAIR_D2[game],
            "p_exact_vs_fair": p_base, "paired_wins_vs_null": wins,
            "paired_losses_vs_null": losses, "p_exact_paired_vs_null": p_pair,
            "p_joint_intersection_union": joint, "d2_rate_exact_ci95": ci_rate,
            "paired_rate_difference_ci95_conservative": paired_ci,
            "status": "UNVERIFIED_SHADOW_ARITHMETIC",
        })
    adjusted = holm_adjust(p_joint, [x["hypothesis_id"] for x in hypotheses])
    for result in results:
        result["holm_adjusted_p_unverified_family"] = adjusted[result["hypothesis_id"]]
    return {
        "status": "SHADOW_ONLY", "formal_A": 0, "decision": "NO_EDGE",
        "preregistration_verified": False,
        "family_status": "CALLER_SUPPLIED_UNVERIFIED",
        "family_size": expected_family_size, "hypotheses_evaluated": len(hypotheses),
        "results": results,
        "limitations": [
            "Input D2 bits, frozen forecasts, official outcomes and trusted pre-draw seals are not authenticated here.",
            "The supplied family is not proven to match the legacy registered 12-hypothesis family.",
            "The challenger remains unregistered; this arithmetic cannot promote a model or claim D2_EDGE_CONFIRMED.",
        ],
    }
