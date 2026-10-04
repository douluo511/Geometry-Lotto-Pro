from __future__ import annotations

import json
import re

from .domain import DailyBar
from .netclient import NetClient


KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _code(symbol: str) -> str:
    code = "".join(ch for ch in str(symbol) if ch.isdigit())
    if len(code) != 6:
        raise ValueError("symbol must contain exactly 6 digits")
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return prefix + code


def _coerce_json(obj):
    if isinstance(obj, dict):
        return obj
    raise ValueError("Tencent response root must be object")


def fetch_daily_bars_tencent(client: NetClient, symbol: str, limit: int = 120) -> tuple[list[DailyBar], dict]:
    code = _code(symbol)
    params = {"param": f"{code},day,,,{max(30, min(int(limit), 320))},qfq"}
    obj, meta = client.get_json(
        KLINE_URL,
        params,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"},
        allow_mislabeled_json=True,
    )
    root = _coerce_json(obj).get("data")
    if not isinstance(root, dict):
        raise ValueError("Tencent response missing data object")
    stock = root.get(code)
    if not isinstance(stock, dict):
        raise ValueError("Tencent response missing symbol object")
    rows_raw = stock.get("qfqday") or stock.get("day")
    if not isinstance(rows_raw, list) or len(rows_raw) < 30:
        raise ValueError("Tencent response has insufficient kline rows")

    rows: list[DailyBar] = []
    for row in rows_raw:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("Tencent kline schema changed or row is incomplete")
        trade_date = str(row[0])
        open_p, close_p, high_p, low_p, volume = map(float, row[1:6])
        amount = float(row[6]) if len(row) > 6 and str(row[6]).strip() not in {"", "None"} else 0.0
        rows.append(DailyBar(
            symbol=code[-6:],
            trade_date=trade_date,
            open=open_p,
            close=close_p,
            high=high_p,
            low=low_p,
            volume=volume,
            amount=amount,
            pct_change=((close_p / open_p) - 1.0) * 100.0 if open_p else 0.0,
            turnover_rate=None,
            provider="tencent_public_kline",
            raw_sha256=meta.payload_sha256,
        ))
    rows.sort(key=lambda x: x.trade_date)
    return rows, {
        "provider": "tencent_public_kline",
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(rows),
        "content_type": meta.content_type,
        "content_type_policy": meta.content_type_policy,
    }
