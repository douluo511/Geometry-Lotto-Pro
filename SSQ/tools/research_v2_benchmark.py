from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from glp.constants import PROMOTION_POLICY
from glp.domain import Draw
from glp.evidence import bootstrap_ci, holm, permutation_p
from glp.research_v2 import (
    FEATURE_NAMES,
    exact_two_dan_random_baseline,
    feature_map,
    fit_ridge_multiscale,
    research_probabilities_from_feature_map,
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rank(probabilities: dict[int, float]) -> list[int]:
    return sorted(probabilities, key=lambda n: (-probabilities[n], n))


def load_draws(path: Path) -> tuple[list[Draw], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    draws = [Draw.from_dict(x) for x in payload["draws"]]
    canonical_hash = str(payload.get("canonical_hash") or "")
    if not draws:
        raise ValueError("official seed has no draws")
    for i in range(len(draws) - 1):
        if draws[i].draw_date >= draws[i + 1].draw_date:
            raise ValueError(
                f"non-monotonic chronology at {draws[i].issue}->{draws[i + 1].issue}"
            )
    return draws, canonical_hash


def exact_red_hit_null() -> dict[int, float]:
    total = math.comb(33, 6)
    return {
        k: math.comb(6, k) * math.comb(27, 6 - k) / total
        for k in range(7)
    }


def _record(
    front_rank: list[int],
    back_rank: list[int],
    target: Draw,
    dan_at_least_one_null: float,
) -> dict[str, Any]:
    actual_front = set(target.front)
    red_hits = len(set(front_rank[:6]) & actual_front)
    blue_hit = int(back_rank[0] in set(target.back))
    dan_hits = len(set(front_rank[:2]) & actual_front)
    dan_any = int(dan_hits >= 1)

    red_gain = red_hits - (36.0 / 33.0)
    blue_gain = blue_hit - (1.0 / 16.0)
    dan_gain = dan_any - dan_at_least_one_null
    combined_gain = 0.70 * ((red_hits / 6.0) - (6.0 / 33.0)) + 0.30 * blue_gain
    return {
        "issue": target.issue,
        "draw_date": target.draw_date,
        "red_hits": red_hits,
        "blue_hit": blue_hit,
        "dan_hits": dan_hits,
        "dan_at_least_one": dan_any,
        "red_gain": red_gain,
        "blue_gain": blue_gain,
        "dan_gain": dan_gain,
        "combined_gain": combined_gain,
    }


def _summary(records: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    metric_names = ("combined_gain", "dan_gain", "red_gain", "blue_gain")
    metrics: dict[str, Any] = {}
    pvalues: dict[str, float] = {}
    for idx, name in enumerate(metric_names):
        values = [float(r[name]) for r in records]
        boot = bootstrap_ci(values, rounds=rounds, seed=1729 + idx * 101)
        p = permutation_p(values, rounds=rounds, seed=2718 + idx * 101)
        metrics[name] = {
            "mean": _mean(values),
            "bootstrap": boot,
            "permutation_p": p,
            "n": len(values),
        }
        pvalues[name] = p
    return {"metrics": metrics, "holm": holm(pvalues)}


def _three_eras(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(records)
    cuts = (0, n // 3, (2 * n) // 3, n)
    eras = []
    for i in range(3):
        part = records[cuts[i]:cuts[i + 1]]
        eras.append({
            "era": i + 1,
            "n": len(part),
            "start_issue": part[0]["issue"] if part else None,
            "end_issue": part[-1]["issue"] if part else None,
            "combined_gain": _mean([float(x["combined_gain"]) for x in part]),
            "dan_gain": _mean([float(x["dan_gain"]) for x in part]),
            "red_gain": _mean([float(x["red_gain"]) for x in part]),
            "blue_gain": _mean([float(x["blue_gain"]) for x in part]),
        })
    return eras


def _null_worlds(n: int, observed_gain: float, worlds: int = 300) -> dict[str, Any]:
    rng = random.Random(0x53535132)
    world_means: list[float] = []
    false_promotions = 0
    n = max(240, n)
    for _ in range(worlds):
        vals: list[float] = []
        for _j in range(n):
            actual = set(rng.sample(range(1, 34), 6))
            pred = set(rng.sample(range(1, 34), 6))
            red_hits = len(actual & pred)
            blue_hit = 1 if rng.randrange(16) == 0 else 0
            vals.append(
                0.70 * ((red_hits / 6.0) - (6.0 / 33.0))
                + 0.30 * (blue_hit - (1.0 / 16.0))
            )
        m = _mean(vals)
        world_means.append(m)
        cut = len(vals) // 2
        okay = True
        for part in (vals[:cut], vals[cut:]):
            pm = _mean(part)
            if len(part) < 2:
                okay = False
                break
            sd = math.sqrt(sum((x - pm) ** 2 for x in part) / (len(part) - 1))
            lower = pm - 1.96 * sd / math.sqrt(len(part))
            if lower <= 0:
                okay = False
                break
        if okay:
            false_promotions += 1
    world_means.sort()
    return {
        "worlds": worlds,
        "false_promotions": false_promotions,
        "false_positive_rate": false_promotions / worlds,
        "observed_percentile": sum(x <= observed_gain for x in world_means) / worlds,
        "null_gain_p95": world_means[min(worlds - 1, int(0.95 * worlds))],
    }


def _distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    dan_null = exact_two_dan_random_baseline()
    red_null = exact_red_hit_null()
    n = len(records)
    dan_counts = Counter(int(r["dan_hits"]) for r in records)
    red_counts = Counter(int(r["red_hits"]) for r in records)
    blue_hits = sum(int(r["blue_hit"]) for r in records)
    return {
        "n": n,
        "two_dan": {
            "observed_counts": {str(k): dan_counts[k] for k in range(3)},
            "observed_rates": {str(k): dan_counts[k] / n for k in range(3)},
            "expected_rates": {
                "0": dan_null["zero_hits"],
                "1": dan_null["one_hit"],
                "2": dan_null["two_hits"],
            },
            "at_least_one_observed": (dan_counts[1] + dan_counts[2]) / n,
            "at_least_one_null": dan_null["at_least_one"],
        },
        "six_red": {
            "observed_counts": {str(k): red_counts[k] for k in range(7)},
            "observed_rates": {str(k): red_counts[k] / n for k in range(7)},
            "expected_rates": {str(k): red_null[k] for k in range(7)},
            "mean_hits_observed": _mean([float(r["red_hits"]) for r in records]),
            "mean_hits_null": 36.0 / 33.0,
        },
        "blue": {
            "hits": blue_hits,
            "observed_rate": blue_hits / n,
            "null_rate": 1.0 / 16.0,
        },
    }


def run_shadow_benchmark(
    draws: list[Draw],
    *,
    max_evals: int = 1440,
    confirmation_n: int = 240,
    refit_interval: int = 20,
    train_points: int = 240,
    rounds: int = 1999,
) -> dict[str, Any]:
    if refit_interval <= 0:
        raise ValueError("refit_interval must be positive")
    if confirmation_n <= 0:
        raise ValueError("confirmation_n must be positive")
    if max_evals <= confirmation_n:
        raise ValueError("max_evals must exceed confirmation_n")

    start = max(121, len(draws) - max_evals)
    dan_null = exact_two_dan_random_baseline()["at_least_one"]
    records: list[dict[str, Any]] = []
    ablation_values: dict[str, list[float]] = {name: [] for name in FEATURE_NAMES}
    base_holdout_values: list[float] = []

    front_coefficients: tuple[float, ...] | None = None
    back_coefficients: tuple[float, ...] | None = None
    refits = 0

    for offset, idx in enumerate(range(start, len(draws))):
        history = draws[:idx]
        target = draws[idx]
        if not history or history[-1].draw_date >= target.draw_date:
            raise RuntimeError(f"chronology leakage before target {target.issue}")

        if front_coefficients is None or offset % refit_interval == 0:
            front_fit = fit_ridge_multiscale(
                history, "front", rho=0.0, train_points=train_points
            )
            back_fit = fit_ridge_multiscale(
                history, "back", rho=0.0, train_points=train_points
            )
            front_coefficients = front_fit.coefficients
            back_coefficients = back_fit.coefficients
            refits += 1

        front_features = feature_map(history, "front")
        back_features = feature_map(history, "back")
        front_probs = research_probabilities_from_feature_map(
            front_features, "front", front_coefficients
        )
        back_probs = research_probabilities_from_feature_map(
            back_features, "back", back_coefficients
        )
        front_rank = _rank(front_probs)
        back_rank = _rank(back_probs)
        row = _record(front_rank, back_rank, target, dan_null)
        records.append(row)

        # Diagnostic only: coefficient-zero ablation on the final confirmation window.
        if idx >= len(draws) - confirmation_n:
            base_holdout_values.append(float(row["combined_gain"]))
            for feature in FEATURE_NAMES:
                alt_front = _rank(research_probabilities_from_feature_map(
                    front_features, "front", front_coefficients, zero_feature=feature
                ))
                alt_back = _rank(research_probabilities_from_feature_map(
                    back_features, "back", back_coefficients, zero_feature=feature
                ))
                alt = _record(alt_front, alt_back, target, dan_null)
                ablation_values[feature].append(
                    float(row["combined_gain"]) - float(alt["combined_gain"])
                )

    if len(records) <= confirmation_n:
        raise RuntimeError("insufficient OOS records for isolated confirmation window")
    dev = records[:-confirmation_n]
    holdout = records[-confirmation_n:]
    dev_summary = _summary(dev, rounds)
    holdout_summary = _summary(holdout, rounds)
    eras = _three_eras(dev)
    nulls = _null_worlds(
        len(dev),
        float(dev_summary["metrics"]["combined_gain"]["mean"]),
        worlds=int(PROMOTION_POLICY["null_worlds"]),
    )

    ablation: dict[str, Any] = {}
    for i, feature in enumerate(FEATURE_NAMES):
        vals = ablation_values[feature]
        ablation[feature] = {
            "kind": "coefficient_zero_diagnostic_not_refit",
            "mean_degradation": _mean(vals),
            "bootstrap": bootstrap_ci(vals, rounds=min(rounds, 999), seed=9000 + i),
            "permutation_p": permutation_p(vals, rounds=min(rounds, 1000), seed=10000 + i),
        }

    alpha = float(PROMOTION_POLICY["alpha"])
    combined_dev = dev_summary["metrics"]["combined_gain"]
    combined_hold = holdout_summary["metrics"]["combined_gain"]
    dan_dev = dev_summary["metrics"]["dan_gain"]
    dan_hold = holdout_summary["metrics"]["dan_gain"]

    edge_candidate_supported = bool(
        len(dev) >= int(PROMOTION_POLICY["min_walk_forward"])
        and combined_dev["bootstrap"]["lower95"] > 0
        and dev_summary["holm"]["combined_gain"]["reject_null"]
        and all(float(e["combined_gain"]) > 0 for e in eras)
        and combined_hold["bootstrap"]["lower95"] > 0
        and combined_hold["permutation_p"] <= alpha
        and nulls["false_positive_rate"] <= float(PROMOTION_POLICY["max_null_world_fpr"])
        and nulls["observed_percentile"] >= float(PROMOTION_POLICY["min_null_percentile"])
    )
    dan_candidate_supported = bool(
        dan_dev["bootstrap"]["lower95"] > 0
        and dev_summary["holm"]["dan_gain"]["reject_null"]
        and dan_hold["bootstrap"]["lower95"] > 0
        and dan_hold["permutation_p"] <= alpha
    )

    protocol_complete = bool(
        len(dev) >= int(PROMOTION_POLICY["min_walk_forward"])
        and len(holdout) == confirmation_n
        and len(eras) == 3
    )

    return {
        "schema": "ssq-v2-shadow-benchmark-v1",
        "software_status": "PASS" if protocol_complete else "FAIL",
        "research_decision": "CANDIDATE_SUPPORTED" if edge_candidate_supported else "NO_EDGE",
        "dan_research_decision": "DAN_CANDIDATE_SUPPORTED" if dan_candidate_supported else "NULL_DAN",
        "rho_recommendation": 0.0,
        "promotion_eligible": False,
        "promotion_blockers": [
            "refit-based feature ablation not yet executed",
            "excluded-heuristic challenger matrix not yet executed",
            "prospective immutable pre-draw replay n<120",
            "independent repository/release gates not satisfied",
        ],
        "walk_forward": {
            "total_oos_n": len(records),
            "development_oos_n": len(dev),
            "confirmation_oos_n": len(holdout),
            "refit_interval": refit_interval,
            "refit_count": refits,
            "train_points": train_points,
            "start_issue": records[0]["issue"],
            "end_issue": records[-1]["issue"],
        },
        "development": {
            "summary": dev_summary,
            "distribution": _distribution(dev),
            "eras": eras,
        },
        "confirmation": {
            "summary": holdout_summary,
            "distribution": _distribution(holdout),
        },
        "null_world": nulls,
        "coefficient_zero_ablation": ablation,
        "exact_nulls": {
            "two_dan": exact_two_dan_random_baseline(),
            "six_red": {str(k): v for k, v in exact_red_hit_null().items()},
            "blue_hit": 1.0 / 16.0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-evals", type=int, default=1440)
    parser.add_argument("--confirmation", type=int, default=240)
    parser.add_argument("--refit-interval", type=int, default=20)
    parser.add_argument("--train-points", type=int, default=240)
    parser.add_argument("--rounds", type=int, default=1999)
    args = parser.parse_args()

    draws, canonical_hash = load_draws(args.dataset)
    report = run_shadow_benchmark(
        draws,
        max_evals=args.max_evals,
        confirmation_n=args.confirmation,
        refit_interval=args.refit_interval,
        train_points=args.train_points,
        rounds=args.rounds,
    )
    report["canonical_hash"] = canonical_hash
    report["dataset_draws"] = len(draws)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps({
        "software_status": report["software_status"],
        "research_decision": report["research_decision"],
        "dan_research_decision": report["dan_research_decision"],
        "rho_recommendation": report["rho_recommendation"],
        "promotion_eligible": report["promotion_eligible"],
        "walk_forward": report["walk_forward"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["software_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
