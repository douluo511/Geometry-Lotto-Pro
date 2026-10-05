from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date
import math
import random
import re
from statistics import NormalDist, mean, median, pstdev
from typing import Iterable

from .domain import DailyBar, validate_market_rows


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
# Frozen leave-one-feature-out replication family. These exclusions are structural,
# not selected from observed performance, so current real-network evidence can
# execute the ablation gate without post-hoc model shopping.
FROZEN_ABLATION_FAMILY = {
    "without_amount": ("turnover_rate", "volume"),
    "without_turnover_rate": ("amount", "volume"),
    "without_volume": ("amount", "turnover_rate"),
}
FROZEN_METHOD_THRESHOLDS = {
    "min_oos_observations": 120,
    "min_walk_forward_folds": 6,
    "moving_block_length": 5,
    "bootstrap_samples": 1000,
    "regime_windows": 3,
    "min_regime_observations": 30,
    "regime_benchmark_lookback": 20,
    # Frozen before the next exact-head real-network qualification. This is a
    # decision target, not a claim that the observed signal has enough power.
    "holdout_alpha": 0.05,
    "holdout_target_power": 0.80,
    "holdout_min_detectable_mean_return": 0.0010,
}


def _strict_dates(rows: list[DailyBar]) -> bool:
    dates = [x.trade_date for x in rows]
    return len(dates) == len(set(dates)) and dates == sorted(dates)


def _corporate_action_evidence_qualified(source_meta: dict, evidence: dict) -> bool:
    if source_meta.get("qualification_scope") != "production_real_network":
        return False
    if str(source_meta.get("price_adjustment", "")).lower() != "qfq":
        return False
    if evidence.get("status") != "PASS" or evidence.get("point_in_time_lineage") != "PASS":
        return False

    providers = evidence.get("source_providers")
    if providers != {
        "qfq": "tencent_public_full_kline",
        "raw": "tencent_public_full_kline",
        "events": "eastmoney_share_bonus_datacenter",
    }:
        return False

    hashes = [
        evidence.get("qfq_payload_sha256"),
        evidence.get("raw_payload_sha256"),
        evidence.get("event_payload_sha256"),
    ]
    if any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}", x) for x in hashes):
        return False
    if hashes[0] == hashes[1]:
        return False

    try:
        verified = int(evidence.get("verified_event_count"))
        unexplained_count = int(evidence.get("unexplained_factor_changes"))
        significant = int(evidence.get("significant_factor_changes"))
        overlap_rows = int(evidence.get("overlap_rows"))
    except Exception:
        return False
    source_symbol = str(source_meta.get("symbol") or "")
    evidence_symbol = str(evidence.get("symbol") or "")
    if overlap_rows < 60:
        return False
    if source_symbol and evidence_symbol != source_symbol:
        return False
    matched = evidence.get("matched_events")
    unexplained = evidence.get("unexplained_changes")
    if (
        verified < 1
        or unexplained_count != 0
        or not isinstance(matched, list)
        or len(matched) != verified
        or not isinstance(unexplained, list)
        or len(unexplained) != 0
        or significant != verified + unexplained_count
    ):
        return False

    if evidence.get("factor_detection_method") != "persistent_median_regime_shift_v1":
        return False
    if evidence.get("factor_estimator") != "quantized_ohlc_interval_v2":
        return False
    try:
        factor_window_sessions = int(evidence.get("factor_window_sessions"))
    except Exception:
        return False
    if factor_window_sessions < 3:
        return False
    price_tick = evidence.get("price_tick")
    if not isinstance(price_tick, (int, float)) or not math.isfinite(float(price_tick)) or abs(float(price_tick) - 0.01) > 1e-12:
        return False
    tolerance = evidence.get("factor_change_tolerance")
    if not isinstance(tolerance, (int, float)) or not math.isfinite(float(tolerance)) or float(tolerance) <= 0:
        return False
    seen_events = set()
    for item in matched:
        if not isinstance(item, dict):
            return False
        event = item.get("event")
        change = item.get("factor_change")
        if not isinstance(event, dict) or not isinstance(change, dict):
            return False
        notice = str(event.get("plan_notice_date") or "")
        ex_date = str(event.get("ex_dividend_date") or "")
        trade_date = str(change.get("trade_date") or "")
        previous_trade_date = str(change.get("previous_trade_date") or "")
        if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x) for x in (notice, ex_date, previous_trade_date, trade_date)):
            return False
        try:
            notice_day = date.fromisoformat(notice)
            ex_day = date.fromisoformat(ex_date)
            previous_day = date.fromisoformat(previous_trade_date)
            trade_day = date.fromisoformat(trade_date)
        except Exception:
            return False
        if notice_day > ex_day or previous_day >= trade_day or trade_day < ex_day:
            return False
        days_after = item.get("calendar_days_after_ex_date")
        actual_days_after = (trade_day - ex_day).days
        if not isinstance(days_after, int) or days_after != actual_days_after or not 0 <= days_after <= 7:
            return False

        event_symbol = str(event.get("symbol") or "")
        if event_symbol != evidence_symbol:
            return False
        try:
            payout_positive = any(float(event.get(k) or 0) > 0 for k in ("pretax_bonus_rmb", "bonus_ratio", "transfer_ratio"))
        except Exception:
            return False
        if not payout_positive:
            return False
        event_key = (event_symbol, notice, ex_date)
        if event_key in seen_events:
            return False
        seen_events.add(event_key)

        relative = change.get("relative_change")
        effective_threshold = change.get("effective_threshold")
        rounding_bound = change.get("rounding_error_bound")
        local_noise = change.get("local_mad_ratio")
        interval_gap = change.get("quantization_interval_gap")
        before_interval = change.get("before_factor_interval")
        after_interval = change.get("after_factor_interval")
        if (
            not isinstance(interval_gap, (int, float))
            or not math.isfinite(float(interval_gap))
            or float(interval_gap) <= float(tolerance)
            or not isinstance(before_interval, list) or len(before_interval) != 2
            or not isinstance(after_interval, list) or len(after_interval) != 2
            or not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in before_interval + after_interval)
            or float(before_interval[0]) > float(before_interval[1])
            or float(after_interval[0]) > float(after_interval[1])
            or not (float(before_interval[1]) < float(after_interval[0])
                    or float(after_interval[1]) < float(before_interval[0]))
        ):
            return False
        values = (relative, effective_threshold, rounding_bound, local_noise)
        if any(not isinstance(x, (int, float)) or not math.isfinite(float(x)) for x in values):
            return False
        if float(effective_threshold) < float(tolerance):
            return False
        if float(rounding_bound) < 0 or float(local_noise) < 0:
            return False
        if float(relative) <= float(effective_threshold):
            return False
    return True


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


def _independent_benchmark_regimes(
    base_points: list[dict],
    oos_values: list[float],
    benchmark_rows: Iterable[DailyBar] | None,
    benchmark_meta: dict | None,
) -> dict:
    """Evaluate OOS outcomes in ex-ante SSE benchmark trend regimes."""
    rows = list(benchmark_rows or [])
    meta = dict(benchmark_meta or {})
    lookback = int(FROZEN_METHOD_THRESHOLDS["regime_benchmark_lookback"])
    minimum = int(FROZEN_METHOD_THRESHOLDS["min_regime_observations"])
    if (
        meta.get("qualification_scope") != "production_real_network_benchmark"
        or meta.get("instrument_role") != "benchmark_sse_composite"
    ):
        return {"status": "NOT VERIFIED", "reason": "independent live benchmark evidence unavailable"}
    if len(rows) < lookback + 2 or not _strict_dates(rows):
        return {"status": "NOT VERIFIED", "reason": "benchmark history is insufficient or not chronological"}
    if len(oos_values) == 0 or len(oos_values) > len(base_points):
        return {"status": "NOT VERIFIED", "reason": "OOS alignment is unavailable"}

    dates = [row.trade_date for row in rows]
    closes = [float(row.close) for row in rows]
    if any(not math.isfinite(x) or x <= 0 for x in closes):
        return {"status": "NOT VERIFIED", "reason": "benchmark contains invalid closes"}

    oos_points = base_points[-len(oos_values):]
    buckets: dict[str, list[float]] = {"BULL": [], "BEAR": []}
    missing = 0
    for point, value in zip(oos_points, oos_values):
        idx = bisect_right(dates, point["feature_date"]) - 1
        if idx < lookback:
            missing += 1
            continue
        trailing = closes[idx] / closes[idx - lookback] - 1.0
        label = "BULL" if trailing >= 0 else "BEAR"
        buckets[label].append(float(value))

    regimes = {
        name: {
            "count": len(values),
            "mean_net_return": mean(values) if values else None,
        }
        for name, values in buckets.items()
    }
    coverage = missing == 0 and all(
        item["count"] >= minimum
        and isinstance(item["mean_net_return"], (int, float))
        and math.isfinite(item["mean_net_return"])
        for item in regimes.values()
    )
    return {
        "status": "PASS" if coverage else "NOT VERIFIED",
        "definition": "SSE Composite trailing-20-session return >= 0 => BULL; otherwise BEAR",
        "lookback_sessions": lookback,
        "minimum_observations_per_regime": minimum,
        "missing_oos_labels": missing,
        "regimes": regimes,
        "benchmark_provider": meta.get("provider"),
        "benchmark_payload_sha256": meta.get("payload_sha256"),
        "benchmark_asof": rows[-1].trade_date if rows else None,
        "reason": None if coverage else "independent benchmark regime coverage is insufficient",
    }


def _holdout_power_analysis(values: list[float]) -> dict:
    """Evaluate the frozen holdout-power target without promoting signal success."""
    if len(values) < 20 or any(not math.isfinite(float(x)) for x in values):
        return {"status": "NOT VERIFIED", "reason": "insufficient finite holdout returns"}
    alpha = float(FROZEN_METHOD_THRESHOLDS["holdout_alpha"])
    target_power = float(FROZEN_METHOD_THRESHOLDS["holdout_target_power"])
    mde = float(FROZEN_METHOD_THRESHOLDS["holdout_min_detectable_mean_return"])
    if not (0 < alpha < 1 and 0.5 < target_power < 1 and mde > 0):
        raise ValueError("invalid frozen holdout power target")
    sigma = pstdev(values)
    if not math.isfinite(sigma) or sigma <= 0:
        return {"status": "NOT VERIFIED", "reason": "non-positive holdout volatility"}
    z_alpha = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    z_power = NormalDist().inv_cdf(target_power)
    required_n = math.ceil(((z_alpha + z_power) * sigma / mde) ** 2)
    observed_n = len(values)

    return {
        "status": "PASS",
        "method": "normal_approximation_two_sided_mean_test",
        "alpha": alpha,
        "target_power": target_power,
        "minimum_detectable_mean_return": mde,
        "observed_sigma": sigma,
        "observed_n": observed_n,
        "required_n": required_n,
        "power_sufficient": observed_n >= required_n,
        "decision": "SUFFICIENT" if observed_n >= required_n else "INSUFFICIENT",
    }


def qualify_research(
    rows: Iterable[DailyBar],
    source_meta: dict,
    assumptions: CostAssumptions | None = None,
    *,
    benchmark_rows: Iterable[DailyBar] | None = None,
    benchmark_meta: dict | None = None,
    corporate_action_evidence: dict | None = None,
) -> dict:
    ordered = list(rows)
    validate_market_rows(ordered)
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
    # A provider qfq label alone is never enough. Corporate-action PASS requires
    # independent event dates plus observed qfq/raw factor changes and source hashes.
    research_symbol = str(ordered[0].symbol)
    if any(str(row.symbol) != research_symbol for row in ordered):
        raise ValueError("qualification rows must belong to one research symbol")
    corporate_evidence = dict(corporate_action_evidence or {})
    # Preserve an explicit source symbol if the adapter supplied one. Overwriting
    # it with the row symbol would erase cross-symbol provenance mismatches and
    # allow forged evidence to qualify. Only backfill the symbol when source
    # metadata is genuinely silent.
    corporate_source_meta = dict(source_meta)
    if not str(corporate_source_meta.get("symbol") or "").strip():
        corporate_source_meta["symbol"] = research_symbol
    corporate_action = (
        "PASS"
        if _corporate_action_evidence_qualified(corporate_source_meta, corporate_evidence)
        else "NOT VERIFIED"
    )
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
    holdout_power = _holdout_power_analysis(oos_values)

    ablation_results: dict[str, dict] = {}
    for name, fields in FROZEN_ABLATION_FAMILY.items():
        points = _observations(ordered, fields)
        if len(points) < 80:
            ablation_results[name] = {
                "status": "NOT VERIFIED",
                "fields": list(fields),
                "reason": "insufficient usable lagged feature observations",
            }
            continue
        wf = _walk_forward(points, one_way_cost_bps)
        ci = _moving_block_bootstrap_ci(
            wf["oos_net_returns"],
            samples=FROZEN_METHOD_THRESHOLDS["bootstrap_samples"],
            block_length=FROZEN_METHOD_THRESHOLDS["moving_block_length"],
        )
        ablation_results[name] = {
            "status": "PASS",
            "fields": list(fields),
            "walk_forward": {k: v for k, v in wf.items() if k not in {"oos_net_returns", "oos_gross_returns"}},
            "bootstrap": ci,
            "mean_net_return": wf["mean_net_return"],
        }

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

    independent_regime_analysis = _independent_benchmark_regimes(
        base_points, oos_values, benchmark_rows, benchmark_meta
    )

    base = results[base_name]
    base_corrected = float(base.get("bonferroni_p_value", 1.0))
    diagnostic_thresholds_met = (
        base["walk_forward"]["mean_net_return"] > 0
        and base["bootstrap"]["mean_ci95"][0] > 0
        and base_corrected <= 0.05
        and all(x["mean_net_return"] > 0 for x in stability.values())
        and holdout_power.get("power_sufficient") is True
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
    ablation_coverage = (
        all(results.get(name, {}).get("status") == "PASS" for name in FROZEN_SEARCH_FAMILY)
        and set(ablation_results) == set(FROZEN_ABLATION_FAMILY)
        and all(
            item.get("status") == "PASS"
            and item.get("walk_forward", {}).get("oos_count", 0) >= FROZEN_METHOD_THRESHOLDS["min_oos_observations"]
            and len(item.get("walk_forward", {}).get("folds", [])) >= FROZEN_METHOD_THRESHOLDS["min_walk_forward_folds"]
            for item in ablation_results.values()
        )
    )

    method_gates = {
        "cost_slippage_model": "PASS",
        "leakage_safe_time_split": "PASS",
        "oos_walk_forward": "PASS" if walk_forward_coverage else "NOT VERIFIED",
        "bootstrap": "PASS" if bootstrap_coverage else "NOT VERIFIED",
        "ablation": "PASS" if ablation_coverage else "NOT VERIFIED",
        "stability": "PASS" if regime_coverage else "NOT VERIFIED",
        "multiple_testing_correction": "PASS" if search_family_coverage else "NOT VERIFIED",
    }
    gates = {
        "cost_slippage_model": "NOT VERIFIED",
        "liquidity_capacity": "NOT VERIFIED",
        "corporate_action_adjustment": corporate_action,
        "leakage_safe_time_split": "NOT VERIFIED",
        "survivorship_selection_control": "NOT VERIFIED",
        # Computing an INSUFFICIENT decision completes a method diagnostic but
        # cannot satisfy the frozen business gate named holdout power.
        "oos_walk_forward": "PASS" if (
            source_meta.get("qualification_scope") == "production_real_network"
            and walk_forward_coverage
            and holdout_power.get("status") == "PASS"
            and holdout_power.get("power_sufficient") is True
        ) else "NOT VERIFIED",
        "bootstrap": method_gates["bootstrap"],
        "ablation": "PASS" if (
            source_meta.get("qualification_scope") == "production_real_network"
            and ablation_coverage
        ) else "NOT VERIFIED",
        "stability": "PASS" if (
            source_meta.get("qualification_scope") == "production_real_network"
            and independent_regime_analysis.get("status") == "PASS"
        ) else "NOT VERIFIED",
        "multiple_testing_correction": method_gates["multiple_testing_correction"],
    }
    gaps = {
        "cost_slippage_model": "Illustrative basis-point assumptions lack current exchange/broker calibration and observed execution slippage.",
        "liquidity_capacity": "No order notional, executable participation, spread/impact or limit/suspension fill evidence.",
        "corporate_action_adjustment": "Provider qfq label alone is insufficient; PASS requires independently hashed action dates plus matched qfq/raw factor changes with no unexplained changes.",
        "leakage_safe_time_split": "Lagged execution is implemented, but historical point-in-time source availability is unverified.",
        "survivorship_selection_control": "User-selected single symbol lacks a precommitted survivorship-safe investable universe.",
        "oos_walk_forward": "Frozen holdout-power target lacks sufficient current real-network OOS evidence; computing an INSUFFICIENT decision is not a power PASS.",
        "ablation": "Frozen leave-one-feature-out replication was not executed with complete field coverage on current production real-network evidence.",
        "stability": "Independent SSE Composite BULL/BEAR regime labels lack complete current real-network OOS coverage.",
    }
    gaps = {name: reason for name, reason in gaps.items() if gates.get(name) != "PASS"}
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
        "corporate_action_evidence": corporate_evidence,
        "cost_assumptions": asdict(assumptions),
        "round_trip_cost_bps_assumption": assumptions.round_trip_bps(),
        "base_feature_set": base_name,
        "feature_results": results,
        "stability": stability,
        "regime_windows": regime_windows,
        "independent_regime_analysis": independent_regime_analysis,
        "frozen_search_family": {name: list(fields) for name, fields in FROZEN_SEARCH_FAMILY.items()},
        "frozen_ablation_family": {name: list(fields) for name, fields in FROZEN_ABLATION_FAMILY.items()},
        "ablation_results": ablation_results,
        "frozen_method_thresholds": dict(FROZEN_METHOD_THRESHOLDS),
        "holdout_power_analysis": holdout_power,
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


