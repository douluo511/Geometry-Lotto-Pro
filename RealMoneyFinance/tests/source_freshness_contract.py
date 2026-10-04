from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from app.freshness import qualify_source_freshness


def main() -> int:
    now = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)
    cross = {"status": "PASS", "providers": ["provider_a", "provider_b"]}

    valid = qualify_source_freshness("2026-09-30", cross, now=now)
    assert valid["status"] == "PASS"
    assert valid["age_calendar_days"] == 4

    stale = qualify_source_freshness("2026-09-26", cross, now=now)
    assert stale["status"] == "FAIL"
    assert stale["reason"] == "latest agreed market date is stale"

    future = qualify_source_freshness("2026-10-05", cross, now=now)
    assert future["status"] == "FAIL"

    one_source = qualify_source_freshness(
        "2026-09-30",
        {"status": "NOT VERIFIED", "providers": ["provider_a"]},
        now=now,
    )
    assert one_source["status"] == "NOT VERIFIED"

    malformed = qualify_source_freshness("not-a-date", cross, now=now)
    assert malformed["status"] == "FAIL"

    evidence = {
        "status": "PASS",
        "cases": {
            "valid_cross_source_recent": valid,
            "stale": stale,
            "future": future,
            "one_source": one_source,
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
