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


def fetch_daily_bars_tencent_full_history(
    client: NetClient,
    symbol: str,
    limit: int = 1200,
    adjustment: str = "qfq",
) -> tuple[list[DailyBar], dict]:
    """Collect long Tencent history from bounded windows with overlap proof.\n\n    The frozen coverage-first selector is unchanged. Adjacent request windows\n    overlap for one month and duplicate dates must contain identical market\n    values; otherwise the provider fails closed instead of silently stitching\n    incompatible qfq scales.\n    """
    requested = max(30, min(int(limit), 2000))
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
    current_year = date.today().year
    by_date: dict[str, DailyBar] = {}
    components = []
    overlap_verified_rows = 0

    def same_market_values(left: DailyBar, right: DailyBar) -> bool:
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

    # Two calendar years stay below Tencent's 640-row request bound. Older
    # windows overlap the next-newer window for one month so qfq scale identity
    # is independently checked instead of assumed.
    for window_index in range(10):
        end_year = current_year + 1 - (window_index * 2)
        start_year = end_year - 2
        start_date = f"{start_year}-01-01"
        end_date = f"{end_year}-01-01" if window_index == 0 else f"{end_year}-02-01"
        start_bound = date.fromisoformat(start_date)
        end_bound = date.fromisoformat(end_date)
        variable = f"kline_day{fq}_{start_year}_{end_year}"
        params = {
            "_var": variable,
            "param": f"{code},day,{start_date},{end_date},640,{fq}",
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

        component = {
            "window_index": window_index,
            "start_date": start_date,
            "end_date": end_date,
            "payload_sha256": meta.payload_sha256,
            "retrieved_at_unix": meta.retrieved_at_unix,
            "row_count": len(rows_raw),
            "url": meta.url,
        }
        duplicate_overlap_rows = 0

        for row in rows_raw:
            if not isinstance(row, list) or len(row) < 9:
                raise ValueError("Tencent full-history kline schema changed or row is incomplete")
            trade_date = str(row[0])
            try:
                trade_day = date.fromisoformat(trade_date)
            except Exception as exc:
                raise ValueError(f"invalid Tencent full-history trade date: {trade_date!r}") from exc
            if not (start_bound <= trade_day < end_bound):
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
            candidate = DailyBar(
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
            prior = by_date.get(trade_date)
            if prior is not None:
                duplicate_overlap_rows += 1
                if not same_market_values(prior, candidate):
                    raise ValueError(
                        "Tencent qfq/raw scale mismatch across overlapping history windows "
                        f"on {trade_date}"
                    )
                overlap_verified_rows += 1
            else:
                by_date[trade_date] = candidate

        component["duplicate_overlap_rows"] = duplicate_overlap_rows
        components.append(component)

        if len(by_date) >= requested and overlap_verified_rows > 0:
            break

    rows = [by_date[key] for key in sorted(by_date)]
    rows = rows[-requested:]
    if len(rows) < 30:
        raise ValueError("Tencent full-history response has insufficient unique valid rows")
    validate_market_rows(rows)

    lineage_material = "\n".join(
        f"{item['window_index']}|{item['start_date']}|{item['end_date']}|{item['payload_sha256']}|{item['row_count']}"
        for item in components
    ).encode("utf-8")
    aggregate_payload_sha256 = hashlib.sha256(lineage_material).hexdigest()

    return rows, {
        "provider": "tencent_public_full_kline",
        "url": components[0]["url"] if components else KLINE_FULL_URL,
        "http_status": 200,
        "payload_sha256": aggregate_payload_sha256,
        "component_payload_sha256": [item["payload_sha256"] for item in components],
        "history_windows": components,
        "retrieved_at_unix": max((float(item["retrieved_at_unix"]) for item in components), default=0.0),
        "row_count": len(rows),
        "requested_row_count": requested,
        "requested_coverage_met": len(rows) >= requested,
        "price_adjustment": adjustment_label,
        "requested_adjustment": fq,
        "field_contract": "date/open/close/high/low/volume/turnover/amount",
        "unit_contract": "volume=shares; turnover_rate=fraction; amount=CNY",
        "history_contract": "bounded-two-year-windows-one-month-overlap-verified",
        "overlap_consistency": "PASS" if overlap_verified_rows > 0 else "NOT VERIFIED",
        "overlap_verified_rows": overlap_verified_rows,
    }
