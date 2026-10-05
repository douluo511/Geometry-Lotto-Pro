from __future__ import annotations

from datetime import date, datetime
import math
import re
from statistics import median
from typing import Iterable

from .domain import DailyBar, validate_market_rows
from .netclient import NetClient

EASTMONEY_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_NAME = "RPT_SHAREBONUS_DET"


def _date_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except Exception:
        return None


def _finite_nonnegative(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def fetch_share_bonus_events(client: NetClient, symbol: str, page_size: int = 100) -> tuple[list[dict], dict]:
    symbol = str(symbol).strip()
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("corporate-action symbol must be six digits")
    obj, meta = client.get_json(
        EASTMONEY_DATACENTER_URL,
        {
            "reportName": REPORT_NAME,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{symbol}")',
            "pageNumber": 1,
            "pageSize": max(20, min(int(page_size), 500)),
            "sortColumns": "EX_DIVIDEND_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Referer": "https://data.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    result = obj.get("result")
    if not isinstance(result, dict):
        raise ValueError("Eastmoney corporate-action response missing result")
    raw_rows = result.get("data")
    if not isinstance(raw_rows, list):
        raise ValueError("Eastmoney corporate-action response missing result.data")

    events = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise ValueError("Eastmoney corporate-action row is not an object")
        if str(row.get("SECURITY_CODE", symbol)).strip() != symbol:
            continue
        ex_date = _date_text(row.get("EX_DIVIDEND_DATE"))
        if not ex_date:
            continue
        notice_date = _date_text(row.get("PLAN_NOTICE_DATE"))
        cash = _finite_nonnegative(row.get("PRETAX_BONUS_RMB"))
        bonus = _finite_nonnegative(row.get("BONUS_RATIO"))
        transfer = _finite_nonnegative(row.get("TRANSFER_RATIO"))
        if not any((cash or 0) > 0 for cash in (cash, bonus, transfer)):
            continue
        events.append({
            "symbol": symbol,
            "plan_notice_date": notice_date,
            "ex_dividend_date": ex_date,
            "pretax_bonus_rmb": cash,
            "bonus_ratio": bonus,
            "transfer_ratio": transfer,
            "assign_progress": str(row.get("ASSIGN_PROGRESS") or ""),
        })
    events.sort(key=lambda x: x["ex_dividend_date"])
    return events, {
        "provider": "eastmoney_share_bonus_datacenter",
        "report_name": REPORT_NAME,
        "url": meta.url,
        "http_status": meta.status,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "event_count": len(events),
        "schema_fields": [
            "SECURITY_CODE", "PLAN_NOTICE_DATE", "EX_DIVIDEND_DATE",
            "PRETAX_BONUS_RMB", "BONUS_RATIO", "TRANSFER_RATIO", "ASSIGN_PROGRESS",
        ],
    }


def verify_corporate_action_lineage(
    qfq_rows: Iterable[DailyBar],
    raw_rows: Iterable[DailyBar],
    events: list[dict],
    qfq_meta: dict,
    raw_meta: dict,
    event_meta: dict,
    *,
    factor_change_tolerance: float = 0.0005,
    max_match_calendar_days: int = 7,
) -> dict:
    qfq = list(qfq_rows)
    raw = list(raw_rows)
    validate_market_rows(qfq)
    validate_market_rows(raw)
    if not qfq or not raw or qfq[0].symbol != raw[0].symbol:
        return {"status": "NOT VERIFIED", "reason": "qfq/raw symbol evidence is missing or mismatched"}
    if qfq_meta.get("price_adjustment") != "qfq" or raw_meta.get("price_adjustment") != "unadjusted":
        return {"status": "NOT VERIFIED", "reason": "qfq and raw adjustment identities are not independently present"}
    providers = {
        "qfq": qfq_meta.get("provider"),
        "raw": raw_meta.get("provider"),
        "events": event_meta.get("provider"),
    }
    if (
        providers["qfq"] != "tencent_public_full_kline"
        or providers["raw"] != "tencent_public_full_kline"
        or providers["events"] != "eastmoney_share_bonus_datacenter"
    ):
        return {"status": "NOT VERIFIED", "reason": "corporate-action source provider identity mismatch",
                "source_providers": providers}

    hashes = {
        "qfq_payload_sha256": str(qfq_meta.get("payload_sha256") or ""),
        "raw_payload_sha256": str(raw_meta.get("payload_sha256") or ""),
        "event_payload_sha256": str(event_meta.get("payload_sha256") or ""),
    }
    if any(not re.fullmatch(r"[0-9a-f]{64}", v) for v in hashes.values()):
        return {"status": "NOT VERIFIED", "reason": "source payload hash lineage is incomplete or malformed", **hashes}
    if hashes["qfq_payload_sha256"] == hashes["raw_payload_sha256"]:
        return {"status": "NOT VERIFIED", "reason": "qfq/raw payloads are not independently distinguishable", **hashes}

    qmap = {x.trade_date: float(x.close) for x in qfq}
    rmap = {x.trade_date: float(x.close) for x in raw}
    dates = sorted(set(qmap) & set(rmap))
    if len(dates) < 60:
        return {"status": "NOT VERIFIED", "reason": "qfq/raw overlap is too short", "overlap_rows": len(dates), **hashes}

    factor_points = []
    for d in dates:
        raw_close = rmap[d]
        qfq_close = qmap[d]
        if raw_close <= 0 or qfq_close <= 0:
            return {"status": "FAIL", "reason": "non-positive close in factor verification", "trade_date": d, **hashes}
        factor_points.append({
            "trade_date": d,
            "qfq_close": qfq_close,
            "raw_close": raw_close,
            "factor": qfq_close / raw_close,
        })

    # qfq and raw closes are price-tick rounded. A day-to-day ratio therefore
    # jitters even while the true adjustment factor is unchanged. Detect only
    # persistent factor-regime shifts by comparing five-session medians. The
    # threshold is bounded below by the caller's tolerance and raised only by
    # an explicit 0.01-price-tick error bound plus local MAD noise.
    window = 5
    half_tick = 0.005
    signals = []
    for split in range(window, len(factor_points) - window + 1):
        before = factor_points[split-window:split]
        after = factor_points[split:split+window]
        before_factor = median([x["factor"] for x in before])
        after_factor = median([x["factor"] for x in after])
        if before_factor <= 0 or after_factor <= 0:
            continue
        relative = abs(after_factor / before_factor - 1.0)

        before_q = median([x["qfq_close"] for x in before])
        before_r = median([x["raw_close"] for x in before])
        after_q = median([x["qfq_close"] for x in after])
        after_r = median([x["raw_close"] for x in after])
        rounding_bound = (
            half_tick / before_q + half_tick / before_r
            + half_tick / after_q + half_tick / after_r
        )
        before_mad = median([abs(x["factor"] - before_factor) for x in before]) / before_factor
        after_mad = median([abs(x["factor"] - after_factor) for x in after]) / after_factor
        local_noise = max(before_mad, after_mad)
        threshold = max(float(factor_change_tolerance), 2.0 * rounding_bound, 6.0 * local_noise)
        if relative > threshold:
            signals.append({
                "split_index": split,
                "previous_trade_date": before[-1]["trade_date"],
                "trade_date": after[0]["trade_date"],
                "previous_factor": before_factor,
                "factor": after_factor,
                "relative_change": relative,
                "effective_threshold": threshold,
                "rounding_error_bound": rounding_bound,
                "local_mad_ratio": local_noise,
            })

    # A single persistent step can trigger several neighboring rolling splits.
    # Collapse those signals into one regime change and keep the strongest split.
    clusters = []
    for signal in signals:
        if not clusters or signal["split_index"] > clusters[-1][-1]["split_index"] + window:
            clusters.append([signal])
        else:
            clusters[-1].append(signal)
    changes = []
    for cluster in clusters:
        strongest = max(cluster, key=lambda x: (x["relative_change"], -x["split_index"]))
        strongest = dict(strongest)
        strongest.pop("split_index", None)
        changes.append(strongest)

    valid_events = []
    for event in events:
        ex = _date_text(event.get("ex_dividend_date"))
        notice = _date_text(event.get("plan_notice_date"))
        if not ex or not notice or notice > ex:
            continue
        if ex < dates[0] or ex > dates[-1]:
            continue
        if not any(float(event.get(k) or 0) > 0 for k in ("pretax_bonus_rmb", "bonus_ratio", "transfer_ratio")):
            continue
        valid_events.append({**event, "ex_dividend_date": ex, "plan_notice_date": notice})

    matched = []
    unexplained = []
    used_events = set()
    for change in changes:
        change_day = date.fromisoformat(change["trade_date"])
        candidates = []
        for index, event in enumerate(valid_events):
            if index in used_events:
                continue
            ex_day = date.fromisoformat(event["ex_dividend_date"])
            delta = (change_day - ex_day).days
            if 0 <= delta <= max_match_calendar_days:
                candidates.append((delta, index, event))
        if not candidates:
            unexplained.append(change)
            continue
        delta, index, event = min(candidates, key=lambda x: (x[0], x[1]))
        used_events.add(index)
        matched.append({
            "event": event,
            "factor_change": change,
            "calendar_days_after_ex_date": delta,
        })

    unmatched_events = [e for i, e in enumerate(valid_events) if i not in used_events]
    point_in_time = bool(matched) and not unexplained
    return {
        "status": "PASS" if point_in_time else "NOT VERIFIED",
        "point_in_time_lineage": "PASS" if point_in_time else "NOT VERIFIED",
        "symbol": qfq[0].symbol,
        "overlap_start": dates[0],
        "overlap_end": dates[-1],
        "overlap_rows": len(dates),
        "factor_change_tolerance": factor_change_tolerance,
        "factor_detection_method": "persistent_median_regime_shift_v1",
        "factor_window_sessions": window,
        "price_tick": 0.01,
        "significant_factor_changes": len(changes),
        "verified_event_count": len(matched),
        "unexplained_factor_changes": len(unexplained),
        "matched_events": matched,
        "unexplained_changes": unexplained,
        "unmatched_valid_events": unmatched_events,
        "source_providers": providers,
        **hashes,
        "boundary": (
            "PASS proves observed persistent Tencent qfq/raw factor-regime shifts are explained by independently retrieved "
            "Eastmoney announced corporate-action dates in the overlapping window. It does not prove "
            "historical point-in-time availability of every research feature or execution-cost calibration."
        ),
        "reason": None if point_in_time else (
            "requires at least one announced event matched to an observed persistent qfq/raw factor-regime shift and no unexplained persistent shifts"
        ),
    }
