from __future__ import annotations

from datetime import date

from .domain import DailyBar, validate_market_rows
from .netclient import NetClient
from .source_tencent import _code


KLINE_FULL_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"


def fetch_daily_bars_tencent_full(
    client: NetClient,
    symbol: str,
    limit: int = 260,
    adjustment: str = "qfq",
) -> tuple[list[DailyBar], dict]:
    """Tencent field-complete K-line path with explicit adjustment identity."""
    mode = str(adjustment).strip().lower()
    if mode in {"none", "raw", "unadjusted"}:
        fq = "none"
        expected_key = "day"
        adjustment_label = "unadjusted"
    elif mode == "qfq":
        fq = "qfq"
        expected_key = "qfqday"
        adjustment_label = "qfq"
    else:
        raise ValueError("adjustment must be qfq or raw/none/unadjusted")

    code = _code(symbol)
    year = date.today().year - 1
    variable = f"kline_dayqfq{year}" if fq == "qfq" else f"kline_day{year}"
    params = {
        "_var": variable,
        "param": f"{code},day,{year}-01-01,{year + 2}-01-01,640,{fq}",
        "r": "0.8205512681390605",
    }
    obj, meta = client.get_jsonp_object(
        KLINE_FULL_URL,
        params,
        variable,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Referer": "https://gu.qq.com/",
            "Accept": "application/javascript,text/javascript,text/plain,*/*",
        },
    )
    root = obj.get("data")
    if not isinstance(root, dict):
        raise ValueError("Tencent full response missing data object")
    stock = root.get(code)
    if not isinstance(stock, dict):
        raise ValueError("Tencent full response missing symbol object")
    rows_raw = stock.get(expected_key)
    if not isinstance(rows_raw, list) or len(rows_raw) < 30:
        raise ValueError(f"Tencent full response missing required {expected_key} rows")

    by_date: dict[str, DailyBar] = {}
    for row in rows_raw:
        if not isinstance(row, list) or len(row) < 9:
            raise ValueError("Tencent full kline schema changed or row is incomplete")
        trade_date = str(row[0])
        open_p = float(row[1])
        close_p = float(row[2])
        high_p = float(row[3])
        low_p = float(row[4])
        volume = float(row[5])
        turnover_rate = float(row[7]) / 100.0
        amount = float(row[8]) * 10000.0
        if not code.startswith(("sh688", "sz399", "sh000", "sz000")):
            volume *= 100.0
        if min(open_p, close_p, high_p, low_p, volume, amount, turnover_rate) <= 0:
            raise ValueError(f"Tencent full kline contains non-positive required field on {trade_date}")
        by_date[trade_date] = DailyBar(
            symbol=code[-6:],
            trade_date=trade_date,
            open=open_p,
            close=close_p,
            high=high_p,
            low=low_p,
            volume=volume,
            amount=amount,
            pct_change=((close_p / open_p) - 1.0) * 100.0,
            turnover_rate=turnover_rate,
            provider="tencent_public_full_kline",
            raw_sha256=meta.payload_sha256,
        )

    rows = [by_date[key] for key in sorted(by_date)]
    rows = rows[-max(30, min(int(limit), 500)):]
    if len(rows) < 30:
        raise ValueError("Tencent full response has insufficient unique valid rows")
    validate_market_rows(rows)
    return rows, {
        "provider": "tencent_public_full_kline",
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(rows),
        "price_adjustment": adjustment_label,
        "requested_adjustment": fq,
        "content_type": meta.content_type,
        "content_type_policy": meta.content_type_policy,
        "field_contract": "date/open/close/high/low/volume/turnover/amount",
        "unit_contract": "volume=shares; turnover_rate=fraction; amount=CNY",
    }
