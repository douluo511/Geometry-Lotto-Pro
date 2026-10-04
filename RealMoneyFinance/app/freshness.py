from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
MAX_CALENDAR_AGE_DAYS = 7


def qualify_source_freshness(
    asof: str,
    cross_source_validation: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_calendar_age_days: int = MAX_CALENDAR_AGE_DAYS,
) -> dict[str, Any]:
    """Fail-closed source freshness qualification.

    Freshness requires independent cross-source PASS first. The accepted market
    date must not be in the future and must be no more than the frozen maximum
    calendar age in China Standard Time. A calendar-age cap deliberately does
    not infer a missing exchange calendar; long closures eventually fail closed
    instead of silently blessing stale data.
    """
    if max_calendar_age_days < 0:
        raise ValueError("max_calendar_age_days must be nonnegative")
    try:
        market_date = date.fromisoformat(str(asof))
    except ValueError:
        return {"status": "FAIL", "reason": "invalid market date", "asof": str(asof)}

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    china_date = current.astimezone(CHINA_STANDARD_TIME).date()
    age_days = (china_date - market_date).days

    cross = cross_source_validation if isinstance(cross_source_validation, dict) else {}
    providers = cross.get("providers")
    providers_ok = (
        cross.get("status") == "PASS"
        and isinstance(providers, list)
        and len(set(str(x) for x in providers if x)) >= 2
    )
    base = {
        "asof": market_date.isoformat(),
        "china_date": china_date.isoformat(),
        "age_calendar_days": age_days,
        "max_calendar_age_days": int(max_calendar_age_days),
        "cross_source_status": cross.get("status", "NOT VERIFIED"),
        "providers": providers if isinstance(providers, list) else [],
    }
    if age_days < 0:
        return {**base, "status": "FAIL", "reason": "market date is in the future"}
    if not providers_ok:
        return {
            **base,
            "status": "NOT VERIFIED",
            "reason": "freshness requires at least two independently agreeing production sources",
        }
    if age_days > max_calendar_age_days:
        return {**base, "status": "FAIL", "reason": "latest agreed market date is stale"}
    return {
        **base,
        "status": "PASS",
        "reason": "two independent production sources agree and market date is within frozen age limit",
    }
