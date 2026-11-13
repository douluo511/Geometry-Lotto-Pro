"""Deterministic invented offline fixtures for mother V1 CI, never live results."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path


def invented_bundle(n=130):
    if n < 120 or n > 250:
        raise ValueError("TEST_FIXTURE_SIZE_INVALID")
    cases = {}
    for game in ("SSQ", "DLT"):
        last = date(2026, 11, 12 if game == "SSQ" else 11)
        issue_first = 2026001 if game == "SSQ" else 26001
        history = []
        for i in range(n):
            day = last - timedelta(days=n - 1 - i)
            if game == "SSQ":
                front = sorted((i * 3 + j * 5) % 33 + 1 for j in range(6))
                back = [(i % 16) + 1]
            else:
                front = sorted((i * 3 + j * 7) % 35 + 1 for j in range(5))
                back = sorted([(i % 12) + 1, ((i + 5) % 12) + 1])
            issue = str(issue_first + i)
            history.append({"issue": issue, "draw_date": day.isoformat(),
                            "front": front, "back": back})
        cases[game] = {
            "target_issue": str(issue_first + n),
            "target_draw_date": "2026-11-15" if game == "SSQ" else "2026-11-14",
            "as_of_utc": "2026-11-13T10:00:00+00:00",
            "provenance": "HISTORICAL_REPLAY_UNVERIFIED",
            "history": history,
        }
    return cases


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(invented_bundle(), target, ensure_ascii=False,
                  sort_keys=True, indent=2)


if __name__ == "__main__":
    main()
