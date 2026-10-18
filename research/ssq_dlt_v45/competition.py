"""Research-only paired D2 replay; caller declarations never establish formal A.

All predictions must be hash-bound to an independently supplied freeze index.
The complete prospective plan is mandatory, including periods with poor results.
The formal preregistered 12-family, 01--04 authorization, external TSA and
independent replication remain BLOCKED even when internal checks pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import comb, isfinite

from .models import (DEFAULT_SEED, MODEL_VERSIONS, NULL_MODEL, PRIMARY_MODEL, REGISTRY_SHA256,
                     RULES, ModelBlocked, digest, validate_numbers, validate_prediction)


class CompetitionBlocked(ValueError):
    """Incomplete periods, changed identities, chronology or hash mismatch."""


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise CompetitionBlocked("TIMEZONE_AWARE_TIME_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise CompetitionBlocked("TIMEZONE_AWARE_TIME_REQUIRED") from exc


def paired_exact_one_sided(wins: int, losses: int) -> float:
    """Exact conditional binomial test on discordant pairs; H1 model > null."""
    if type(wins) is not int or type(losses) is not int or min(wins, losses) < 0:
        raise CompetitionBlocked("INVALID_PAIR_COUNTS")
    n = wins + losses
    if n == 0:
        return 1.0
    # Integer arithmetic avoids unstable factorial and huge-int float conversion.
    return sum(comb(n, k) for k in range(wins, n + 1)) / (1 << n)


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p values for the supplied RESEARCH family only."""
    if (type(pvalues) is not dict or not pvalues
            or any(type(key) is not str or not key or type(p) not in (float, int)
                   or not isfinite(p) or not 0 <= p <= 1
                   for key, p in pvalues.items())):
        raise CompetitionBlocked("INVALID_HOLM_FAMILY")
    ordered = sorted(pvalues, key=lambda key: (pvalues[key], key))
    result, maximum, size = {}, 0.0, len(ordered)
    for rank, key in enumerate(ordered):
        maximum = max(maximum, (size - rank) * pvalues[key])
        result[key] = min(1.0, maximum)
    return result


def make_plan(game: str, expected_issues: list[str], registered_at: str,
              independent_series_id: str, *, seed: int = DEFAULT_SEED) -> dict:
    """Create an internal research plan; save its SHA externally before outcomes."""
    if type(game) is not str or game not in RULES:
        raise CompetitionBlocked("UNKNOWN_GAME")
    if (type(expected_issues) is not list or not expected_issues
            or any(type(issue) is not str or not issue.isascii() or not issue.isdigit()
                   or int(issue) <= 0 for issue in expected_issues)
            or len(set(expected_issues)) != len(expected_issues)
            or len({len(issue) for issue in expected_issues}) != 1
            or expected_issues != sorted(expected_issues, key=int)):
        raise CompetitionBlocked("INDEPENDENT_NUMERIC_ISSUE_PLAN_REQUIRED")
    if type(independent_series_id) is not str or not independent_series_id.strip():
        raise CompetitionBlocked("INDEPENDENT_SERIES_ID_REQUIRED")
    if type(seed) is not int or seed < 0:
        raise CompetitionBlocked("FIXED_NULL_SEED_REQUIRED")
    _time(registered_at)
    return {"schema": "ssq-dlt-v45-research-plan-1", "game": game,
            "expected_issues": list(expected_issues), "registered_at": registered_at,
            "independent_series_id": independent_series_id,
            "registry_sha256": REGISTRY_SHA256,
            "model_versions": dict(MODEL_VERSIONS), "primary_model": PRIMARY_MODEL,
            "null_model": NULL_MODEL, "alpha": 0.05,
            "seed": seed,
            "family": "RESEARCH_FOUR_VS_SAME_ISSUE_NULL_D2"}


def evaluate_registered(game: str, rows: list[dict], plan: dict,
                        frozen_hashes: dict[str, str], *, plan_sha256: str) -> dict:
    """Replay an exact issue/model rectangle fixed before any included outcome.

    Rows: game, issue, prediction (generate output), frozen_at, draw_at,
    draw_front, draw_back. frozen_hashes must come from the append-only ledger,
    not the row payload. Neither local hashes nor self-reported times are TSA.
    """
    if type(plan) is not dict or digest(plan) != plan_sha256:
        raise CompetitionBlocked("PREREGISTERED_PLAN_HASH_MISMATCH")
    expected_plan = make_plan(game, plan.get("expected_issues"), plan.get("registered_at"),
                              plan.get("independent_series_id"), seed=plan.get("seed"))
    if plan != expected_plan:
        raise CompetitionBlocked("REGISTRY_OR_FAMILY_PLAN_REPLACED")
    issues = plan["expected_issues"]
    if (type(rows) is not list or len(rows) != len(issues)
            or any(type(row) is not dict for row in rows)):
        raise CompetitionBlocked("MISSING_OR_EXTRA_ISSUES")
    ids = [row.get("issue") for row in rows]
    if (any(type(issue) is not str for issue in ids)
            or len(set(ids)) != len(ids) or set(ids) != set(issues)):
        raise CompetitionBlocked("MISSING_OR_DUPLICATE_ISSUES")
    if type(frozen_hashes) is not dict or set(frozen_hashes) != set(issues):
        raise CompetitionBlocked("COMPLETE_EXTERNAL_FREEZE_INDEX_REQUIRED")
    front_upper, front_count, back_upper, back_count = RULES[game]
    outcomes = {model: [] for model in MODEL_VERSIONS}
    totals = {model: {f"D{k}": 0 for k in range(1, 6)} for model in MODEL_VERSIONS}
    draws_seen = set()
    previous_draw = None
    period_scores = []
    ordered_rows = sorted(rows, key=lambda row: int(row["issue"]))
    for row in ordered_rows:
        if row.get("game") != game:
            raise CompetitionBlocked("WRONG_GAME")
        prediction = row.get("prediction")
        try:
            validate_prediction(prediction)
            validate_numbers(row.get("draw_front"), front_count, front_upper)
            validate_numbers(row.get("draw_back"), back_count, back_upper)
        except ModelBlocked as exc:
            raise CompetitionBlocked(str(exc)) from exc
        if prediction["game"] != game or prediction["issue"] != row["issue"]:
            raise CompetitionBlocked("PREDICTION_GAME_OR_ISSUE_MISMATCH")
        if prediction["seed"] != plan["seed"]:
            raise CompetitionBlocked("RANDOM_NULL_SEED_CHANGED_AFTER_PREREGISTRATION")
        if digest(prediction) != frozen_hashes[row["issue"]]:
            raise CompetitionBlocked("FORECAST_REPLACED_AFTER_FREEZE")
        frozen, draw_at = _time(row.get("frozen_at")), _time(row.get("draw_at"))
        if not _time(plan["registered_at"]) <= frozen < draw_at:
            raise CompetitionBlocked("F01_PLAN_OR_PREDICTION_AFTER_DRAW")
        if draw_at in draws_seen or (previous_draw is not None and draw_at <= previous_draw):
            raise CompetitionBlocked("INDEPENDENT_DISTINCT_DRAW_PERIODS_REQUIRED")
        draws_seen.add(draw_at)
        previous_draw = draw_at
        official = set(row["draw_front"])
        per_model = {}
        for model, candidate in prediction["models"].items():
            values = {}
            for k in range(1, 6):
                hit = len(set(candidate["dan"][str(k)]) & official)
                full = int(hit == k)
                values[f"D{k}"] = {"hits": hit, "full": full,
                                     "p0": comb(front_count, k) / comb(front_upper, k)}
                totals[model][f"D{k}"] += full
            outcomes[model].append(values["D2"]["full"])
            per_model[model] = values
        period_scores.append({"issue": row["issue"], "models": per_model})
    n = len(rows)
    comparisons = []
    for model in MODEL_VERSIONS:
        if model == NULL_MODEL:
            continue
        pairs = list(zip(outcomes[model], outcomes[NULL_MODEL]))
        wins = sum(x == 1 and y == 0 for x, y in pairs)
        losses = sum(x == 0 and y == 1 for x, y in pairs)
        comparisons.append({"model": model, "null_model": NULL_MODEL,
                            "wins": wins, "losses": losses, "ties": n - wins - losses,
                            "paired_delta": (wins - losses) / n,
                            "p_one_sided": paired_exact_one_sided(wins, losses)})
    adjusted = holm_adjust({row["model"]: row["p_one_sided"] for row in comparisons})
    for comparison in comparisons:
        comparison["p_holm_research"] = adjusted[comparison["model"]]
        comparison["reject_research_only"] = adjusted[comparison["model"]] <= plan["alpha"]
    return {"game": game, "n": n, "issues": issues,
            "D2_random_p0": comb(front_count, 2) / comb(front_upper, 2),
            "plan_sha256": plan_sha256, "registry_sha256": REGISTRY_SHA256,
            "independent_series_id": plan["independent_series_id"],
            "period_scores": period_scores,
            "D1_D5_full": totals, "pairwise_vs_null": comparisons,
            "holm_scope": "RESEARCH_FOUR_VS_SAME_ISSUE_NULL_D2",
            "formal_12_family": "BLOCKED_MISSING_REGISTERED_12_FAMILY_AND_INDEPENDENT_ADMISSION",
            "prospective_status": "INTERNAL_CHRONOLOGY_ONLY_EXTERNAL_TSA_REQUIRED",
            "primary_model": PRIMARY_MODEL, "formal_winner": None,
            "admission": "RESEARCH_ONLY", "formal_A": 0, "decision": "NO_EDGE"}
