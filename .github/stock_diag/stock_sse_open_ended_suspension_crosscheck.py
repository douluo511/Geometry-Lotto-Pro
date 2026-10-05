from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import akshare as ak
import pandas as pd
import requests

REPLAY = Path("stock_sse_daily_suspension_replay.json")
OUT = Path("stock_sse_open_ended_suspension_crosscheck.json")
END = "2026-09-30"
END8 = "20260930"
FROZEN_CALENDAR_SHA256 = "45215343b187e337bc2b1ca3edbfc3055cdc77c0130b46c707bfe84ccf5513c9"
FROZEN_CALENDAR_ROWS = 2123


def digest_dates(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values)).encode("ascii")).hexdigest()


def normalize_dates(df, provider: str, start: str, end: str) -> list[str]:
    if df is None or getattr(df, "empty", True):
        raise RuntimeError(f"{provider}: empty history")
    date_col = next((c for c in df.columns if str(c).lower() in {"date", "日期", "trade_date"}), None)
    if date_col is None:
        raise RuntimeError(f"{provider}: no date column")
    s = pd.to_datetime(df[date_col], errors="coerce").dropna()
    s = s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))]
    values = sorted(set(s.dt.strftime("%Y-%m-%d").tolist()))
    if not values:
        raise RuntimeError(f"{provider}: no dates in diagnostic window")
    return values


def bounded(label, fn, attempts=3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            return fn(), {"status": "PASS", "attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                return None, {"status": "FAIL", "attempts": attempts, "errors": errors}
            time.sleep(2 ** (attempt - 1))


def yahoo_dates(code: str, start: str, end: str) -> list[str]:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) - timedelta(days=3)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=2)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.SS"
    params = {
        "period1": int(start_dt.timestamp()),
        "period2": int(end_dt.timestamp()),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "false",
    }
    resp = requests.get(
        url,
        params=params,
        timeout=(10, 25),
        headers={"User-Agent": "Mozilla/5.0 StockAI evidence probe"},
    )
    resp.raise_for_status()
    obj = resp.json()
    result = ((obj.get("chart") or {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise RuntimeError("yahoo: missing chart result")
    stamps = result.get("timestamp") or []
    tz8 = timezone(timedelta(hours=8))
    values = sorted({
        datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz8).date().isoformat()
        for ts in stamps
    })
    values = [d for d in values if start <= d <= end]
    if not values:
        raise RuntimeError("yahoo: empty date sequence")
    return values


def main() -> int:
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    prereq = replay["prerequisites"]
    missing = replay["replay"]["missing_end_sample"]

    if prereq.get("missing_end_count") != len(missing):
        raise AssertionError("missing-end sample is incomplete; refuse partial adjudication")
    if not missing:
        raise AssertionError("no open-ended intervals to cross-check")
    if prereq.get("invalid_range_count") != 0 or prereq.get("zero_trading_day_intersection_count") != 0:
        raise AssertionError("closed-interval replay has unresolved structural failures")
    if replay["adjudication"].get("shanghai_historical_suspension_intervals") != "SUPPORTED":
        raise AssertionError("official Shanghai interval corpus is not supported")
    if replay["adjudication"].get("end_stop_date_semantics") != "FINAL_SUSPENDED_DATE_SUPPORTED":
        raise AssertionError("endStopDate semantics are not supported")

    tx_idx, tx_idx_meta = bounded(
        "tencent_index",
        lambda: ak.stock_zh_index_daily_tx(symbol="sh000001"),
    )
    if tx_idx is None:
        raise RuntimeError("frozen trading calendar replay unavailable")
    calendar = normalize_dates(tx_idx, "tencent_index", "2018-01-01", END)
    calendar_sha = digest_dates(calendar)
    if len(calendar) != FROZEN_CALENDAR_ROWS or calendar_sha != FROZEN_CALENDAR_SHA256:
        raise AssertionError("Tencent calendar no longer matches frozen dual-provider identity")

    results = []
    all_supported = True

    for item in missing:
        code = str(item["code"])
        start8 = str(item["start"])
        start = f"{start8[:4]}-{start8[4:6]}-{start8[6:8]}"
        start_dt = datetime.fromisoformat(start)
        window_start = (start_dt - timedelta(days=45)).date().isoformat()
        prior_dates = [d for d in calendar if d < start]
        if not prior_dates:
            raise AssertionError(f"{code}: no prior trading day in frozen calendar")
        expected_prev = prior_dates[-1]

        providers = {}

        em, em_meta = bounded(
            "eastmoney",
            lambda c=code, ws=window_start: ak.stock_zh_a_hist(
                symbol=c,
                period="daily",
                start_date=ws.replace("-", ""),
                end_date=END8,
                adjust="",
            ),
        )
        if em is not None:
            try:
                providers["eastmoney"] = {
                    "status": "PASS",
                    "dates": normalize_dates(em, "eastmoney", window_start, END),
                    "transport": em_meta,
                }
            except Exception as exc:
                providers["eastmoney"] = {"status": "FAIL", "error": repr(exc), "transport": em_meta}
        else:
            providers["eastmoney"] = em_meta

        tx, tx_meta = bounded(
            "tencent",
            lambda c=code, ws=window_start: ak.stock_zh_a_hist_tx(
                symbol="sh" + c,
                start_date=ws.replace("-", ""),
                end_date=END8,
                adjust="",
            ),
        )
        if tx is not None:
            try:
                providers["tencent"] = {
                    "status": "PASS",
                    "dates": normalize_dates(tx, "tencent", window_start, END),
                    "transport": tx_meta,
                }
            except Exception as exc:
                providers["tencent"] = {"status": "FAIL", "error": repr(exc), "transport": tx_meta}
        else:
            providers["tencent"] = tx_meta

        yd, y_meta = bounded("yahoo", lambda c=code, ws=window_start: yahoo_dates(c, ws, END))
        if yd is not None:
            providers["yahoo"] = {"status": "PASS", "dates": yd, "transport": y_meta}
        else:
            providers["yahoo"] = y_meta

        successful = {
            name: info for name, info in providers.items()
            if info.get("status") == "PASS"
        }
        checks = {}
        for name, info in successful.items():
            dates = info["dates"]
            post_start = [d for d in dates if start <= d <= END]
            checks[name] = {
                "last_date": dates[-1],
                "expected_previous_trading_date": expected_prev,
                "last_date_matches_expected_previous": dates[-1] == expected_prev,
                "post_start_trade_dates": post_start,
                "no_trade_on_or_after_open_interval_start": len(post_start) == 0,
                "date_count": len(dates),
                "date_sha256": digest_dates(dates),
            }

        supporting = [
            name for name, check in checks.items()
            if check["last_date_matches_expected_previous"]
            and check["no_trade_on_or_after_open_interval_start"]
        ]
        supported = len(supporting) >= 2
        all_supported = all_supported and supported

        results.append({
            "code": code,
            "name": item.get("name"),
            "start": start,
            "row_sha256": item.get("row_sha256"),
            "expected_previous_trading_date": expected_prev,
            "providers": providers,
            "checks": checks,
            "supporting_independent_providers": supporting,
            "status": "SUPPORTED_OPEN_THROUGH_WINDOW_END" if supported else "NOT VERIFIED",
        })

    report = {
        "schema": "stock-sse-open-ended-suspension-crosscheck-v1",
        "frozen_window_end": END,
        "calendar": {
            "provider": "tencent_replay",
            "frozen_dual_provider_identity_sha256": FROZEN_CALENDAR_SHA256,
            "observed_sha256": calendar_sha,
            "rows": len(calendar),
            "status": "PASS",
            "transport": tx_idx_meta,
        },
        "open_ended_interval_count": len(missing),
        "results": results,
        "adjudication": {
            "open_ended_interval_resolution": "SUPPORTED" if all_supported else "NOT VERIFIED",
            "historical_daily_suspension_state": (
                "SUPPORTED_SHANGHAI_ONLY" if all_supported else "NOT VERIFIED"
            ),
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "beijing_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This combines the already-supported official SSE closed-interval replay with "
            "independent market-history evidence for every open-ended interval. It can support "
            "Shanghai daily suspension state only; it does not prove historical ST-name state, "
            "Beijing coverage, full A-share HISTORICAL_ST_PIT, or Final."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
