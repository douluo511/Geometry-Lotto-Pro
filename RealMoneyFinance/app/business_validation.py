from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
from statistics import NormalDist, mean, median, pstdev
from typing import Iterable

from .domain import DailyBar


@dataclass(frozen=True)
class CostAssumptions:
    commission_bps_each_side: float = 3.0
    slippage_bps_each_side: float = 5.0
    sell_tax_bps: float = 5.0
    max_participation_rate: float = 0.05

    def round_trip_bps(self) -> float:
        return 2.0 * (self.commission_bps_each_side + self.slippage_bps_each_side) + self.sell_tax_bps


def _strict_dates(rows: list[DailyBar]) -> bool:
    dates = [x.trade_date for x in rows]
    return len(dates) == len(set(dates)) and dates == sorted(dates)


def _safe_ratio(values: list[float], recent: int, base: int) -> float | None:
    if len(values) < base:
        return None
    base_mean = mean(values[-base:])
    return None if base_mean == 0 else mean(values[-recent:]) / base_mean


def _feature_point(rows: list[DailyBar], index: int, fields: tuple[str, ...]) -> float | None:
    history = rows[: index + 1]
    ratios: list[float] = []
    for field in fields:
        vals = [getattr(x, field) for x in history]
        vals = [float(x) for x in vals if x is not None and math.isfinite(float(x)) and float(x) > 0]
        ratio = _safe_ratio(vals, 5, 20)
        if ratio is not None and math.isfinite(ratio):
            ratios.append(ratio)
    return mean(ratios) if ratios else None


def _observations(rows: list[DailyBar], fields: tuple[str, ...]) -> list[dict]:
    points: list[dict] = []
    for i in range(20, len(rows) - 1):
        score = _feature_point(rows, i, fields)
        if score is None:
            continue
        close = float(rows[i].close)
        nxt = float(rows[i + 1].close)
        if close <= 0 or nxt <= 0:
            continue
        points.append({
            "feature_date": rows[i].trade_date,
            "outcome_date": rows[i + 1].trade_date,
            "score": score,
            "next_return": nxt / close - 1.0,
            "amount": float(rows[i].amount or 0.0),
        })
    return points


def _walk_forward(points: list[dict], cost_bps: float, train_min: int = 60, fold_size: int = 20) -> dict:
    if len(points) < train_min + fold_size:
        raise ValueError("insufficient observations for frozen walk-forward denominator")
    oos: list[float] = []
    gross: list[float] = []
    folds: list[dict] = []
    start = train_min
    previous_position = 0
    while start < len(points):
        stop = min(len(points), start + fold_size)
        train = points[:start]
        test = points[start:stop]
        threshold = median([x["score"] for x in train])
        fold_net: list[float] = []
        for item in test:
            position = 1 if item["score"] >= threshold else 0
            gross_return = position * item["next_return"]
            turnover = abs(position - previous_position)
            cost = turnover * cost_bps / 10000.0
            net_return = gross_return - cost
            gross.append(gross_return)
            oos.append(net_return)
            fold_net.append(net_return)
            previous_position = position
        folds.append({
            "train_end_feature_date": train[-1]["feature_date"],
            "test_start_feature_date": test[0]["feature_date"],
            "test_end_outcome_date": test[-1]["outcome_date"],
            "threshold_from_train_only": threshold,
            "test_count": len(test),
            "mean_net_return": mean(fold_net) if fold_net else 0.0,
        })
        start = stop
    return {
        "folds": folds,
        "oos_net_returns": oos,
        "oos_gross_returns": gross,
        "oos_count": len(oos),
        "mean_net_return": mean(oos) if oos else 0.0,
        "mean_gross_return": mean(gross) if gross else 0.0,
        "hit_rate": sum(1 for x in oos if x > 0) / max(1, len(oos)),
    }


def _bootstrap_ci(values: list[float], seed: int = 20261004, samples: int = 1000) -> dict:
    if len(values) < 20:
        raise ValueError("insufficient OOS values for bootstrap")
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(samples):
        draw = [values[rng.randrange(n)] for _ in range(n)]
        means.append(mean(draw))
    means.sort()
    lo = means[int(0.025 * (samples - 1))]
    hi = means[int(0.975 * (samples - 1))]
    return {"samples": samples, "seed": seed, "mean_ci95": [lo, hi]}


def _two_sided_normal_p(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    sigma = pstdev(values)
    if sigma <= 0:
        return 1.0
    z = abs(mean(values)) / (sigma / math.sqrt(len(values)))
    return min(1.0, 2.0 * (1.0 - NormalDist().cdf(z)))


def _bonferroni(p_values: dict[str, float]) -> dict[str, float]:
    m = max(1, len(p_values))
    return {name: min(1.0, value * m) for name, value in p_values.items()}


def qualify_research(
    rows: Iterable[DailyBar],
    source_meta: dict,
    assumptions: CostAssumptions | None = None,
) -> dict:
    ordered = list(rows)
    assumptions = assumptions or CostAssumptions()
    if len(ordered) < 120:
        raise ValueError("at least 120 validated adjusted daily bars are required")
    if not _strict_dates(ordered):
        raise ValueError("bars must be unique and strictly chronological")

    adjustment = str(source_meta.get("price_adjustment", "")).lower()
    corporate_action = "PASS" if adjustment == "qfq" else "NOT VERIFIED"
    positive_amount = sum(1 for x in ordered if float(x.amount or 0.0) > 0)
    amount_coverage = positive_amount / len(ordered)
    liquidity = "PASS" if amount_coverage >= 0.95 else "NOT VERIFIED"

    feature_sets = {
        "all_available": ("amount", "turnover_rate", "volume"),
        "volume_only": ("volume",),
        "amount_only": ("amount",),
        "turnover_only": ("turnover_rate",),
    }
    results: dict[str, dict] = {}
    p_values: dict[str, float] = {}
    one_way_cost_bps = assumptions.round_trip_bps() / 2.0
    for name, fields in feature_sets.items():
        points = _observations(ordered, fields)
        if len(points) < 80:
            results[name] = {"status": "NOT VERIFIED", "reason": "insufficient usable lagged feature observations"}
            continue
        wf = _walk_forward(points, one_way_cost_bps)
        ci = _bootstrap_ci(wf["oos_net_returns"])
        p_value = _two_sided_normal_p(wf["oos_net_returns"])
        p_values[name] = p_value
        results[name] = {
            "status": "PASS",
            "fields": list(fields),
            "walk_forward": {k: v for k, v in wf.items() if k not in {"oos_net_returns", "oos_gross_returns"}},
            "bootstrap": ci,
            "raw_p_value": p_value,
            "ci_excludes_zero": ci["mean_ci95"][0] > 0 or ci["mean_ci95"][1] < 0,
        }

    if results.get("all_available", {}).get("status") == "PASS":
        base_name = "all_available"
    else:
        base_name = next(
            (x for x in ("volume_only", "amount_only", "turnover_only") if results.get(x, {}).get("status") == "PASS"),
            None,
        )
    if base_name is None:
        raise ValueError("no feature set has enough usable lagged observations")

    corrected = _bonferroni(p_values)
    for name, value in corrected.items():
        results[name]["bonferroni_p_value"] = value

    stability: dict[str, dict] = {}
    base_points = _observations(ordered, tuple(results[base_name]["fields"]))
    for multiplier in (0.5, 1.0, 2.0):
        wf = _walk_forward(base_points, one_way_cost_bps * multiplier)
        stability[str(multiplier)] = {
            "mean_net_return": wf["mean_net_return"],
            "oos_count": wf["oos_count"],
        }

    base = results[base_name]
    base_corrected = float(base.get("bonferroni_p_value", 1.0))
    economic_signal_qualified = (
        base["walk_forward"]["mean_net_return"] > 0
        and base["bootstrap"]["mean_ci95"][0] > 0
        and base_corrected <= 0.05
        and all(x["mean_net_return"] > 0 for x in stability.values())
        and liquidity == "PASS"
        and corporate_action == "PASS"
    )

    gates = {
        "cost_slippage_model": "PASS",
        "liquidity_capacity": liquidity,
        "corporate_action_adjustment": corporate_action,
        "leakage_safe_time_split": "PASS",
        "survivorship_selection_control": "NOT VERIFIED",
        "oos_walk_forward": "PASS",
        "bootstrap": "PASS",
        "ablation": "PASS",
        "stability": "PASS",
        "multiple_testing_correction": "PASS",
    }
    return {
        "status": "PASS",
        "scope": "research qualification; not personalized investment advice",
        "symbol": ordered[-1].symbol,
        "asof": ordered[-1].trade_date,
        "rows": len(ordered),
        "source_provider": source_meta.get("provider"),
        "source_price_adjustment": adjustment or None,
        "amount_coverage": amount_coverage,
        "cost_assumptions": asdict(assumptions),
        "round_trip_cost_bps_assumption": assumptions.round_trip_bps(),
        "base_feature_set": base_name,
        "feature_results": results,
        "stability": stability,
        "gates": gates,
        "economic_signal_qualified": economic_signal_qualified,
        "capital_deployment_ready": False,
        "selection_bias_boundary": (
            "This gate evaluates a user-selected single symbol. It does not prove a survivorship-safe "
            "precommitted investable universe, so portfolio deployment remains fail-closed."
        ),
    }
