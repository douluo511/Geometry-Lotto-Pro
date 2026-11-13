"""Bounded 2026-11-13 SHADOW example input; NOT verified official ingestion.

Pinned retrospective history through SSQ 2026121, DLT 26120 is copied from
the existing read-only V4.7 study; 9 later issuer rows per game were manually
transcribed in the 2026-11-13 research run. No untrusted post-target labels are
allowed. This artifact is educational replay, never formal G01/TSA evidence.
"""
from __future__ import annotations
import argparse
from datetime import date
import gzip
import json
from pathlib import Path
from research.harness_v46 import core

ORIGINAL_CANONICAL = "3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c"
SOURCE = Path(__file__).resolve().parents[1] / "harness_v46/evidence/recency_ablation_20261024/observations.json.gz"
APPENDIX = {
    "SSQ": [
        ("2026121", "2026-10-22", [2,7,20,24,26,30], [2]),
        ("2026122", "2026-10-25", [1,2,4,17,19,30], [9]),
        ("2026123", "2026-10-27", [4,5,20,21,26,30], [12]),
        ("2026124", "2026-10-29", [3,11,17,22,23,29], [9]),
        ("2026125", "2026-11-01", [4,6,10,15,26,27], [11]),
        ("2026126", "2026-11-03", [9,10,13,22,29,32], [12]),
        ("2026127", "2026-11-05", [13,14,19,25,29,32], [12]),
        ("2026128", "2026-11-08", [5,6,10,25,27,30], [11]),
        ("2026129", "2026-11-10", [3,9,16,20,25,30], [5]),
        ("2026130", "2026-11-12", [1,2,6,16,20,28], [2]),
    ],
    "DLT": [
        ("26120", "2026-10-21", [1,6,10,15,32], [3,4]),
        ("26121", "2026-10-24", [6,8,19,24,25], [1,8]),
        ("26122", "2026-10-26", [2,14,21,22,24], [2,12]),
        ("26123", "2026-10-28", [13,18,19,20,28], [9,11]),
        ("26124", "2026-10-31", [12,14,18,22,27], [1,9]),
        ("26125", "2026-11-02", [12,13,23,25,29], [7,10]),
        ("26126", "2026-11-04", [5,11,17,25,34], [4,6]),
        ("26127", "2026-11-07", [5,6,17,18,27], [3,12]),
        ("26128", "2026-11-09", [3,13,20,25,34], [9,12]),
        ("26129", "2026-11-11", [2,12,14,17,33], [7,8]),
    ],
}
TARGETS = {
    "SSQ": ("2026131", "2026-11-15"),
    "DLT": ("26130", "2026-11-14"),
}
AS_OF = "2026-11-13T09:53:39+00:00"


def build():
    pinned = json.loads(gzip.decompress(SOURCE.read_bytes()))
    if core.digest(pinned) != ORIGINAL_CANONICAL:
        raise ValueError("HISTORICAL_ARCHIVE_DIGEST_CONFLICT")
    if set(pinned) != {"SSQ", "DLT"}:
        raise ValueError("HISTORICAL_ARCHIVE_GAMES_INVALID")
    result = {}
    for game in ("SSQ", "DLT"):
        rows = list(pinned[game])
        appendix = [
            {"issue": issue, "draw_date": day, "front": front, "back": back}
            for issue, day, front, back in APPENDIX[game]
        ]
        if rows[-1] != appendix[0]:
            raise ValueError("ARCHIVED_OVERLAP_ROW_CONFLICT")
        rows += appendix[1:]
        target, target_day = TARGETS[game]
        if int(rows[-1]["issue"]) + 1 != int(target):
            raise ValueError("NEXT_ISSUE_CONFLICT")
        if not date.fromisoformat(rows[-1]["draw_date"]) < date.fromisoformat(target_day):
            raise ValueError("FUTURE_ROW_CONFLICT")
        result[game] = {"target_issue": target, "target_draw_date": target_day,
                        "as_of_utc": AS_OF, "history": rows,
                        "provenance": "UNVERIFIED_TRANSCRIPTION"}
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(build(), f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
