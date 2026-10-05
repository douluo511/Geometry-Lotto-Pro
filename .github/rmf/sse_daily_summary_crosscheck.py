from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = ROOT / "RealMoneyFinance"
sys.path.insert(0, str(PRODUCT_ROOT))

from app.netclient import NetClient

URL = "https://query.sse.com.cn/commonQuery.do"
HEADERS = {
    "Host": "query.sse.com.cn",
    "Referer": "https://www.sse.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
DATES = ("2021-12-24", "2023-01-13", "2024-04-15", "2025-07-10", "2026-09-30")
EXPECTED_RECONSTRUCTED = {
    # 2021-12-24 is intentionally left unset until computed from canonical SSE
    # listing/delisting rows in the companion membership evidence.
    "2023-01-13": 2170,
    "2024-04-15": 2268,
    "2025-07-10": 2283,
    "2026-09-30": 2320,
}


def _num(value: object) -> int:
    raw = str(value or "").strip().replace(",", "")
    if not re.fullmatch(r"\d+", raw):
        raise ValueError(f"invalid integer field {raw!r}")
    return int(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--network-evidence", required=True, type=Path)
    args = ap.parse_args()

    client = NetClient(args.network_evidence, connect_timeout=5, read_timeout=30, max_attempts=3)
    rows_by_date = {}
    parsed = {}
    mismatches = []
    for day in DATES:
        obj, meta = client.get_json(
            URL,
            {"isPagination": "false", "sqlId": "COMMON_SSE_XXPL_LSSJL_S", "STAT_DATE": day},
            headers=HEADERS,
            allow_mislabeled_json=True,
        )
        rows = obj.get("result")
        if not isinstance(rows, list):
            raise RuntimeError(f"SSE daily summary malformed for {day}")
        if not rows:
            rows_by_date[day] = {
                "payload_sha256": meta.payload_sha256,
                "retrieved_at_unix": meta.retrieved_at_unix,
                "rows": [],
            }
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "official SSE daily summary returned no rows",
            }
            continue
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("SSE summary row is not object")
            cleaned.append({
                "STAT_DATE": str(row.get("STAT_DATE") or day),
                "STAT_NAME": str(row.get("STAT_NAME") or "").strip(),
                "STAT_NUM": row.get("STAT_NUM"),
                "TRADE_AMOUNT": row.get("TRADE_AMOUNT"),
                "TOTAL_MARKET_CAP": row.get("TOTAL_MARKET_CAP"),
                "FLOAT_MARKET_CAP": row.get("FLOAT_MARKET_CAP"),
            })
        rows_by_date[day] = {
            "payload_sha256": meta.payload_sha256,
            "retrieved_at_unix": meta.retrieved_at_unix,
            "rows": cleaned,
        }

        # SSE rows expose categories such as 主板A / 科创板. Require an exact
        # unambiguous pair instead of inferring from total stock count.
        main_candidates = [r for r in cleaned if "主板A" in r["STAT_NAME"]]
        star_candidates = [r for r in cleaned if "科创板" in r["STAT_NAME"]]
        if len(main_candidates) != 1 or len(star_candidates) != 1:
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "could not identify unique 主板A + 科创板 rows",
                "stat_names": [r["STAT_NAME"] for r in cleaned],
            }
            continue
        main_count = _num(main_candidates[0]["STAT_NUM"])
        star_count = _num(star_candidates[0]["STAT_NUM"])
        total = main_count + star_count
        parsed[day] = {
            "status": "PASS",
            "main_a": main_count,
            "star": star_count,
            "main_plus_star": total,
        }
        expected = EXPECTED_RECONSTRUCTED.get(day)
        if expected is not None and total != expected:
            mismatches.append({"date": day, "official": total, "reconstructed": expected})

    comparable_dates = [
        day for day, row in parsed.items()
        if row.get("status") == "PASS" and day in EXPECTED_RECONSTRUCTED
    ]
    status = "PASS" if not mismatches and len(comparable_dates) >= 3 else "FAIL"
    evidence = {
        "schema": "rmf-sse-historical-membership-daily-summary-crosscheck-v1",
        "status": status,
        "scope": "independent official SSE aggregate cross-check of historical membership counts",
        "source_url": URL,
        "sql_id": "COMMON_SSE_XXPL_LSSJL_S",
        "dates": list(DATES),
        "official_results": parsed,
        "raw_source_evidence": rows_by_date,
        "reconstructed_counts_checked": EXPECTED_RECONSTRUCTED,
        "mismatches": mismatches,
        "comparable_dates": comparable_dates,
        "minimum_comparable_dates": 3,
        "historical_membership_crosscheck": status,
        "historical_pit_availability": "NOT VERIFIED",
        "survivorship_selection_control": "NOT VERIFIED",
        "boundary": (
            "Agreement with SSE historical listed-count aggregates independently supports the "
            "listing/delisting membership reconstruction. It does not prove point-in-time feature "
            "availability or ex-ante security selection."
        ),
    }
    args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
