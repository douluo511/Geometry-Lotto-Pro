"""Research-only D1-D5 scoring and paired D2 comparison.

This module never verifies official source, pre-draw timestamp, authorization,
or model provenance. Its output MUST NOT be counted as formal A evidence.
"""
from __future__ import annotations

from math import comb, isfinite

RULES = {"SSQ": (33, 6), "DLT": (35, 5)}


class AdmissionBlocked(ValueError):
    """Fail closed when an expected issue/model/version is missing or malformed."""


def validate_numbers(numbers: object, count: int, upper: int) -> None:
    if (
        type(numbers) is not list
        or len(numbers) != count
        or any(type(n) is not int or not 1 <= n <= upper for n in numbers)
        or len(set(numbers)) != count
    ):
        raise AdmissionBlocked("INVALID_NUMBERS")


def score_d1_d5(game: str, ranked_five: list[int], official_front: list[int]) -> dict:
    if type(game) is not str or game not in RULES:
        raise AdmissionBlocked("UNKNOWN_GAME")
    upper, drawn = RULES[game]
    validate_numbers(ranked_five, 5, upper)
    validate_numbers(official_front, drawn, upper)
    winning = set(official_front)
    return {
        "D" + str(k): {
            "hits": len(set(ranked_five[:k]) & winning),
            "full": int(set(ranked_five[:k]).issubset(winning)),
            "p0": comb(drawn, k) / comb(upper, k),
        }
        for k in range(1, 6)
    }


def paired_exact_one_sided(wins: int, losses: int) -> float:
    """Exact one-sided discordant-pair test (H1: model > null).

    Ties are deliberately excluded from this conditional test.
    """
    if (type(wins) is not int or type(losses) is not int
            or wins < 0 or losses < 0):
        raise AdmissionBlocked("INVALID_PAIR_COUNTS")
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def evaluate_registered(
    game: str,
    rows: list[dict],
    expected_issues: list[str],
    model_versions: dict[str, str],
    *,
    null_model: str = "M07-NULL-SHADOW",
    tau: float = 200.0,
) -> dict:
    """Score only the complete preregistered issue/model rectangle.

    Each row: {game, issue, draw_front, models:
                  {model_id: {version, ranked_front}}}
    The calling admission service must independently verify source, pre-draw
    freeze and eligibility. This function returns RESEARCH_ONLY regardless
    of input declarations.
    """
    if type(game) is not str or game not in RULES:
        raise AdmissionBlocked("UNKNOWN_GAME")
    if (type(tau) not in (float, int) or not isfinite(tau) or tau <= 0):
        raise AdmissionBlocked("INVALID_SHRINKAGE")
    if (type(expected_issues) is not list or not expected_issues
            or any(type(i) is not str or not i for i in expected_issues)
            or len(set(expected_issues)) != len(expected_issues)):
        raise AdmissionBlocked("INVALID_EXPECTED_ISSUES")
    if (type(model_versions) is not dict or null_model not in model_versions
            or len(model_versions) < 2
            or any(type(m) is not str or not m or
                   type(v) is not str or not v
                   for m, v in model_versions.items())):
        raise AdmissionBlocked("INVALID_MODEL_REGISTRY")
    if type(rows) is not list or len(rows) != len(expected_issues):
        raise AdmissionBlocked("MISSING_OR_EXTRA_ISSUES")
    ids = [r.get("issue") if type(r) is dict else None for r in rows]
    if (any(type(i) is not str or not i for i in ids)
            or len(set(ids)) != len(ids) or set(ids) != set(expected_issues)):
        raise AdmissionBlocked("MISSING_OR_DUPLICATE_ISSUES")

    outcomes: dict[str, list[int]] = {m: [] for m in model_versions}
    counts: dict[str, dict[str, int]] = {
        m: {"D" + str(k): 0 for k in range(1, 6)}
        for m in model_versions
    }
    n = len(rows)
    for row in rows:
        if (row.get("game") != game or type(row.get("models")) is not dict
                or set(row["models"]) != set(model_versions)):
            raise AdmissionBlocked("WRONG_GAME_OR_MISSING_MODEL")
        for model in model_versions:
            value = row["models"][model]
            if (type(value) is not dict or
                    value.get("version") != model_versions[model]):
                raise AdmissionBlocked("VERSION_MISMATCH")
            score = score_d1_d5(game, value.get("ranked_front"), row.get("draw_front"))
            outcomes[model].append(score["D2"]["full"])
            for k in range(1, 6):
                key = "D" + str(k)
                counts[model][key] += score[key]["full"]

    upper, drawn = RULES[game]
    p0 = comb(drawn, 2) / comb(upper, 2)
    ranking = []
    comparison = []
    for model in sorted(model_versions):
        hit = sum(outcomes[model])
        ranking.append({
            "model": model,
            "version": model_versions[model],
            "n": n,
            "D2_full": hit,
            "D2_rate": hit / n,
            "D2_excess_vs_p0": hit / n - p0,
            "D2_shrunk_research": (hit + tau * p0) / (n + tau),
            "D1_D5_full": counts[model],
        })
        if model != null_model:
            wins = sum(x == 1 and y == 0
                       for x, y in zip(outcomes[model], outcomes[null_model]))
            losses = sum(x == 0 and y == 1
                         for x, y in zip(outcomes[model], outcomes[null_model]))
            comparison.append({
                "model": model,
                "null_model": null_model,
                "wins": wins,
                "losses": losses,
                "ties": n - wins - losses,
                "paired_delta": (wins - losses) / n,
                "p_one_sided_exploratory": paired_exact_one_sided(wins, losses),
            })

    return {
        "game": game,
        "n": n,
        "D2_random_p0": p0,
        "research_ranking": sorted(
            ranking, key=lambda r: (-r["D2_shrunk_research"], r["model"])),
        "pairwise_vs_null": comparison,
        "admission": "RESEARCH_ONLY",
        "formal_a_samples": 0,
        "formal_winner": None,
        "decision": "NO_EDGE",
        "limitations": [
            "No official-source or as-of verification",
            "No external pre-draw TSA or 01/04 digital authorization",
            "No preregistered formal 12-family Holm or independent replication",
        ],
    }
