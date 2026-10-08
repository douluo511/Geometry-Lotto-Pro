"""Canonical commitments bind research rows to the audited source series."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable

from .domain import DailyBar


def market_row_commitment(row: DailyBar) -> str:
    numeric_fields = ("open", "close", "high", "low", "volume", "amount", "pct_change", "turnover_rate")
    record = {"symbol":row.symbol, "trade_date":row.trade_date,
              "provider":row.provider, "raw_sha256":row.raw_sha256}
    for field in numeric_fields:
        value = getattr(row, field)
        if value is None and field == "turnover_rate":
            record[field] = None
        else:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("non-finite series commitment input")
            record[field] = number.hex()
    canonical = json.dumps(record, sort_keys=True, separators=(",",":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def market_series_commitments(rows: Iterable[DailyBar]) -> dict[str,str]:
    result = {}
    for row in rows:
        if row.trade_date in result:
            raise ValueError("duplicate date in series commitment")
        result[row.trade_date] = market_row_commitment(row)
    return result


def commitment_index_digest(index: dict[str,str]) -> str:
    canonical = json.dumps(index, sort_keys=True, separators=(",",":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
