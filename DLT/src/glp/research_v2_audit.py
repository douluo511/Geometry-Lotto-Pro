from __future__ import annotations

import random
import statistics
from typing import Any

from .constants import PROMOTION_POLICY
from .domain import Draw
from .evidence import bootstrap_ci, holm, permutation_p
from .research_v2 import FEATURE_NAMES, feature_map
from .util import sha256_json, utc_now


ALLOWED_DECISIONS = ("KEEP_CANDIDATE", "DEAD_PATH", "NOT_VERIFIED")


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    if area == "front":
        return draw.front
    if area == "back":
        return draw.back
    raise ValueError(f"unknown area: {area}")


def _meta(area: str) -> tuple[int, int]:
    if area == "front":
        return (35, 5)
    if area == "back":
        return (12, 2)
    raise ValueError(f"unknown area: {area}")


def _recall(ranking: list[int], actual: tuple[int, ...], k: int) -> float:
    return len(set(ranking[:k]) & set(actual)) / float(k)


def _random_ranking(max_n: int, seed_material: Any) -> list[int]:
    seed = int(sha256_json(seed_material)[:16], 16)
    rng = random.Random(seed)
    values = list(range(1, max_n + 1))
    rng.shuffle(values)
    return values


def walk_forward_feature_gains(
    draws: list[Draw],
    area: str,
    *,
    eval_points: int,
    seeds: tuple[int, ...] | None = None,
) -> dict[str, list[float]]:
    """
    Evaluate each raw V2 feature strictly out-of-sample.

    A feature never sees the target draw: feature_map receives draws[:target_index].
    Gain is top-k recall minus the average same-target deterministic uniform-random
    ranking recall across preregistered seeds.
    """
    if eval_points <= 0:
        raise ValueError("eval_points must be positive")
    if len(draws) < 121:
        raise ValueError("feature audit requires at least 121 draws")
    max_n, pick = _meta(area)
    seeds = tuple(seeds or PROMOTION_POLICY["seeds"])
    if not seeds:
        raise ValueError("at least one random-baseline seed is required")

    start = max(120, len(draws) - eval_points)
    gains = {name: [] for name in FEATURE_NAMES}
    for target_index in range(start, len(draws)):
        history = draws[:target_index]
        features = feature_map(history, area)
        actual = _area(draws[target_index], area)
        random_recalls = [
            _recall(
                _random_ranking(
                    max_n,
                    ["dlt-v2-feature-audit", area, seed, draws[target_index].issue],
                ),
                actual,
                pick,
            )
            for seed in seeds
        ]
        random_recall = statistics.mean(random_recalls)
        for feature_index, name in enumerate(FEATURE_NAMES):
            ranking = sorted(
                range(1, max_n + 1),
                key=lambda number: (-features[number][feature_index], number),
            )
            gains[name].append(_recall(ranking, actual, pick) - random_recall)
    return gains


def _decision(
    mean_gain: float,
    ci_low: float,
    ci_high: float,
    holm_reject_null: bool,
) -> str:
    if mean_gain > 0.0 and ci_low > 0.0 and holm_reject_null:
        return "KEEP_CANDIDATE"
    if mean_gain < 0.0 and ci_high < 0.0:
        return "DEAD_PATH"
    return "NOT_VERIFIED"


def _summarize_area(
    gains: dict[str, list[float]],
    area: str,
    *,
    alpha: float,
    bootstrap_rounds: int,
    permutation_rounds: int,
) -> dict[str, Any]:
    pvalues = {
        name: permutation_p(
            values,
            rounds=permutation_rounds,
            seed=23000 + index + (0 if area == "front" else 1000),
        )
        for index, (name, values) in enumerate(gains.items())
    }
    corrected = holm(pvalues, alpha)
    features: dict[str, Any] = {}
    for index, name in enumerate(FEATURE_NAMES):
        values = gains[name]
        lo, hi = bootstrap_ci(
            values,
            rounds=bootstrap_rounds,
            seed=21000 + index + (0 if area == "front" else 1000),
        )
        mean_gain = statistics.mean(values) if values else 0.0
        decision = _decision(mean_gain, lo, hi, bool(corrected[name]))
        features[name] = {
            "n": len(values),
            "mean_recall_gain_vs_random": mean_gain,
            "bootstrap95": [lo, hi],
            "permutation_p": pvalues[name],
            "holm_reject_null": bool(corrected[name]),
            "decision": decision,
        }
    return {
        "area": area,
        "features": features,
        "random_baseline": "same-target deterministic uniform rankings",
    }


def audit_feature_utility(
    draws: list[Draw],
    *,
    eval_points: int = 360,
    alpha: float | None = None,
    bootstrap_rounds: int | None = None,
    permutation_rounds: int | None = None,
) -> dict[str, Any]:
    """
    Research-only shadow audit.

    KEEP_CANDIDATE means a raw feature survived same-target OOS random-baseline,
    bootstrap lower bound, permutation test and Holm correction in that area.
    It does NOT prove the combined Ridge model has predictive edge.

    DEAD_PATH requires the entire bootstrap interval to be below zero.
    Everything else is NOT_VERIFIED.
    """
    if len(draws) < 121:
        raise ValueError("feature audit requires at least 121 draws")
    for draw in draws:
        draw.validate()
    if draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("draws must be chronological")
    if len({draw.issue for draw in draws}) != len(draws):
        raise ValueError("duplicate issue in feature audit")

    alpha = float(alpha if alpha is not None else PROMOTION_POLICY["alpha"])
    bootstrap_rounds = int(
        bootstrap_rounds if bootstrap_rounds is not None
        else PROMOTION_POLICY["bootstrap_rounds"]
    )
    permutation_rounds = int(
        permutation_rounds if permutation_rounds is not None
        else PROMOTION_POLICY["permutation_rounds"]
    )

    areas: dict[str, Any] = {}
    for area in ("front", "back"):
        gains = walk_forward_feature_gains(
            draws,
            area,
            eval_points=eval_points,
        )
        areas[area] = _summarize_area(
            gains,
            area,
            alpha=alpha,
            bootstrap_rounds=bootstrap_rounds,
            permutation_rounds=permutation_rounds,
        )

    combined: dict[str, Any] = {}
    for name in FEATURE_NAMES:
        front_decision = areas["front"]["features"][name]["decision"]
        back_decision = areas["back"]["features"][name]["decision"]
        decisions = (front_decision, back_decision)
        if "KEEP_CANDIDATE" in decisions and "DEAD_PATH" not in decisions:
            overall = "KEEP_CANDIDATE"
        elif decisions == ("DEAD_PATH", "DEAD_PATH"):
            overall = "DEAD_PATH"
        else:
            overall = "NOT_VERIFIED"
        combined[name] = {
            "front": front_decision,
            "back": back_decision,
            "overall": overall,
        }

    return {
        "schema": "dlt-v2-feature-utility-shadow-v1",
        "created_at": utc_now(),
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "eval_points_requested": int(eval_points),
        "feature_names": list(FEATURE_NAMES),
        "forbidden_default_features": ["gap", "omission", "overdue"],
        "decision_vocabulary": list(ALLOWED_DECISIONS),
        "areas": areas,
        "combined": combined,
        "predictive_edge_claim": "NOT_VERIFIED",
        "production_rho": 0.0,
        "promotion_authorized": False,
    }
