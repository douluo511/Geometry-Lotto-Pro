from __future__ import annotations

from datetime import date, datetime, time as clock_time, timedelta, timezone
from typing import Any


CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
SSE_2026_SCHEDULE_SOURCE = (
    "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
    "c/c_20251222_10802510.shtml"
)
SSE_2026_SCHEDULE_PUBLISHED = "2025-12-22"
SSE_2026_CLOSED_RANGES = (
    ("2026-01-01", "2026-01-03"),
    ("2026-02-15", "2026-02-23"),
    ("2026-04-04", "2026-04-06"),
    ("2026-05-01", "2026-05-05"),
    ("2026-06-19", "2026-06-21"),
    ("2026-09-25", "2026-09-27"),
    ("2026-10-01", "2026-10-07"),
)
DAILY_BAR_SETTLEMENT_MARGIN = clock_time(15, 30)


class FreshnessCalendarUnavailable(RuntimeError):
    pass


def _in_frozen_closure(day: date) -> bool:
    for start_text, end_text in SSE_2026_CLOSED_RANGES:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        if start <= day <= end:
            return True
    return False


def is_sse_session(day: date) -> bool:
    if day.year != 2026:
        raise FreshnessCalendarUnavailable(
            f"no frozen authoritative SSE closure schedule for year {day.year}"
        )
    return day.weekday() < 5 and not _in_frozen_closure(day)


def expected_latest_completed_session(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = current.astimezone(CHINA_STANDARD_TIME)
    if local.year != 2026:
        raise FreshnessCalendarUnavailable(
            f"no frozen authoritative SSE closure schedule for year {local.year}"
        )
    probe = local.date()
    if is_sse_session(probe) and local.time() < DAILY_BAR_SETTLEMENT_MARGIN:
        probe -= timedelta(days=1)
    for _ in range(40):
        if is_sse_session(probe):
            return probe.isoformat()
        probe -= timedelta(days=1)
    raise FreshnessCalendarUnavailable("could not resolve a completed SSE session within 40 days")


def qualify_source_freshness(
    asof: str,
    cross_source_validation: dict[str, Any] | None,
    *,
    retrieved_at_unix: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Qualify production daily-bar freshness against the frozen official SSE schedule.

    PASS requires: (1) two independently agreeing production providers,
    (2) a current network receipt, and (3) market as-of equal to the latest
    completed SSE session. Unknown calendar years fail closed as NOT VERIFIED.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = current.astimezone(CHINA_STANDARD_TIME)

    try:
        market_date = date.fromisoformat(str(asof))
    except ValueError:
        return {
            "status": "FAIL",
            "reason": "invalid market date",
            "asof": str(asof),
            "china_time": local.isoformat(),
        }

    cross = cross_source_validation if isinstance(cross_source_validation, dict) else {}
    providers = cross.get("providers")
    providers_ok = (
        cross.get("status") == "PASS"
        and isinstance(providers, list)
        and len(set(str(x) for x in providers if x)) >= 2
    )
    if not providers_ok:
        return {
            "status": "NOT VERIFIED",
            "reason": "freshness requires at least two independently agreeing production sources",
            "asof": market_date.isoformat(),
            "china_time": local.isoformat(),
            "cross_source_status": cross.get("status", "NOT VERIFIED"),
            "providers": providers if isinstance(providers, list) else [],
            "authoritative_schedule_reference": SSE_2026_SCHEDULE_SOURCE,
        }

    try:
        expected = expected_latest_completed_session(current)
    except FreshnessCalendarUnavailable as exc:
        return {
            "status": "NOT VERIFIED",
            "reason": str(exc),
            "asof": market_date.isoformat(),
            "china_time": local.isoformat(),
            "providers": providers,
            "authoritative_schedule_reference": SSE_2026_SCHEDULE_SOURCE,
        }

    if retrieved_at_unix is None:
        return {
            "status": "NOT VERIFIED",
            "reason": "current production retrieval timestamp missing",
            "asof": market_date.isoformat(),
            "expected_completed_session": expected,
            "china_time": local.isoformat(),
            "providers": providers,
            "authoritative_schedule_reference": SSE_2026_SCHEDULE_SOURCE,
        }

    receipt_age_seconds = current.timestamp() - float(retrieved_at_unix)
    base = {
        "asof": market_date.isoformat(),
        "expected_completed_session": expected,
        "china_time": local.isoformat(),
        "receipt_age_seconds": round(receipt_age_seconds, 3),
        "cross_source_status": cross.get("status"),
        "providers": providers,
        "calendar": "SSE_2026_OFFICIAL_FROZEN",
        "calendar_published": SSE_2026_SCHEDULE_PUBLISHED,
        "authoritative_schedule_reference": SSE_2026_SCHEDULE_SOURCE,
        "settlement_margin_local": DAILY_BAR_SETTLEMENT_MARGIN.isoformat(),
    }
    if receipt_age_seconds < -300:
        return {**base, "status": "FAIL", "reason": "retrieval timestamp is materially in the future"}
    if receipt_age_seconds > 900:
        return {**base, "status": "FAIL", "reason": "production retrieval receipt is older than 900 seconds"}
    if market_date.isoformat() != expected:
        return {
            **base,
            "status": "FAIL",
            "reason": "market date does not equal latest completed SSE session",
        }
    return {
        **base,
        "status": "PASS",
        "reason": "two live providers agree and market date equals latest completed SSE session",
    }
