from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from stock_sse_historical_suspension_query import ENDPOINT, get, parse_json_or_jsonp

PAGE_SIZE = 500
FIRST_YEAR = 1990
LAST_YEAR = 2026
LAST_DATE = "20260930"
EQUITY_CODE = re.compile(r"^(600|601|603|605|688)\\d{3}$")


def compact(value):
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())[:8]


def fetch_page(session, year, page_no):
    start = "19901219" if year == 1990 else f"{year}0101"
    end = LAST_DATE if year == LAST_YEAR else f"{year}1231"
    params = {
        "isPagination": "true",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "pageHelp.pageSize": str(PAGE_SIZE),
        "pageHelp.pageNo": str(page_no),
        "productCode": "",
        "keyWords": "",
        "startStopDate": start,
        "endStopDate": end,
        "jsonCallBack": "jsonpCallback",
    }
    r, meta = get(session, ENDPOINT, params=params, attempts=3)
    raw = r.content
    payload, parsed_as = parse_json_or_jsonp(raw.decode(r.encoding or "utf-8", errors="replace"))
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
        raise RuntimeError("unexpected SSE payload shape")
    return payload, {
        "http_status": r.status_code,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "parsed_as": parsed_as,
        "attempt": meta["attempt"],
        "url": r.url,
        "start": start,
        "end": end,
    }


def canonical_row(row):
    keys = (
        "productCode", "productName", "controlType",
        "startStopDate", "endStopDate", "startStopTime", "endStopTime",
        "stopReason", "endStopReason", "startStopReason",
    )
    return {k: row.get(k) for k in keys if k in row}


def main():
    import requests
    session = requests.Session()
    years = []
    all_rows = []
    failures = []

    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        fetched = []
        pages = []
        try:
            first, meta = fetch_page(session, year, 1)
            page_help = first.get("pageHelp") if isinstance(first.get("pageHelp"), dict) else {}
            page_count = int(page_help.get("pageCount") or 1)
            total = int(page_help.get("total") or len(first["result"]))
            fetched.extend(first["result"])
            pages.append(meta)
            for page_no in range(2, page_count + 1):
                payload, meta = fetch_page(session, year, page_no)
                fetched.extend(payload["result"])
                pages.append(meta)
                time.sleep(0.05)

            starts = [compact(r.get("startStopDate")) for r in fetched if isinstance(r, dict)]
            starts = [d for d in starts if len(d) == 8]
            start_in_window = sum(1 for d in starts if meta["start"] <= d <= meta["end"])
            complete = len(fetched) == total
            years.append({
                "year": year,
                "start": meta["start"],
                "end": meta["end"],
                "page_count_claimed": page_count,
                "pages_fetched": len(pages),
                "total_claimed": total,
                "rows_fetched": len(fetched),
                "start_dates_recognized": len(starts),
                "start_dates_in_window": start_in_window,
                "pagination_complete": complete,
                "page_hashes": [x["sha256"] for x in pages],
            })
            if not complete:
                failures.append(f"{year}: fetched={len(fetched)} total={total}")
            all_rows.extend(fetched)
        except Exception as exc:
            failures.append(f"{year}: {type(exc).__name__}: {exc}")
            years.append({"year": year, "error": f"{type(exc).__name__}: {exc}", "pagination_complete": False})

    field_counts = Counter()
    code_field_counts = Counter()
    code_samples = defaultdict(list)
    for row in all_rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            field_counts[str(key)] += 1
            if "code" in str(key).lower() and value not in (None, ""):
                code_field_counts[str(key)] += 1
                if len(code_samples[str(key)]) < 12:
                    code_samples[str(key)].append(repr(value))

    product_code_values = [
        str(row.get("productCode") or "").strip()
        for row in all_rows if isinstance(row, dict)
    ]
    product_code_nonempty = [x for x in product_code_values if x]
    product_code_equity_matches = [x for x in product_code_nonempty if EQUITY_CODE.fullmatch(x)]
    schema_audit = {
        "top_fields": field_counts.most_common(40),
        "code_fields": code_field_counts.most_common(20),
        "code_samples": {k: v for k, v in sorted(code_samples.items())},
        "product_code_nonempty_count": len(product_code_nonempty),
        "product_code_equity_match_count": len(product_code_equity_matches),
        "product_code_samples": product_code_nonempty[:30],
        "product_code_equity_samples": product_code_equity_matches[:30],
    }

    unique = {}
    for row in all_rows:
        if not isinstance(row, dict):
            continue
        normalized = canonical_row(row)
        key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique[key] = normalized

    stock_rows = [
        row for row in unique.values()
        if EQUITY_CODE.fullmatch(str(row.get("productCode") or "").strip())
    ]
    stock_rows.sort(key=lambda r: (
        compact(r.get("startStopDate")),
        str(r.get("productCode") or ""),
        compact(r.get("endStopDate")),
    ))

    recognized_starts = [compact(r.get("startStopDate")) for r in stock_rows]
    recognized_starts = [d for d in recognized_starts if len(d) == 8]
    invalid_interval = 0
    for row in stock_rows:
        start = compact(row.get("startStopDate"))
        end = compact(row.get("endStopDate"))
        if start and end and end < start:
            invalid_interval += 1

    all_years_complete = not failures and all(x.get("pagination_complete") for x in years)
    interval_inventory = "SUPPORTED" if all_years_complete and stock_rows and invalid_interval == 0 else "NOT VERIFIED"

    report = {
        "schema": "stock-sse-historical-suspension-inventory-v1",
        "endpoint": ENDPOINT,
        "query_range": {"first": "19901219", "last": LAST_DATE},
        "page_size": PAGE_SIZE,
        "year_reports": years,
        "failures": failures,
        "schema_audit": schema_audit,
        "counts": {
            "raw_rows": len(all_rows),
            "unique_rows": len(unique),
            "shanghai_a_share_interval_rows": len(stock_rows),
            "unique_stock_codes": len({str(r.get("productCode")) for r in stock_rows}),
            "invalid_interval_rows": invalid_interval,
        },
        "date_range": {
            "earliest_start": min(recognized_starts) if recognized_starts else None,
            "latest_start": max(recognized_starts) if recognized_starts else None,
        },
        "adjudication": {
            "pagination_complete_all_years": all_years_complete,
            "historical_sse_equity_suspension_interval_inventory": interval_inventory,
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "inventory": stock_rows,
    }
    Path("stock_sse_historical_suspension_inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "query_range": report["query_range"],
        "failures": failures,
        "schema_audit": report["schema_audit"],
        "counts": report["counts"],
        "date_range": report["date_range"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
