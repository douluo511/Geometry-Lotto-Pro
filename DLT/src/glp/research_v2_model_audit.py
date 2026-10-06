from __future__ import annotations

import random
import statistics
from typing import Any

from .constants import PROMOTION_POLICY
from .domain import Draw
from .evidence import bootstrap_ci, permutation_p
from .research_v2 import fit_ridge_multiscale
from .util import sha256_json, utc_now


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    if area == "front":
        return draw.front
    if area == "back":
        return draw.back
    raise ValueError(f"unknown area: {area}")


def _meta(area: str) -> tuple[int, int]:
    return (35, 5) if area == "front" else (12, 2)


def _random_ranking(max_n: int, seed_material: Any) -> list[int]:
    seed = int(sha256_json(seed_material)[:16], 16)
    rng = random.Random(seed)
    values = list(range(1, max_n + 1))
    rng.shuffle(values)
    return values


def _recall(ranking: list[int], actual: tuple[int, ...], k: int) -> float:
    return len(set(ranking[:k]) & set(actual)) / float(k)


def _brier(probabilities: dict[int, float], actual: tuple[int, ...], max_n: int) -> float:
    actual_set = set(actual)
    return statistics.mean(
        (float(probabilities[n]) - (1.0 if n in actual_set else 0.0)) ** 2
        for n in range(1, max_n + 1)
    )


def walk_forward_joint_gains(
    draws: list[Draw],
    area: str,
    *,
    eval_points: int = 120,
    train_points: int = 120,
) -> dict[str, list[float]]:
    if len(draws) < 121:
        raise ValueError("joint audit requires at least 121 draws")
    max_n, pick = _meta(area)
    p0 = pick / max_n
    seeds = tuple(PROMOTION_POLICY["seeds"])
    start = max(121, len(draws) - eval_points)
    brier_gains: list[float] = []
    recall_gains: list[float] = []

    for target_index in range(start, len(draws)):
        history = draws[:target_index]
        result = fit_ridge_multiscale(
            history,
            area,
            rho=1.0,
            train_points=train_points,
        )
        actual = _area(draws[target_index], area)
        uniform = {n: p0 for n in range(1, max_n + 1)}
        baseline_brier = _brier(uniform, actual, max_n)
        model_brier = _brier(result.research_probabilities, actual, max_n)
        brier_gains.append(baseline_brier - model_brier)

        model_recall = _recall(result.research_ranking, actual, pick)
        random_recalls = [
            _recall(
                _random_ranking(
                    max_n,
                    ["dlt-v2-joint-shadow", area, seed, draws[target_index].issue],
                ),
                actual,
                pick,
            )
            for seed in seeds
        ]
        recall_gains.append(model_recall - statistics.mean(random_recalls))

    return {"brier_gain": brier_gains, "recall_gain": recall_gains}


def _metric_summary(values: list[float], *, seed: int) -> dict[str, Any]:
    lo, hi = bootstrap_ci(values, seed=seed)
    p = permutation_p(values, seed=seed + 1000)
    mean = statistics.mean(values) if values else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "bootstrap95": [lo, hi],
        "permutation_p": p,
        "pass": bool(values) and mean > 0.0 and lo > 0.0 and p < float(PROMOTION_POLICY["alpha"]),
    }


def _half_summary(values: list[float], *, seed: int) -> list[dict[str, Any]]:
    h = len(values) // 2
    chunks = [values[:h], values[h:]]
    return [
        {"half": i + 1, **_metric_summary(chunk, seed=seed + i * 100)}
        for i, chunk in enumerate(chunks)
    ]


def audit_joint_ridge(
    draws: list[Draw],
    *,
    eval_points: int = 120,
    train_points: int = 120,
) -> dict[str, Any]:
    if len(draws) < 121:
        raise ValueError("joint audit requires at least 121 draws")
    for draw in draws:
        draw.validate()
    if draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("draws must be chronological")
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("duplicate issue in joint audit")

    areas: dict[str, Any] = {}
    area_passes: list[bool] = []
    for offset, area in enumerate(("front", "back")):
        gains = walk_forward_joint_gains(
            draws,
            area,
            eval_points=eval_points,
            train_points=train_points,
        )
        brier = _metric_summary(gains["brier_gain"], seed=31000 + offset * 1000)
        recall = _metric_summary(gains["recall_gain"], seed=41000 + offset * 1000)
        brier_halves = _half_summary(gains["brier_gain"], seed=51000 + offset * 1000)
        recall_halves = _half_summary(gains["recall_gain"], seed=61000 + offset * 1000)
        area_pass = (
            brier["pass"]
            and recall["pass"]
            and all(x["pass"] for x in brier_halves)
            and all(x["pass"] for x in recall_halves)
        )
        area_passes.append(area_pass)
        areas[area] = {
            "brier_gain_vs_uniform": brier,
            "recall_gain_vs_random": recall,
            "brier_halves": brier_halves,
            "recall_halves": recall_halves,
            "decision": "SHADOW_EDGE_CANDIDATE" if area_pass else "NO_EDGE",
        }

    edge_candidate = all(area_passes)
    return {
        "schema": "dlt-v2-joint-ridge-shadow-v1",
        "created_at": utc_now(),
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "eval_points_requested": eval_points,
        "train_points": train_points,
        "areas": areas,
        "shadow_decision": "SHADOW_EDGE_CANDIDATE" if edge_candidate else "NO_EDGE",
        "predictive_edge_claim": "NOT_VERIFIED",
        "production_rho": 0.0,
        "promotion_authorized": False,
        "note": (
            "Even SHADOW_EDGE_CANDIDATE cannot promote production. "
            "Prospective immutable pre-draw evidence and the existing Evidence Court remain mandatory."
        ),
    }
