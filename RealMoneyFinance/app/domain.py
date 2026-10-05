from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import math
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


def validate_market_rows(rows: list[DailyBar]) -> None:
    """Reject malformed/non-finite source data before research or persistence."""
    if not rows:
        raise ValueError("empty market rows")
    dates = []
    for row in rows:
        date.fromisoformat(row.trade_date)
        dates.append(row.trade_date)
        prices = (row.open, row.close, row.high, row.low)
        numbers = (*prices, row.volume, row.amount, row.pct_change)
        if any(not math.isfinite(float(x)) for x in numbers):
            raise ValueError("market rows contain non-finite numeric fields")
        if min(prices) <= 0 or row.volume < 0 or row.amount < 0:
            raise ValueError("market prices must be positive and activity nonnegative")
        if row.low > min(row.open, row.close) or row.high < max(row.open, row.close):
            raise ValueError("market OHLC bounds are inconsistent")
        if row.turnover_rate is not None and (
            not math.isfinite(float(row.turnover_rate)) or row.turnover_rate < 0
        ):
            raise ValueError("invalid turnover rate")
        if row.symbol != rows[0].symbol:
            raise ValueError("market rows must describe one symbol")
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("market dates must be unique and chronological")


@dataclass(frozen=True)
class CapitalObservation:
    symbol: str
    asof: str
    price_return_5d: float | None
    price_return_20d: float | None
    amount_ratio_5d_vs_20d: float | None
    turnover_ratio_5d_vs_20d: float | None
    volume_ratio_5d_vs_20d: float | None
    activity_state: str
    true_capital_identity: str
    conclusion_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

