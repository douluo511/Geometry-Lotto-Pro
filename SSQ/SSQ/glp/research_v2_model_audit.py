from __future__ import annotations

import math
import statistics
from typing import Any

from .constants import PROMOTION_POLICY
from .domain import Draw
from .evidence import bootstrap_ci, permutation_p
from .research_v2 import exact_two_dan_random_baseline, fit_ridge_multiscale
from .util import utc_now


def _area(draw: Draw, area: str) -> tuple[int, ...]:
    if area == "front":
        return draw.front
    if area == "back":
        return draw.back
    raise ValueError(f"unknown area: {area}")


def _meta(area: str) -> tuple[int, int]:
    if area == "front":
        return 33, 6
    if area == "back":
        return 16, 1
    raise ValueError(f"unknown area: {area}")


def _brier(probabilities: dict[int, float], actual: tuple[int, ...], max_n: int) -> float:
    actual_set = set(actual)
    return statistics.mean(
        (float(probabilities[n]) - (1.0 if n in actual_set else 0.0)) ** 2
        for n in range(1, max_n + 1)
    )


def _red_ticket_null() -> dict[str, float]:
    total = math.comb(33, 6)
    return {
        str(k): (math.comb(6, k) * math.comb(27, 6 - k) / total)
        for k in range(7)
    }


def _metric_summary(values: list[float], *, seed: int) -> dict[str, Any]:
    ci = bootstrap_ci(values, seed=seed)
    p = permutation_p(values, seed=seed + 1000)
    mean = statistics.mean(values) if values else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "bootstrap95": [float(ci["lower95"]), float(ci["upper95"])],
        "permutation_p": float(p),
        "pass": bool(values)
        and mean > 0.0
        and float(ci["lower95"]) > 0.0
        and float(p) < float(PROMOTION_POLICY["alpha"]),
    }


def _half_summaries(values: list[float], *, seed: int) -> list[dict[str, Any]]:
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
        raise ValueError("SSQ joint audit requires at least 121 draws")
    for draw in draws:
        draw.validate()
    if draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("draws must be chronological")
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("duplicate issue in SSQ joint audit")

    start = max(121, len(draws) - int(eval_points))
    baseline_two_dan = exact_two_dan_random_baseline()
    red_ticket_null = _red_ticket_null()

    front_brier_gain: list[float] = []
    back_brier_gain: list[float] = []
    red_recall_gain: list[float] = []
    dan_at_least_one_gain: list[float] = []
    dan_two_hit_gain: list[float] = []
    blue_hit_gain: list[float] = []

    two_dan_counts = {str(k): 0 for k in range(3)}
    red_ticket_counts = {str(k): 0 for k in range(7)}
    blue_hit_count = 0

    for target_index in range(start, len(draws)):
        history = draws[:target_index]
        front = fit_ridge_multiscale(
            history, "front", rho=1.0, train_points=train_points
        )
        back = fit_ridge_multiscale(
            history, "back", rho=1.0, train_points=train_points
        )
        target = draws[target_index]

        front_uniform = {n: 6.0 / 33.0 for n in range(1, 34)}
        back_uniform = {n: 1.0 / 16.0 for n in range(1, 17)}
        front_brier_gain.append(
            _brier(front_uniform, target.front, 33)
            - _brier(front.research_probabilities, target.front, 33)
        )
        back_brier_gain.append(
            _brier(back_uniform, target.back, 16)
            - _brier(back.research_probabilities, target.back, 16)
        )

        front_top6 = front.research_ranking[:6]
        red_hits = len(set(front_top6) & set(target.front))
        red_ticket_counts[str(red_hits)] += 1
        red_recall_gain.append(red_hits / 6.0 - 6.0 / 33.0)

        dan_hits = len(set(front.research_ranking[:2]) & set(target.front))
        two_dan_counts[str(dan_hits)] += 1
        dan_at_least_one_gain.append(
            (1.0 if dan_hits >= 1 else 0.0) - float(baseline_two_dan["at_least_one"])
        )
        dan_two_hit_gain.append(
            (1.0 if dan_hits == 2 else 0.0) - float(baseline_two_dan["two_hits"])
        )

        blue_hit = 1.0 if back.research_ranking[0] in set(target.back) else 0.0
        blue_hit_count += int(blue_hit)
        blue_hit_gain.append(blue_hit - 1.0 / 16.0)

    metrics = {
        "front_brier_gain_vs_uniform": _metric_summary(front_brier_gain, seed=31001),
        "back_brier_gain_vs_uniform": _metric_summary(back_brier_gain, seed=32001),
        "red_recall_gain_vs_exact_random": _metric_summary(red_recall_gain, seed=33001),
        "two_dan_at_least_one_gain_vs_exact_null": _metric_summary(
            dan_at_least_one_gain, seed=34001
        ),
        "two_dan_two_hit_gain_vs_exact_null": _metric_summary(
            dan_two_hit_gain, seed=35001
        ),
        "blue_hit_gain_vs_exact_null": _metric_summary(blue_hit_gain, seed=36001),
    }

    primary_names = (
        "front_brier_gain_vs_uniform",
        "back_brier_gain_vs_uniform",
        "red_recall_gain_vs_exact_random",
        "two_dan_at_least_one_gain_vs_exact_null",
        "blue_hit_gain_vs_exact_null",
    )
    primary_series = {
        "front_brier_gain_vs_uniform": front_brier_gain,
        "back_brier_gain_vs_uniform": back_brier_gain,
        "red_recall_gain_vs_exact_random": red_recall_gain,
        "two_dan_at_least_one_gain_vs_exact_null": dan_at_least_one_gain,
        "blue_hit_gain_vs_exact_null": blue_hit_gain,
    }
    halves = {
        name: _half_summaries(values, seed=41000 + i * 1000)
        for i, (name, values) in enumerate(primary_series.items())
    }
    primary_pass = all(metrics[name]["pass"] for name in primary_names)
    half_pass = all(
        all(item["pass"] for item in halves[name])
        for name in primary_names
    )
    edge_candidate = bool(primary_pass and half_pass)

    n = max(1, len(front_brier_gain))
    return {
        "schema": "ssq-v2-joint-ridge-shadow-v1",
        "created_at": utc_now(),
        "draw_count": len(draws),
        "latest_issue": draws[-1].issue,
        "eval_points_requested": int(eval_points),
        "eval_points_observed": len(front_brier_gain),
        "train_points": int(train_points),
        "metrics": metrics,
        "half_stability": halves,
        "observed_distribution": {
            "two_dan_hits": {k: v / n for k, v in two_dan_counts.items()},
            "red_ticket_hits": {k: v / n for k, v in red_ticket_counts.items()},
            "blue_hit_rate": blue_hit_count / n,
        },
        "exact_null": {
            "two_dan_hits": {
                "0": float(baseline_two_dan["zero_hits"]),
                "1": float(baseline_two_dan["one_hit"]),
                "2": float(baseline_two_dan["two_hits"]),
                "at_least_one": float(baseline_two_dan["at_least_one"]),
            },
            "red_ticket_hits": red_ticket_null,
            "blue_hit_rate": 1.0 / 16.0,
        },
        "shadow_decision": "SHADOW_EDGE_CANDIDATE" if edge_candidate else "NO_EDGE",
        "predictive_edge_claim": "NOT_VERIFIED",
        "production_rho": 0.0,
        "promotion_authorized": False,
        "stopping_rule": (
            "NO_EDGE stops model promotion. SHADOW_EDGE_CANDIDATE still requires "
            "the frozen era/holdout/null-world/ablation/prospective protocol."
        ),
    }
