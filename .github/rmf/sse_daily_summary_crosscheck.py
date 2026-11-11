from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = ROOT / "RealMoneyFinance"
sys.path.insert(0, str(PRODUCT_ROOT))

from app.netclient import NetClient

URL = "https://query.sse.com.cn/commonQuery.do"
CURRENT_DAILY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C"
CURRENT_DAILY_PRODUCT_CODE = "01,02,03,11,17"
HEADERS = {
    "Host": "query.sse.com.cn",
    "Referer": "https://www.sse.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
DATES = ("2021-12-24", "2023-01-13", "2024-04-15", "2025-07-10", "2026-09-30")
EXPECTED_RECONSTRUCTED = {
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


def _clean_row(row: dict) -> dict:
    return {
        "PRODUCT_CODE": str(row.get("PRODUCT_CODE") or "").strip(),
        "TRADE_DATE": str(row.get("TRADE_DATE") or "").strip(),
        "LIST_NUM": row.get("LIST_NUM"),
        "AVG_PE_RATE": row.get("AVG_PE_RATE"),
        "TOTAL_VALUE": row.get("TOTAL_VALUE"),
        "NEGO_VALUE": row.get("NEGO_VALUE"),
        "TRADE_AMT": row.get("TRADE_AMT"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--network-evidence", required=True, type=Path)
    args = ap.parse_args()

    client = NetClient(args.network_evidence, connect_timeout=5, read_timeout=30, max_attempts=3)
    rows_by_date: dict[str, dict] = {}
    parsed: dict[str, dict] = {}
    mismatches: list[dict] = []

    for day in DATES:
        obj, meta = client.get_json(
            URL,
            {
                "sqlId": CURRENT_DAILY_SQL_ID,
                "PRODUCT_CODE": CURRENT_DAILY_PRODUCT_CODE,
                "type": "inParams",
                "SEARCH_DATE": day,
            },
            headers=HEADERS,
            allow_mislabeled_json=True,
        )
        rows = obj.get("result") if isinstance(obj, dict) else None
        rows_by_date[day] = {
            "payload_sha256": meta.payload_sha256,
            "retrieved_at_unix": meta.retrieved_at_unix,
            "result_type": type(rows).__name__,
            "rows": [_clean_row(row) for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else [],
        }

        if not isinstance(rows, list):
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "official SSE current daily endpoint result is not a row list",
                "result_type": type(rows).__name__,
            }
            continue
        if not rows:
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "official SSE current daily endpoint returned no rows for this date",
            }
            continue
        if not all(isinstance(row, dict) for row in rows):
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "official SSE current daily endpoint contained a non-object row",
            }
            continue

        expected_trade_date = day.replace("-", "")
        main_candidates = [
            row for row in rows
            if str(row.get("PRODUCT_CODE") or "").strip() == "01"
            and str(row.get("TRADE_DATE") or "").strip() == expected_trade_date
        ]
        star_candidates = [
            row for row in rows
            if str(row.get("PRODUCT_CODE") or "").strip() == "03"
            and str(row.get("TRADE_DATE") or "").strip() == expected_trade_date
        ]
        if len(main_candidates) != 1 or len(star_candidates) != 1:
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": "could not identify unique date-bound PRODUCT_CODE 01 + 03 rows",
                "product_codes": [
                    str(row.get("PRODUCT_CODE") or "").strip() for row in rows
                ],
                "trade_dates": [
                    str(row.get("TRADE_DATE") or "").strip() for row in rows
                ],
            }
            continue

        try:
            main_count = _num(main_candidates[0].get("LIST_NUM"))
            star_count = _num(star_candidates[0].get("LIST_NUM"))
        except ValueError as exc:
            parsed[day] = {
                "status": "NOT VERIFIED",
                "reason": str(exc),
            }
            continue

        total = main_count + star_count
        parsed[day] = {
            "status": "PASS",
            "main_a_product_code": "01",
            "main_a_list_num": main_count,
            "star_product_code": "03",
            "star_list_num": star_count,
            "main_plus_star": total,
        }
        expected = EXPECTED_RECONSTRUCTED.get(day)
        if expected is not None and total != expected:
            mismatches.append(
                {"date": day, "official": total, "reconstructed": expected}
            )

    comparable_dates = [
        day
        for day, row in parsed.items()
        if row.get("status") == "PASS" and day in EXPECTED_RECONSTRUCTED
    ]
    status = "PASS" if not mismatches and len(comparable_dates) >= 3 else "FAIL"
    evidence = {
        "schema": "rmf-sse-historical-membership-daily-summary-crosscheck-v2",
        "status": status,
        "scope": "independent official SSE daily listed-count cross-check of historical membership reconstruction",
        "source_url": URL,
        "sql_id": CURRENT_DAILY_SQL_ID,
        "product_code_query": CURRENT_DAILY_PRODUCT_CODE,
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
        "capital_deployment_ready": False,
        "boundary": (
            "Agreement with independent official SSE daily listed-count aggregates supports the "
            "listing/delisting membership reconstruction only. It does not prove that the current "
            "listing/delisting fields were historically knowable at each past date, nor that the "
            "research symbol was selected ex ante from a frozen investable universe."
        ),
    }
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
