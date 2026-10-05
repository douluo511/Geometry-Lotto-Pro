from __future__ import annotations

from datetime import date
import hashlib

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


def _same_market_values(left: DailyBar, right: DailyBar) -> bool:
    """Cross-window duplicate dates must encode the same market observation."""
    if left.symbol != right.symbol or left.trade_date != right.trade_date:
        return False
    for field in ("open", "close", "high", "low", "volume", "amount", "pct_change", "turnover_rate"):
        a = getattr(left, field)
        b = getattr(right, field)
        if a is None or b is None:
            if a is not b:
                return False
            continue
        a = float(a)
        b = float(b)
        tolerance = max(1e-9, 1e-9 * max(abs(a), abs(b), 1.0))
        if abs(a - b) > tolerance:
            return False
    return True


def _fetch_tencent_full_window(
    client: NetClient,
    symbol: str,
    start: date,
    end: date,
    adjustment: str,
) -> tuple[dict[str, DailyBar], object]:
    mode = str(adjustment).strip().lower()
    if mode in {"none", "raw", "unadjusted"}:
        fq = "none"
        expected_key = "day"
    elif mode == "qfq":
        fq = "qfq"
        expected_key = "qfqday"
    else:
        raise ValueError("adjustment must be qfq or raw/none/unadjusted")

    code = _code(symbol)
    variable = f"kline_dayqfq{start.year}" if fq == "qfq" else f"kline_day{start.year}"
    params = {
        "_var": variable,
        "param": f"{code},day,{start.isoformat()},{end.isoformat()},640,{fq}",
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
        raise ValueError("Tencent full-history response missing data object")
    stock = root.get(code)
    if not isinstance(stock, dict):
        raise ValueError("Tencent full-history response missing symbol object")
    rows_raw = stock.get(expected_key)
    if not isinstance(rows_raw, list):
        raise ValueError(f"Tencent full-history response missing required {expected_key} rows")

    by_date: dict[str, DailyBar] = {}
    for row in rows_raw:
        if not isinstance(row, list) or len(row) < 9:
            raise ValueError("Tencent full-history kline schema changed or row is incomplete")
        trade_date = str(row[0])
        try:
            trade_day = date.fromisoformat(trade_date)
        except Exception as exc:
            raise ValueError(f"invalid Tencent full-history trade date: {trade_date!r}") from exc
        if not (start <= trade_day < end):
            continue

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
            raise ValueError(f"Tencent full-history kline contains non-positive required field on {trade_date}")
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
            provider="tencent_public_full_kline_history",
            raw_sha256=meta.payload_sha256,
        )
    return by_date, meta


def fetch_daily_bars_tencent_full_history(
    client: NetClient,
    symbol: str,
    limit: int = 1200,
    adjustment: str = "qfq",
) -> tuple[list[DailyBar], dict]:
    """Fetch long field-complete Tencent history without lowering row coverage.

    The Tencent full-history endpoint is queried in bounded two-year windows.
    Adjacent windows overlap for one calendar month. Duplicate dates in those
    overlaps must contain identical market values; any mismatch fails closed.
    Each raw response remains independently recorded by NetClient, while the
    returned metadata binds the component payload hashes into one lineage hash.
    """
    requested = max(30, int(limit))
    if requested > 1600:
        raise ValueError("Tencent full-history adapter supports at most 1600 requested rows")

    mode = str(adjustment).strip().lower()
    if mode in {"none", "raw", "unadjusted"}:
        fq = "none"
        adjustment_label = "unadjusted"
    elif mode == "qfq":
        fq = "qfq"
        adjustment_label = "qfq"
    else:
        raise ValueError("adjustment must be qfq or raw/none/unadjusted")

    current_year = date.today().year
    merged: dict[str, DailyBar] = {}
    component_hashes: list[str] = []
    component_urls: list[str] = []
    retrieved_times: list[float] = []
    content_types: list[str] = []
    window_evidence: list[dict] = []
    overlap_verified = 0

    for offset in (0, 2, 4, 6, 8):
        start_year = current_year - 1 - offset
        end_year = start_year + 2
        start = date(start_year, 1, 1)
        # Older windows overlap the next-newer window for one month so qfq scale
        # consistency is checked from real duplicate dates rather than assumed.
        end = date(end_year, 1, 1) if offset == 0 else date(end_year, 2, 1)
        rows_by_date, meta = _fetch_tencent_full_window(client, symbol, start, end, fq)

        duplicate_count = 0
        for trade_date, row in rows_by_date.items():
            prior = merged.get(trade_date)
            if prior is not None:
                duplicate_count += 1
                if not _same_market_values(prior, row):
                    raise ValueError(
                        "Tencent qfq/raw scale mismatch across overlapping history windows "
                        f"on {trade_date}"
                    )
                overlap_verified += 1
                continue
            merged[trade_date] = row

        payload_hash = str(meta.payload_sha256)
        if len(payload_hash) != 64 or any(ch not in "0123456789abcdef" for ch in payload_hash.lower()):
            raise ValueError("Tencent full-history payload SHA-256 is missing or malformed")
        component_hashes.append(payload_hash.lower())
        component_urls.append(str(meta.url))
        retrieved_times.append(float(meta.retrieved_at_unix))
        content_types.append(str(meta.content_type))
        window_evidence.append({
            "start": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "row_count": len(rows_by_date),
            "duplicate_overlap_rows": duplicate_count,
            "payload_sha256": payload_hash.lower(),
        })

        if len(merged) >= requested and overlap_verified > 0:
            break

    rows = [merged[key] for key in sorted(merged)]
    if len(rows) < 30:
        raise ValueError("Tencent full-history response has insufficient unique valid rows")
    rows = rows[-requested:]
    validate_market_rows(rows)

    lineage_sha256 = hashlib.sha256(("\n".join(component_hashes) + "\n").encode("ascii")).hexdigest()
    return rows, {
        "provider": "tencent_public_full_kline_history",
        "url": component_urls[0],
        "urls": component_urls,
        "http_status": 200,
        "payload_sha256": lineage_sha256,
        "component_payload_sha256": component_hashes,
        "retrieved_at_unix": max(retrieved_times),
        "row_count": len(rows),
        "requested_rows": requested,
        "price_adjustment": adjustment_label,
        "requested_adjustment": fq,
        "content_type": content_types[0],
        "content_type_policy": "strict-assignment-json-multi-window",
        "field_contract": "date/open/close/high/low/volume/turnover/amount",
        "unit_contract": "volume=shares; turnover_rate=fraction; amount=CNY",
        "window_count": len(window_evidence),
        "windows": window_evidence,
        "overlap_consistency": "PASS" if overlap_verified > 0 else "NOT VERIFIED",
        "overlap_verified_rows": overlap_verified,
        "coverage_start": rows[0].trade_date,
        "coverage_end": rows[-1].trade_date,
    }
