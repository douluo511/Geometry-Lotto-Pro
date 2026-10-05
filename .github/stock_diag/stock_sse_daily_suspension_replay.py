from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from pathlib import Path

import akshare as ak
import pandas as pd

INTERVAL_EVIDENCE = Path("stock_sse_historical_suspension_query.json")
SEMANTIC_EVIDENCE = Path("stock_sse_suspension_field_semantics.json")
START = "2018-01-01"
END = "2026-09-30"
START8 = "20180101"
END8 = "20260930"
SSE_A_PREFIXES = ("600", "601", "603", "605", "688")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_dates(df, provider: str) -> list[str]:
    if df is None or df.empty:
        raise RuntimeError(f"{provider}: empty Shanghai Composite history")
    cols = list(df.columns)
    date_col = next(
        (c for c in cols if str(c).lower() in {"date", "日期", "trade_date"}),
        None,
    )
    if date_col is None:
        raise RuntimeError(f"{provider}: no date column: {cols}")
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    dates = dates[
        (dates >= pd.Timestamp(START))
        & (dates <= pd.Timestamp(END))
    ]
    values = sorted(set(dates.dt.strftime("%Y-%m-%d").tolist()))
    if len(values) < 1500:
        raise RuntimeError(f"{provider}: implausibly short date sequence {len(values)}")
    return values


def date_sha(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values)).encode("ascii")).hexdigest()


def canonical_sha(rows) -> str:
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def flatten_intervals(evidence: dict) -> list[dict]:
    unique = {}
    for window in evidence.get("windows") or []:
        for row in window.get("intervals") or []:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("row_sha256") or "")
            if rid:
                unique[rid] = row
    return sorted(
        unique.values(),
        key=lambda x: (
            str(x.get("start") or ""),
            str(x.get("code") or ""),
            str(x.get("end") or ""),
            str(x.get("row_sha256") or ""),
        ),
    )


def main() -> int:
    intervals_evidence = load(INTERVAL_EVIDENCE)
    semantic_evidence = load(SEMANTIC_EVIDENCE)

    interval_status = (
        intervals_evidence.get("adjudication", {})
        .get("shanghai_historical_suspension_intervals_2018_to_20260930")
    )
    semantic_status = semantic_evidence.get("end_stop_date_semantics")

    em = ak.stock_zh_index_daily_em(
        symbol="sh000001", start_date=START8, end_date=END8
    )
    tx = ak.stock_zh_index_daily_tx(symbol="sh000001")
    em_dates = normalize_dates(em, "eastmoney")
    tx_dates = normalize_dates(tx, "tencent")
    calendar_equal = em_dates == tx_dates
    trading_dates = em_dates if calendar_equal else []
    trading_compact = [x.replace("-", "") for x in trading_dates]

    intervals = flatten_intervals(intervals_evidence)
    a_share = [
        x for x in intervals
        if str(x.get("code") or "").startswith(SSE_A_PREFIXES)
        and str(x.get("start") or "") <= END8
    ]

    missing_end = []
    invalid_range = []
    zero_intersection = []
    daily_pairs = set()
    interval_trade_day_counts = []

    for item in a_share:
        code = str(item.get("code") or "")
        start = str(item.get("start") or "")
        end = item.get("end")
        if not end:
            missing_end.append({
                "code": code,
                "name": item.get("name"),
                "start": start,
                "row_sha256": item.get("row_sha256"),
            })
            continue
        end = str(end)
        if end < start:
            invalid_range.append({
                "code": code,
                "start": start,
                "end": end,
                "row_sha256": item.get("row_sha256"),
            })
            continue

        lo_key = max(start, START8)
        hi_key = min(end, END8)
        if hi_key < lo_key:
            continue
        lo = bisect_left(trading_compact, lo_key)
        hi = bisect_right(trading_compact, hi_key)
        dates = trading_compact[lo:hi]
        if not dates:
            zero_intersection.append({
                "code": code,
                "name": item.get("name"),
                "start": start,
                "end": end,
                "row_sha256": item.get("row_sha256"),
            })
            continue
        interval_trade_day_counts.append(len(dates))
        for d in dates:
            daily_pairs.add((d, code))

    pairs = sorted(
        [{"trade_date": d, "code": c} for d, c in daily_pairs],
        key=lambda x: (x["trade_date"], x["code"]),
    )
    suspended_dates = sorted({x["trade_date"] for x in pairs})
    suspended_codes = sorted({x["code"] for x in pairs})

    prerequisites = {
        "official_interval_corpus": interval_status,
        "end_stop_date_semantics": semantic_status,
        "calendar_provider_exact_equality": calendar_equal,
        "calendar_rows_eastmoney": len(em_dates),
        "calendar_rows_tencent": len(tx_dates),
        "calendar_sha256_eastmoney": date_sha(em_dates),
        "calendar_sha256_tencent": date_sha(tx_dates),
        "a_share_interval_count": len(a_share),
        "missing_end_count": len(missing_end),
        "invalid_range_count": len(invalid_range),
        "zero_trading_day_intersection_count": len(zero_intersection),
    }

    supported = (
        interval_status == "SUPPORTED"
        and semantic_status == "FINAL_SUSPENDED_DATE_SUPPORTED"
        and calendar_equal
        and len(trading_dates) > 0
        and len(a_share) > 0
        and not missing_end
        and not invalid_range
        and not zero_intersection
        and len(pairs) > 0
    )

    report = {
        "schema": "stock-sse-daily-suspension-replay-v1",
        "frozen_window": {"start": START, "end": END},
        "frozen_a_share_prefixes": list(SSE_A_PREFIXES),
        "prerequisites": prerequisites,
        "replay": {
            "daily_state_pair_count": len(pairs),
            "unique_suspended_codes": len(suspended_codes),
            "suspended_trade_date_count": len(suspended_dates),
            "first_suspended_trade_date": suspended_dates[0] if suspended_dates else None,
            "last_suspended_trade_date": suspended_dates[-1] if suspended_dates else None,
            "daily_state_sha256": canonical_sha(pairs),
            "suspended_code_sha256": canonical_sha(suspended_codes),
            "missing_end_sample": missing_end[:20],
            "invalid_range_sample": invalid_range[:20],
            "zero_intersection_sample": zero_intersection[:20],
            "min_interval_trading_days": min(interval_trade_day_counts) if interval_trade_day_counts else None,
            "max_interval_trading_days": max(interval_trade_day_counts) if interval_trade_day_counts else None,
        },
        "adjudication": {
            "research_trading_date_sequence": "SUPPORTED" if calendar_equal else "NOT VERIFIED",
            "shanghai_historical_suspension_intervals": interval_status or "NOT VERIFIED",
            "end_stop_date_semantics": semantic_status or "NOT VERIFIED",
            "historical_daily_suspension_state": (
                "SUPPORTED_SHANGHAI_ONLY" if supported else "NOT VERIFIED"
            ),
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "beijing_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }

    Path("stock_sse_daily_suspension_replay.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
