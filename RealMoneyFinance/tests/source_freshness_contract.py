from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from app.freshness import qualify_source_freshness


def main() -> int:
    cross = {"status": "PASS", "providers": ["provider_a", "provider_b"]}

    holiday_now = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)
    valid = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert valid["status"] == "PASS"
    assert valid["expected_completed_session"] == "2026-09-30"

    stale = qualify_source_freshness(
        "2026-09-29",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert stale["status"] == "FAIL"
    assert stale["reason"] == "market date does not equal latest completed SSE session"

    pre_reopen_close = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
    pre = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=pre_reopen_close.timestamp() - 60,
        now=pre_reopen_close,
    )
    assert pre["status"] == "PASS"
    assert pre["expected_completed_session"] == "2026-09-30"

    post_reopen_close = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
    reopened = qualify_source_freshness(
        "2026-10-08",
        cross,
        retrieved_at_unix=post_reopen_close.timestamp() - 60,
        now=post_reopen_close,
    )
    assert reopened["status"] == "PASS"
    assert reopened["expected_completed_session"] == "2026-10-08"

    one_source = qualify_source_freshness(
        "2026-09-30",
        {"status": "NOT VERIFIED", "providers": ["provider_a"]},
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert one_source["status"] == "NOT VERIFIED"

    old_receipt = qualify_source_freshness(
        "2026-09-30",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 1800,
        now=holiday_now,
    )
    assert old_receipt["status"] == "FAIL"

    future_year = datetime(2027, 1, 2, 5, 0, tzinfo=timezone.utc)
    unsupported_calendar = qualify_source_freshness(
        "2026-12-31",
        cross,
        retrieved_at_unix=future_year.timestamp() - 60,
        now=future_year,
    )
    assert unsupported_calendar["status"] == "NOT VERIFIED"

    malformed = qualify_source_freshness(
        "not-a-date",
        cross,
        retrieved_at_unix=holiday_now.timestamp() - 60,
        now=holiday_now,
    )
    assert malformed["status"] == "FAIL"

    evidence = {
        "status": "PASS",
        "authority": valid["authoritative_schedule_reference"],
        "cases": {
            "national_day_holiday_latest_completed_session": valid,
            "stale_market_date": stale,
            "reopen_before_daily_bar_settles": pre,
            "reopen_after_daily_bar_settles": reopened,
            "one_source": one_source,
            "old_receipt": old_receipt,
            "unsupported_calendar_year": unsupported_calendar,
            "malformed": malformed,
        },
    }
    Path("source_freshness_contract_evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
