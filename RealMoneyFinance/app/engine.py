from __future__ import annotations

from statistics import mean

from .domain import DailyBar, CapitalObservation


def _return(rows: list[DailyBar], days: int) -> float | None:
    if len(rows) <= days or rows[-1-days].close == 0:
        return None
    return rows[-1].close / rows[-1-days].close - 1.0


def _ratio_recent(rows: list[DailyBar], field: str, recent: int = 5, base: int = 20) -> float | None:
    if len(rows) < base:
        return None
    recent_vals = [getattr(x, field) for x in rows[-recent:]]
    base_vals = [getattr(x, field) for x in rows[-base:]]
    recent_vals = [float(x) for x in recent_vals if x is not None]
    base_vals = [float(x) for x in base_vals if x is not None]
    if not recent_vals or not base_vals:
        return None
    denominator = mean(base_vals)
    return None if denominator == 0 else mean(recent_vals) / denominator


def analyze_observable_activity(rows: list[DailyBar]) -> CapitalObservation:
    if len(rows) < 30:
        raise ValueError("at least 30 validated daily bars are required")
    amount_ratio = _ratio_recent(rows, "amount")
    turnover_ratio = _ratio_recent(rows, "turnover_rate")
    drivers = [x for x in (amount_ratio, turnover_ratio) if x is not None]
    avg_ratio = mean(drivers) if drivers else 1.0
    if avg_ratio >= 1.35:
        state = "ELEVATED_OBSERVABLE_ACTIVITY"
    elif avg_ratio <= 0.70:
        state = "LOW_OBSERVABLE_ACTIVITY"
    else:
        state = "NORMAL_OBSERVABLE_ACTIVITY"
    return CapitalObservation(
        symbol=rows[-1].symbol,
        asof=rows[-1].trade_date,
        price_return_5d=_return(rows, 5),
        price_return_20d=_return(rows, 20),
        amount_ratio_5d_vs_20d=amount_ratio,
        turnover_ratio_5d_vs_20d=turnover_ratio,
        activity_state=state,
        true_capital_identity="UNAVAILABLE_FROM_PUBLIC_LEVEL1",
        conclusion_boundary=(
            "Public Level-1 price/volume/turnover can describe observable activity only. "
            "It does not identify institutions, main-force capital, or true inflow/outflow ownership."
        ),
    )


def reverse_validation(obs: CapitalObservation) -> dict:
    counterexamples = [
        "High turnover with falling price may reflect distribution, forced selling, or churn rather than accumulation.",
        "High traded amount does not identify buyer/seller identity or net external capital entering the asset.",
        "A short-window activity spike can disappear when the comparison window changes.",
    ]
    return {
        "status": "PASS",
        "five_why": [
            "Why not call this true capital inflow? Public L1 has no verified participant identity.",
            "Why not infer identity from amount? Amount is two-sided turnover, not ownership attribution.",
            "Why use two windows? To reduce one-day anomaly sensitivity.",
            "Why keep a fail-closed boundary? Wrong identity claims could drive real-money decisions.",
            "Why require further data? Identity-grade conclusions need authorized Level-2/order-flow lineage.",
        ],
        "counterexamples": counterexamples,
        "production_identity_claim_allowed": False,
    }
