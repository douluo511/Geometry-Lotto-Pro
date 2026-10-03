from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    trade_date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    pct_change: float
    turnover_rate: float | None
    provider: str
    raw_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitalObservation:
    symbol: str
    asof: str
    price_return_5d: float | None
    price_return_20d: float | None
    amount_ratio_5d_vs_20d: float | None
    turnover_ratio_5d_vs_20d: float | None
    activity_state: str
    true_capital_identity: str
    conclusion_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
