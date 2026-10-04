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


# Frozen before qualification. Every declared candidate stays in the multiple-
# testing denominator even if a provider lacks one of its fields.
FROZEN_SEARCH_FAMILY = {
    "all_available": ("amount", "turnover_rate", "volume"),
    "volume_only": ("volume",),
    "amount_only": ("amount",),
    "turnover_only": ("turnover_rate",),
}
FROZEN_METHOD_THRESHOLDS = {
    "min_oos_observations": 120,
    "min_walk_forward_folds": 6,
    "moving_block_length": 5,
    "bootstrap_samples": 1000,
    "regime_windows": 3,
    "min_regime_observations": 30,
}


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
    # A finalized close/volume feature is unavailable at that same close. Execute
    # at the following open and hold to the next open, preserving A-share T+1.
    for i in range(20, len(rows) - 2):
        score = _feature_point(rows, i, fields)
        if score is None:
            continue
        entry = float(rows[i + 1].open)
        exit_price = float(rows[i + 2].open)
        if not math.isfinite(entry) or not math.isfinite(exit_price) or entry <= 0 or exit_price <= 0:
            continue
        points.append({
            "feature_date": rows[i].trade_date,
            "entry_date": rows[i + 1].trade_date,
            "outcome_date": rows[i + 2].trade_date,
            "score": score,
            "next_return": exit_price / entry - 1.0,
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
    costs: list[float] = []
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
            costs.append(cost)
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
    # A remaining long must sell at the last outcome open. Without this charge,
    # an all-long path pays only its purchase cost and understates round trips.
    if previous_position:
        closing_cost = cost_bps / 10000.0
        oos[-1] -= closing_cost
        costs[-1] += closing_cost
        last_fold = folds[-1]
        last_fold["mean_net_return"] -= closing_cost / last_fold["test_count"]
    baseline = [x["next_return"] for x in points[train_min:]]
    baseline[0] -= cost_bps / 10000.0
    baseline[-1] -= cost_bps / 10000.0
    return {
        "folds": folds,
        "oos_net_returns": oos,
        "oos_gross_returns": gross,
        "oos_count": len(oos),
        "mean_net_return": mean(oos) if oos else 0.0,
        "mean_gross_return": mean(gross) if gross else 0.0,
        "hit_rate": sum(1 for x in oos if x > 0) / max(1, len(oos)),
        "total_cost_return": sum(costs),
        "buy_and_hold_baseline_mean_net_return": mean(baseline),
        "cash_baseline_mean_return": 0.0,
        "execution_timing": "feature close t; rebalance open t+1; return open t+1 to t+2; final liquidation charged",
    }


def _moving_block_bootstrap_ci(
    values: list[float],
    seed: int = 20261004,
    samples: int = 1000,
    block_length: int = 5,
) -> dict:
    if len(values) < max(20, block_length * 4):
        raise ValueError("insufficient OOS values for dependence-aware bootstrap")
    if block_length < 2 or block_length > len(values):
        raise ValueError("invalid moving bootstrap block length")
    rng = random.Random(seed)
    n = len(values)
    starts = list(range(0, n - block_length + 1))
    means = []
    for _ in range(samples):
        draw: list[float] = []
        while len(draw) < n:
            start = starts[rng.randrange(len(starts))]
            draw.extend(values[start:start + block_length])
        means.append(mean(draw[:n]))
    means.sort()
    lo = means[int(0.025 * (samples - 1))]
    hi = means[int(0.975 * (samples - 1))]
    return {
        "method": "moving_block_bootstrap",
        "samples": samples,
        "seed": seed,
        "block_length": block_length,
        "mean_ci95": [lo, hi],
    }


def _two_sided_normal_p(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    sigma = pstdev(values)
    if sigma <= 0:
        return 1.0
    z = abs(mean(values)) / (sigma / math.sqrt(len(values)))
    return min(1.0, 2.0 * (1.0 - NormalDist().cdf(z)))


def _bonferroni(p_values: dict[str, float], family_size: int) -> dict[str, float]:
    if family_size < len(p_values) or family_size <= 0:
        raise ValueError("multiple-testing family size cannot be smaller than executed tests")
    return {name: min(1.0, value * family_size) for name, value in p_values.items()}


def qualify_research(
    rows: Iterable[DailyBar],
    source_meta: dict,
    assumptions: CostAssumptions | None = None,
) -> dict:
    ordered = list(rows)
    assumptions = assumptions or CostAssumptions()
    if any(not math.isfinite(v) or v < 0 for v in (
        assumptions.commission_bps_each_side, assumptions.slippage_bps_each_side, assumptions.sell_tax_bps
    )) or not 0 < assumptions.max_participation_rate <= 1:
        raise ValueError("cost assumptions must be finite, nonnegative; participation must be in (0, 1]")
    if len(ordered) < 120:
        raise ValueError("at least 120 validated adjusted daily bars are required")
    if not _strict_dates(ordered):
        raise ValueError("bars must be unique and strictly chronological")

    adjustment = str(source_meta.get("price_adjustment", "")).lower()
    # A provider's adjustment label is lineage, not independently verified
    # corporate-action factors, dates or point-in-time availability.
    corporate_action = "NOT VERIFIED"
    positive_amount = sum(1 for x in ordered if float(x.amount or 0.0) > 0)
    amount_coverage = positive_amount / len(ordered)
    # Positive daily amount neither states an order size nor proves executable
    # participation/impact. No capacity PASS can be inferred from coverage.
    liquidity = "NOT VERIFIED"

    feature_sets = dict(FROZEN_SEARCH_FAMILY)
    results: dict[str, dict] = {}
    p_values: dict[str, float] = {}
    one_way_cost_bps = assumptions.round_trip_bps() / 2.0
    for name, fields in feature_sets.items():
        points = _observations(ordered, fields)
        if len(points) < 80:
            results[name] = {"status": "NOT VERIFIED", "reason": "insufficient usable lagged feature observations"}
            continue
        wf = _walk_forward(points, one_way_cost_bps)
        ci = _moving_block_bootstrap_ci(
            wf["oos_net_returns"],
            samples=FROZEN_METHOD_THRESHOLDS["bootstrap_samples"],
            block_length=FROZEN_METHOD_THRESHOLDS["moving_block_length"],
        )
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

    corrected = _bonferroni(p_values, len(feature_sets))
    for name, value in corrected.items():
        results[name]["bonferroni_p_value"] = value

    stability: dict[str, dict] = {}
    base_points = _observations(ordered, tuple(results[base_name]["fields"]))
    base_wf = _walk_forward(base_points, one_way_cost_bps)
    for multiplier in (0.5, 1.0, 2.0):
        wf = _walk_forward(base_points, one_way_cost_bps * multiplier)
        stability[str(multiplier)] = {
            "mean_net_return": wf["mean_net_return"],
            "oos_count": wf["oos_count"],
        }

    oos_values = list(base_wf["oos_net_returns"])
    window_count = FROZEN_METHOD_THRESHOLDS["regime_windows"]
    regime_windows: list[dict] = []
    for index in range(window_count):
        start = index * len(oos_values) // window_count
        stop = (index + 1) * len(oos_values) // window_count
        chunk = oos_values[start:stop]
        regime_windows.append({
            "window": index + 1,
            "start_oos_index": start,
            "stop_oos_index_exclusive": stop,
            "count": len(chunk),
            "mean_net_return": mean(chunk) if chunk else None,
        })

    base = results[base_name]
    base_corrected = float(base.get("bonferroni_p_value", 1.0))
    diagnostic_thresholds_met = (
        base["walk_forward"]["mean_net_return"] > 0
        and base["bootstrap"]["mean_ci95"][0] > 0
        and base_corrected <= 0.05
        and all(x["mean_net_return"] > 0 for x in stability.values())
    )

    walk_forward_coverage = (
        base_wf["oos_count"] >= FROZEN_METHOD_THRESHOLDS["min_oos_observations"]
        and len(base_wf["folds"]) >= FROZEN_METHOD_THRESHOLDS["min_walk_forward_folds"]
    )
    bootstrap_coverage = (
        base["bootstrap"].get("method") == "moving_block_bootstrap"
        and base["bootstrap"].get("samples") == FROZEN_METHOD_THRESHOLDS["bootstrap_samples"]
        and base["bootstrap"].get("block_length") == FROZEN_METHOD_THRESHOLDS["moving_block_length"]
    )
    regime_coverage = (
        len(regime_windows) == FROZEN_METHOD_THRESHOLDS["regime_windows"]
        and all(
            item["count"] >= FROZEN_METHOD_THRESHOLDS["min_regime_observations"]
            and isinstance(item["mean_net_return"], (int, float))
            and math.isfinite(item["mean_net_return"])
            for item in regime_windows
        )
    )
    search_family_coverage = (
        set(results) == set(FROZEN_SEARCH_FAMILY)
        and len(feature_sets) == len(FROZEN_SEARCH_FAMILY)
        and all(name in results for name in FROZEN_SEARCH_FAMILY)
    )

    method_gates = {
        "cost_slippage_model": "PASS",
        "leakage_safe_time_split": "PASS",
        "oos_walk_forward": "PASS" if walk_forward_coverage else "NOT VERIFIED",
        "bootstrap": "PASS" if bootstrap_coverage else "NOT VERIFIED",
        "ablation": "PASS" if all(x.get("status") == "PASS" for x in results.values()) else "NOT VERIFIED",
        "stability": "PASS" if regime_coverage else "NOT VERIFIED",
        "multiple_testing_correction": "PASS" if search_family_coverage else "NOT VERIFIED",
    }
    gates = {
        "cost_slippage_model": "NOT VERIFIED",
        "liquidity_capacity": "NOT VERIFIED",
        "corporate_action_adjustment": "NOT VERIFIED",
        "leakage_safe_time_split": "NOT VERIFIED",
        "survivorship_selection_control": "NOT VERIFIED",
        # Execution coverage alone is not a formal holdout-power analysis.
        "oos_walk_forward": "NOT VERIFIED",
        "bootstrap": method_gates["bootstrap"],
        "ablation": "NOT VERIFIED",
        # Chronological windows are useful diagnostics but are not independently
        # defined market regimes, so the business regime-stability gate stays closed.
        "stability": "NOT VERIFIED",
        "multiple_testing_correction": method_gates["multiple_testing_correction"],
    }
    gaps = {
        "cost_slippage_model": "Illustrative basis-point assumptions lack current exchange/broker calibration and observed execution slippage.",
        "liquidity_capacity": "No order notional, executable participation, spread/impact or limit/suspension fill evidence.",
        "corporate_action_adjustment": "Provider qfq label lacks verified action factors/dates and point-in-time lineage.",
        "leakage_safe_time_split": "Lagged execution is implemented, but historical point-in-time source availability is unverified.",
        "survivorship_selection_control": "User-selected single symbol lacks a precommitted survivorship-safe investable universe.",
        "oos_walk_forward": "Walk-forward execution is covered, but no frozen minimum detectable effect/power target was precommitted.",
        "ablation": "Provider field coverage is insufficient to execute every frozen feature ablation on the same real dataset.",
        "stability": "Chronological windows are diagnostics only; independently defined market-regime labels and coverage are not verified.",
    }
    return {
        "status": "PASS",
        "scope": "method execution diagnostics; full business qualification is NOT VERIFIED",
        "method_execution_status": "PASS",
        "business_qualification_status": "NOT VERIFIED",
        "symbol": ordered[-1].symbol,
        "asof": ordered[-1].trade_date,
        "rows": len(ordered),
        "source_provider": source_meta.get("provider"),
        "source_price_adjustment": adjustment or None,
        "amount_coverage": amount_coverage,
        "liquidity_capacity_status": liquidity,
        "corporate_action_status": corporate_action,
        "cost_assumptions": asdict(assumptions),
        "round_trip_cost_bps_assumption": assumptions.round_trip_bps(),
        "base_feature_set": base_name,
        "feature_results": results,
        "stability": stability,
        "regime_windows": regime_windows,
        "frozen_search_family": {name: list(fields) for name, fields in FROZEN_SEARCH_FAMILY.items()},
        "frozen_method_thresholds": dict(FROZEN_METHOD_THRESHOLDS),
        "multiple_testing_family_size": len(FROZEN_SEARCH_FAMILY),
        "gates": gates,
        "method_gates": method_gates,
        "qualification_gaps": gaps,
        "diagnostic_thresholds_met": diagnostic_thresholds_met,
        "economic_signal_qualified": False,
        "capital_deployment_ready": False,
        "selection_bias_boundary": (
            "This gate evaluates a user-selected single symbol. It does not prove a survivorship-safe "
            "precommitted investable universe, so portfolio deployment remains fail-closed."
        ),
    }

