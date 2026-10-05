from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import requests

from stock_sse_calendar_semantic_probe import (
    daily_suspension_probe,
    fetch_window_all_pages,
    interval_active_stock_codes,
    snapshot_active_stock_codes,
)

DATES = (
    "20220104", "20220105",
    "20240104", "20240105",
    "20260923", "20260924", "20260925", "20260928", "20260929", "20260930",
)


def digest_codes(codes):
    return hashlib.sha256("\n".join(sorted(codes)).encode("ascii")).hexdigest()


def main():
    session = requests.Session()

    # Reuse the already-audited official SSE interval and daily-snapshot clients.
    windows = []
    for year in range(2018, 2027):
        end = f"{year}1231" if year < 2026 else "20260930"
        windows.append(fetch_window_all_pages(session, year, f"{year}0101", end))
    intervals = []
    for w in windows:
        intervals.extend(w["intervals"])

    intervals_by_code = defaultdict(list)
    for row in intervals:
        code = str(row.get("code") or "").strip()
        if code:
            intervals_by_code[code].append({
                "name": row.get("name"),
                "start": row.get("start"),
                "end": row.get("end"),
                "control_type": row.get("control_type"),
                "reason": row.get("reason"),
            })

    daily = {}
    comparisons = {}
    code_set_hashes = {}
    mismatch_classes = Counter()

    for d in DATES:
        item = daily_suspension_probe(session, d)
        snapshot_set, snapshot_rows = snapshot_active_stock_codes(item)
        event_set, event_rows = interval_active_stock_codes(intervals, d, True)

        snap_by_code = defaultdict(list)
        for row in snapshot_rows:
            snap_by_code[row.get("code")].append(row)

        snapshot_only = sorted(snapshot_set - event_set)
        interval_only = sorted(event_set - snapshot_set)
        exact = snapshot_set == event_set

        taxonomy = []
        for code in snapshot_only:
            all_intervals = intervals_by_code.get(code, [])
            active_like = [
                x for x in all_intervals
                if x.get("start") and x["start"] <= d and (not x.get("end") or d <= x["end"])
            ]
            cls = "SNAPSHOT_ONLY_NO_INTERVAL" if not all_intervals else (
                "SNAPSHOT_ONLY_INTERVAL_NOT_ACTIVE" if not active_like else
                "SNAPSHOT_ONLY_FILTER_DIFFERENCE"
            )
            mismatch_classes[cls] += 1
            taxonomy.append({
                "code": code,
                "side": "snapshot_only",
                "class": cls,
                "snapshot_rows": snap_by_code.get(code, []),
                "all_intervals": all_intervals[-8:],
                "active_like_intervals": active_like,
            })

        event_row_by_code = defaultdict(list)
        for row in event_rows:
            event_row_by_code[row.get("code")].append(row)
        for code in interval_only:
            cls = "INTERVAL_ONLY_NOT_ACTIVE_IN_SNAPSHOT"
            mismatch_classes[cls] += 1
            taxonomy.append({
                "code": code,
                "side": "interval_only",
                "class": cls,
                "snapshot_rows": snap_by_code.get(code, []),
                "event_rows": event_row_by_code.get(code, []),
                "all_intervals": intervals_by_code.get(code, [])[-8:],
            })

        snap_hash = digest_codes(snapshot_set)
        event_hash = digest_codes(event_set)
        code_set_hashes[d] = {
            "snapshot_sha256": snap_hash,
            "interval_sha256": event_hash,
        }
        daily[d] = {
            "raw_row_count": item.get("row_count"),
            "response_sha256": item.get("sha256"),
            "snapshot_active_codes": sorted(snapshot_set),
            "snapshot_active_count": len(snapshot_set),
            "snapshot_parsed_rows": snapshot_rows,
        }
        comparisons[d] = {
            "exact_match": exact,
            "snapshot_count": len(snapshot_set),
            "interval_count": len(event_set),
            "snapshot_only": snapshot_only,
            "interval_only": interval_only,
            "taxonomy": taxonomy,
        }

    sep_dates = ("20260923", "20260924", "20260925", "20260928", "20260929", "20260930")
    sep_hashes = [code_set_hashes[d]["snapshot_sha256"] for d in sep_dates]
    date_discrimination = len(set(sep_hashes)) > 1
    exact_dates = [d for d, x in comparisons.items() if x["exact_match"]]
    mismatch_dates = [d for d, x in comparisons.items() if not x["exact_match"]]

    report = {
        "schema": "stock-sse-suspension-interface-mismatch-v1",
        "authoritative_product_head": "43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
        "dates": list(DATES),
        "interval_windows": [
            {
                "year": w["year"],
                "raw_row_count": w["raw_row_count"],
                "interval_parse_count": w["interval_parse_count"],
            }
            for w in windows
        ],
        "daily": daily,
        "comparisons": comparisons,
        "code_set_hashes": code_set_hashes,
        "mismatch_class_counts": dict(sorted(mismatch_classes.items())),
        "summary": {
            "exact_dates": exact_dates,
            "mismatch_dates": mismatch_dates,
            "snapshot_date_discrimination_20260923_to_20260930": date_discrimination,
            "unique_snapshot_sets_20260923_to_20260930": len(set(sep_hashes)),
        },
        "adjudication": {
            "daily_snapshot_endpoint_reachable": "PASS",
            "interval_endpoint_reachable": "PASS",
            "snapshot_date_filter_discrimination": "SUPPORTED" if date_discrimination else "NOT VERIFIED",
            "daily_snapshot_vs_interval_semantics": "CONTRADICTED" if mismatch_dates else "SUPPORTED",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }

    Path("stock_sse_suspension_interface_mismatch.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "exact_dates": exact_dates,
        "mismatch_dates": mismatch_dates,
        "mismatch_class_counts": dict(sorted(mismatch_classes.items())),
        "snapshot_date_discrimination": date_discrimination,
        "unique_snapshot_sets": len(set(sep_hashes)),
        "comparisons": {
            d: {
                "exact": x["exact_match"],
                "snapshot_count": x["snapshot_count"],
                "interval_count": x["interval_count"],
                "snapshot_only": x["snapshot_only"],
                "interval_only": x["interval_only"],
            }
            for d, x in comparisons.items()
        },
        "historical_daily_suspension_state": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    # A contradiction is a successful diagnostic outcome here; Final/business stay fail-closed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
