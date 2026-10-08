from __future__ import annotations

from datetime import date
import hashlib
import math

from .domain import DailyBar
from .freshness import select_completed_market_rows
from .netclient import NetClient
from .source_tencent import _code


KLINE_FULL_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"


def _history_windows(requested_rows: int) -> list[tuple[str, str, int]]:
    """Return bounded date windows for long-history retrieval.

    Short requests preserve the original single-request path. Long requests use
    overlapping yearly windows so we can both exceed Tencent's per-response
    history cap and detect inconsistent overlapping payloads.
    """
    target = max(30, min(int(requested_rows), 1200))
    current_year = date.today().year
    if target <= 500:
        return [
            (
                f"{current_year - 1}-01-01",
                f"{current_year + 2}-01-01",
                640,
            )
        ]

    window_count = min(8, max(2, math.ceil(target / 220) + 1))
    windows: list[tuple[str, str, int]] = []
    for offset in range(window_count):
        year = current_year - offset
        windows.append((f"{year}-01-01", f"{year + 1}-02-15", 360))
    return windows


def _same_observation(left: DailyBar, right: DailyBar) -> bool:
    if left.symbol != right.symbol or left.trade_date != right.trade_date:
        return False
    for field in ("open", "close", "high", "low", "volume", "amount"):
        a = float(getattr(left, field))
        b = float(getattr(right, field))
        scale = max(abs(a), abs(b), 1.0)
        if abs(a - b) > 1e-9 * scale:
            return False
    if left.turnover_rate is None or right.turnover_rate is None:
        return left.turnover_rate is right.turnover_rate
    a = float(left.turnover_rate)
    b = float(right.turnover_rate)
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1.0)


def fetch_daily_bars_tencent_full(
    client: NetClient,
    symbol: str,
    limit: int = 260,
    adjustment: str = "qfq",
) -> tuple[list[DailyBar], dict]:
    """Tencent field-complete K-line path with explicit adjustment identity.

    For requests above 500 rows, multiple overlapping production windows are
    retrieved. Duplicate dates must be byte-semantically consistent after
    parsing; a disagreement fails closed rather than silently choosing one.
    """
    target = max(30, min(int(limit), 1200))
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
    by_date: dict[str, DailyBar] = {}
    metas = []
    payload_hashes: list[str] = []

    for start_date, end_date, request_count in _history_windows(target):
        start_year = start_date[:4]
        variable = f"kline_dayqfq{start_year}" if fq == "qfq" else f"kline_day{start_year}"
        params = {
            "_var": variable,
            "param": f"{code},day,{start_date},{end_date},{request_count},{fq}",
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
        metas.append(meta)
        payload_hash = str(meta.payload_sha256 or "")
        if len(payload_hash) != 64:
            raise ValueError("Tencent full payload hash is missing or malformed")
        payload_hashes.append(payload_hash)

        root = obj.get("data")
        if not isinstance(root, dict):
            raise ValueError("Tencent full response missing data object")
        stock = root.get(code)
        if not isinstance(stock, dict):
            raise ValueError("Tencent full response missing symbol object")
        rows_raw = stock.get(expected_key)
        if not isinstance(rows_raw, list) or len(rows_raw) < 30:
            raise ValueError(f"Tencent full response missing required {expected_key} rows")

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
            parsed = DailyBar(
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
                raw_sha256=payload_hash,
            )
            previous = by_date.get(trade_date)
            if previous is not None and not _same_observation(previous, parsed):
                raise ValueError(
                    f"Tencent full overlapping history disagrees on {trade_date}; refusing mixed adjustment history"
                )
            by_date[trade_date] = parsed

    rows = [by_date[key] for key in sorted(by_date)]
    rows, completed_selection = select_completed_market_rows(rows)
    rows = rows[-target:]
    if len(rows) < 30:
        raise ValueError("Tencent full response has insufficient unique valid rows")

    if len(payload_hashes) == 1:
        lineage_hash = payload_hashes[0]
    else:
        lineage_hash = hashlib.sha256("|".join(payload_hashes).encode("ascii")).hexdigest()

    latest_meta = max(metas, key=lambda x: float(x.retrieved_at_unix))
    return rows, {
        "provider": "tencent_public_full_kline",
        "url": latest_meta.url,
        "urls": [m.url for m in metas],
        "http_status": latest_meta.status,
        "payload_sha256": lineage_hash,
        "source_payload_sha256s": payload_hashes,
        "retrieved_at_unix": max(float(m.retrieved_at_unix) for m in metas),
        "row_count": len(rows),
        "completed_session_selection": completed_selection,
        "requested_row_count": target,
        "history_coverage_satisfied": len(rows) >= target,
        "history_window_count": len(metas),
        "price_adjustment": adjustment_label,
        "requested_adjustment": fq,
        "content_type": latest_meta.content_type,
        "content_type_policy": latest_meta.content_type_policy,
        "field_contract": "date/open/close/high/low/volume/turnover/amount",
        "unit_contract": "volume=shares; turnover_rate=fraction; amount=CNY",
    }
