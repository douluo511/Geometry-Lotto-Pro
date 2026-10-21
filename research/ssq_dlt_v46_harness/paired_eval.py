"""Prospective D2 evaluation arithmetic for V4.6 SHADOW research.

Inputs are caller-supplied D2 outcomes. This module DOES NOT verify official
lottery results, frozen forecast provenance, preregistration, or TSA existence.
It never grants formal A or a predictive-edge decision.
"""
from __future__ import annotations

from collections import defaultdict
from math import comb, sqrt


class EvaluationBlocked(ValueError):
    """Malformed or mixed-protocol evaluation data must fail closed."""


MODELS = (
    "02-HOT60", "03-EWMA", "04-SHRINKMIX", "05-PAIRWISE-D2",
    "06-STABILITY-CHALLENGER", "07-RANDOM-NULL",
)
NULL = "07-RANDOM-NULL"
FAIR_BASELINE = {"SSQ": 15 / 528, "DLT": 10 / 595}
FAMILY_SIZE = 12  # Exploratory arithmetic only; NOT formal family registration.


def exact_paired_upper_tail(wins: int, losses: int) -> float:
    """Exact one-sided conditional sign/McNemar p under discordant symmetry."""
    if (type(wins) is not int or type(losses) is not int
            or wins < 0 or losses < 0):
        raise EvaluationBlocked("INVALID_DISCORDANT_COUNTS")
    n = wins + losses
    if n == 0:
        return 1.0
    # Exact integer arithmetic avoids inaccurate normal approximations for rare D2.
    return sum(comb(n, k) for k in range(wins, n + 1)) / (1 << n)


def holm_adjust(pvalues: dict[str, float], family_size: int = FAMILY_SIZE) -> dict[str, float]:
    """Holm adjusted values; unfilled preregistered slots count as p=1.

    This is an exploratory 12-slot proxy, not verification of the
    legacy V4.5 preregistered hypothesis identities or multiplicity contract.
    """
    if (type(family_size) is not int or family_size < 1
            or not pvalues or len(pvalues) > family_size):
        raise EvaluationBlocked("INVALID_HOLM_FAMILY")
    if any(type(p) not in (float, int) or not 0 <= p <= 1 for p in pvalues.values()):
        raise EvaluationBlocked("INVALID_P_VALUE")
    sorted_items = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    adjusted, running = {}, 0.0
    for rank, (key, p) in enumerate(sorted_items):
        running = max(running, min(1.0, (family_size - rank) * p))
        adjusted[key] = running
    return adjusted


def _wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    radius = z * sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - radius), min(1.0, center + radius))


def evaluate_shadow_d2(rows: list[dict]) -> dict:
    """Pair every model with same-game, same-issue Random NULL D2.

    Every row needs {game, issue, scores}, containing all six model D2 bits.
    Treat outcomes as UNVERIFIED; only an independent audit can admit real
    prospective runs and validate exact precommitment of the formal family.
    """
    if not isinstance(rows, list) or not rows:
        raise EvaluationBlocked("EMPTY_STUDY")
    seen, grouped = set(), defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationBlocked("INVALID_RECORD")
        game, issue, scores = row.get("game"), row.get("issue"), row.get("scores")
        if game not in FAIR_BASELINE or not isinstance(issue, str) or not issue.isdigit():
            raise EvaluationBlocked("INVALID_GAME_OR_ISSUE")
        key = game, issue
        if key in seen:
            raise EvaluationBlocked("DUPLICATE_DRAW_CANNOT_INFLATE_SAMPLE")
        seen.add(key)
        if not isinstance(scores, dict) or set(scores) != set(MODELS):
            raise EvaluationBlocked("INCOMPLETE_MODEL_FAMILY")
        if any(type(value) is not int or value not in (0, 1) for value in scores.values()):
            raise EvaluationBlocked("INVALID_D2_BIT")
        grouped[game].append(scores)

    raw = {}
    observations = []
    for game in sorted(grouped):
        draws = grouped[game]
        count = len(draws)
        n_hits_null = sum(row[NULL] for row in draws)
        for model in MODELS:
            if model == NULL:
                continue
            hits = sum(row[model] for row in draws)
            wins = sum(row[model] == 1 and row[NULL] == 0 for row in draws)
            losses = sum(row[model] == 0 and row[NULL] == 1 for row in draws)
            p = exact_paired_upper_tail(wins, losses)
            identity = f"{game}:{model}"
            raw[identity] = p
            observations.append({
                "lottery": game, "model": model, "draws": count,
                "model_d2_hits": hits, "null_d2_hits": n_hits_null,
                "model_d2_rate": hits / count,
                "fair_d2_baseline": FAIR_BASELINE[game],
                "observed_minus_fair_baseline": hits / count - FAIR_BASELINE[game],
                "model_minus_null_rate": (wins - losses) / count,
                "discordant_wins": wins, "discordant_losses": losses,
                "matched_or_both_missed": count - wins - losses,
                "model_rate_wilson95": _wilson(hits, count),
                "paired_one_sided_p": p,
            })
    adjusted = holm_adjust(raw)
    for r in observations:
        r["exploratory_holm12_adjusted_p"] = adjusted[f"{r['lottery']}:{r['model']}"]
    return {
        "status": "SHADOW_ONLY", "formal_A": 0, "decision": "NO_EDGE",
        "family_size_for_exploratory_adjustment": FAMILY_SIZE,
        "hypotheses_tested": len(raw), "results": observations,
        "limitations": (
            "D2 input outcomes and pre-draw evidence are not verified here; "
            "historical exposed trials are not prospective; Holm-12 arithmetic "
            "is not proof of legacy preregistration, and none of these results "
            "authorizes A promotion or confirms better-than-random predictions."
        ),
    }
