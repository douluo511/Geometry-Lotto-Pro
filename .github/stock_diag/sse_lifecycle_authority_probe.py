from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UNIVERSE_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
DAILY_URL = "https://query.sse.com.cn/commonQuery.do"
UNIVERSE_SQL_ID = "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L"
DAILY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C"
HEADERS = {
    "Host": "query.sse.com.cn",
    "Pragma": "no-cache",
    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
CODE = re.compile(r"^6\d{5}$")
CROSSCHECK_DATES = ("2023-01-13", "2024-04-15", "2025-07-10", "2026-09-30")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_date(value: object, *, allow_missing: bool) -> date | None:
    raw = str(value or "").strip()
    if allow_missing and raw in {"", "-"}:
        return None
    compact = raw.replace("-", "")
    if not re.fullmatch(r"\d{8}", compact):
        raise ValueError(f"invalid SSE date: {raw!r}")
    return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))


def fetch_json(url: str, params: dict[str, str]) -> tuple[bytes, dict, float]:
    request = Request(f"{url}?{urlencode(params)}", headers=HEADERS, method="GET")
    retrieved = time.time()
    with urlopen(request, timeout=35) as response:
        raw = response.read()
        status = int(getattr(response, "status", 0) or 0)
        content_type = str(response.headers.get("Content-Type") or "")
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {url}")
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise RuntimeError("official SSE payload is not a JSON object")
    return raw, obj, retrieved


def fetch_board(output_dir: Path, stock_type: str, board: str) -> tuple[list[dict], dict]:
    params = {
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "sqlId": UNIVERSE_SQL_ID,
        "COMPANY_STATUS": "",
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.endPage": "1",
    }
    raw, obj, retrieved = fetch_json(UNIVERSE_URL, params)
    raw_path = output_dir / f"sse_universe_{board}.json"
    raw_path.write_bytes(raw)
    rows = obj.get("result")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"SSE {board} universe is empty")

    page_help = obj.get("pageHelp")
    if not isinstance(page_help, dict):
        raise RuntimeError(f"SSE {board} pageHelp missing")
    try:
        server_total = int(page_help.get("total"))
        page_count = int(page_help.get("pageCount"))
        page_no = int(page_help.get("pageNo"))
        begin_page = int(page_help.get("beginPage"))
        end_page = int(page_help.get("endPage"))
    except Exception as exc:
        raise RuntimeError(f"SSE {board} invalid pagination metadata") from exc
    page_data = page_help.get("data")
    if (
        server_total != len(rows)
        or page_count != 1
        or page_no != 1
        or begin_page != 1
        or end_page != 1
        or not isinstance(page_data, list)
        or page_data != rows
    ):
        raise RuntimeError(
            f"SSE {board} pagination denominator mismatch: "
            f"total={server_total} rows={len(rows)} pageCount={page_count} "
            f"pageNo={page_no} beginPage={begin_page} endPage={end_page}"
        )

    nums = []
    seen_codes = set()
    normalized: list[dict] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError(f"SSE {board} row {idx} is not object")
        code = str(row.get("A_STOCK_CODE") or "").strip()
        if not CODE.fullmatch(code):
            raise RuntimeError(f"SSE {board} invalid A_STOCK_CODE {code!r}")
        if code in seen_codes:
            raise RuntimeError(f"SSE {board} duplicate A_STOCK_CODE {code!r}")
        seen_codes.add(code)
        try:
            nums.append(int(str(row.get("NUM") or "").strip()))
        except Exception as exc:
            raise RuntimeError(f"SSE {board} invalid NUM at row {idx}") from exc
        listed = parse_date(row.get("LIST_DATE"), allow_missing=False)
        delisted = parse_date(row.get("DELIST_DATE"), allow_missing=True)
        if delisted is not None and delisted < listed:
            raise RuntimeError(f"SSE {code} delist before list")
        normalized.append({
            "market": "SSE",
            "board": board,
            "code": code,
            "listing_date": listed.isoformat(),
            "delisting_date": delisted.isoformat() if delisted else None,
        })

    if sorted(nums) != list(range(1, server_total + 1)):
        raise RuntimeError(f"SSE {board} NUM sequence is not exact 1..{server_total}")

    return normalized, {
        "url": UNIVERSE_URL,
        "sql_id": UNIVERSE_SQL_ID,
        "stock_type": stock_type,
        "company_status_filter": "",
        "raw_path": raw_path.as_posix(),
        "raw_sha256": sha256_bytes(raw),
        "retrieved_at_unix": retrieved,
        "row_count": len(normalized),
        "server_total": server_total,
        "page_count": page_count,
        "page_no": page_no,
        "begin_page": begin_page,
        "end_page": end_page,
        "pagehelp_result_identity": True,
        "num_sequence_complete": True,
        "unique_code_count": len(seen_codes),
        "pagination_complete": (
            server_total == len(normalized)
            and page_count == 1
            and page_no == 1
            and begin_page == 1
            and end_page == 1
            and len(seen_codes) == server_total
        ),
    }


def eligible(item: dict, asof: date) -> bool:
    listed = date.fromisoformat(item["listing_date"])
    delisted = date.fromisoformat(item["delisting_date"]) if item["delisting_date"] else None
    return listed <= asof and (delisted is None or asof < delisted)


def official_daily_count(output_dir: Path, day: str) -> dict:
    params = {
        "sqlId": DAILY_SQL_ID,
        "PRODUCT_CODE": "01,03",
        "type": "inParams",
        "SEARCH_DATE": day,
    }
    raw, obj, retrieved = fetch_json(DAILY_URL, params)
    raw_path = output_dir / f"sse_daily_{day}.json"
    raw_path.write_bytes(raw)
    rows = obj.get("result")
    receipt = {
        "date": day,
        "raw_path": raw_path.as_posix(),
        "raw_sha256": sha256_bytes(raw),
        "retrieved_at_unix": retrieved,
    }
    if not isinstance(rows, list) or not rows:
        return {**receipt, "status": "NOT VERIFIED", "reason": "no official row list"}

    date8 = day.replace("-", "")
    def select(product_code: str) -> list[dict]:
        return [
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("PRODUCT_CODE") or "").strip() == product_code
            and str(row.get("TRADE_DATE") or "").strip() == date8
        ]

    main = select("01")
    star = select("03")
    if len(main) != 1 or len(star) != 1:
        return {
            **receipt,
            "status": "NOT VERIFIED",
            "reason": "unique PRODUCT_CODE 01 + 03 rows unavailable",
        }

    def integer(value: object) -> int:
        text = str(value or "").strip().replace(",", "")
        if not text.isdigit():
            raise ValueError(f"invalid LIST_NUM {text!r}")
        return int(text)

    main_n = integer(main[0].get("LIST_NUM"))
    star_n = integer(star[0].get("LIST_NUM"))
    return {
        **receipt,
        "status": "PASS",
        "main_count": main_n,
        "star_count": star_n,
        "main_plus_star": main_n + star_n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    main_rows, main_meta = fetch_board(args.raw_dir, "1", "main_a")
    star_rows, star_meta = fetch_board(args.raw_dir, "8", "star")
    combined = main_rows + star_rows

    by_code: dict[str, dict] = {}
    for row in combined:
        previous = by_code.get(row["code"])
        if previous is not None and previous != row:
            raise RuntimeError(f"conflicting duplicate SSE code {row['code']}")
        by_code[row["code"]] = row

    lifecycle = [by_code[code] for code in sorted(by_code)]
    lifecycle_payload = "".join(
        f"{row['code']}|{row['listing_date']}|{row['delisting_date'] or ''}\\n"
        for row in lifecycle
    ).encode("utf-8")
    lifecycle_path = args.raw_dir / "sse_lifecycle_projection.txt"
    lifecycle_path.write_bytes(lifecycle_payload)

    crosschecks = []
    mismatches = []
    comparable = 0
    for day_text in CROSSCHECK_DATES:
        day = date.fromisoformat(day_text)
        reconstructed = sum(1 for item in lifecycle if eligible(item, day))
        official = official_daily_count(args.raw_dir, day_text)
        match = None
        if official.get("status") == "PASS":
            comparable += 1
            match = official["main_plus_star"] == reconstructed
            if not match:
                mismatches.append({
                    "date": day_text,
                    "reconstructed": reconstructed,
                    "official": official["main_plus_star"],
                })
        crosschecks.append({
            "date": day_text,
            "reconstructed": reconstructed,
            "official": official,
            "match": match,
        })

    source_identity_pass = (
        main_meta["row_count"] > 0
        and star_meta["row_count"] > 0
        and main_meta.get("pagination_complete") is True
        and star_meta.get("pagination_complete") is True
        and main_meta["server_total"] == main_meta["row_count"]
        and star_meta["server_total"] == star_meta["row_count"]
        and len(lifecycle) == len(by_code)
        and len(lifecycle) == main_meta["server_total"] + star_meta["server_total"]
    )
    reconstruction_supported = comparable >= 3 and not mismatches

    evidence = {
        "schema": "stock-sse-native-lifecycle-authority-diagnostic-v1",
        "status": "PASS" if source_identity_pass and reconstruction_supported else "NOT VERIFIED",
        "product_bytes_changed": False,
        "scope": "SSE native lifecycle authority diagnostic only; not full three-market PIT completeness",
        "authority": {
            "provider": "Shanghai Stock Exchange",
            "universe_url": UNIVERSE_URL,
            "universe_sql_id": UNIVERSE_SQL_ID,
            "daily_count_url": DAILY_URL,
            "daily_count_sql_id": DAILY_SQL_ID,
            "native_raw_bytes_preserved": True,
            "main_a": main_meta,
            "star": star_meta,
        },
        "lifecycle": {
            "normalized_security_count": len(lifecycle),
            "securities_with_delist_date": sum(1 for x in lifecycle if x["delisting_date"]),
            "projection_path": lifecycle_path.as_posix(),
            "projection_sha256": sha256_bytes(lifecycle_payload),
            "membership_rule": "LIST_DATE <= asof < DELIST_DATE; missing/'-' DELIST_DATE means no recorded delisting",
        },
        "crosscheck": {
            "dates": list(CROSSCHECK_DATES),
            "comparable_date_count": comparable,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "rows": crosschecks,
            "historical_membership_reconstruction": "SUPPORTED" if reconstruction_supported else "NOT VERIFIED",
        },
        "adjudication": {
            "sse_source_identity": "PASS" if source_identity_pass else "NOT VERIFIED",
            "sse_native_raw_binding": "PASS" if source_identity_pass else "NOT VERIFIED",
            "sse_lifecycle_projection": "SUPPORTED" if reconstruction_supported else "NOT VERIFIED",
            "sse_historical_pit_availability": "NOT VERIFIED",
            "szse_native_lifecycle_authority": "NOT VERIFIED",
            "bse_native_lifecycle_authority": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "PASS proves a current first-party SSE native universe payload was fetched and preserved, its server-declared pagination denominator exactly matched the complete returned rows with continuous NUM identities, "
            "its LIST_DATE/DELIST_DATE rows were deterministically normalized, and the reconstruction "
            "agreed with independent official SSE daily listed-count aggregates on at least three "
            "comparable historical dates with zero mismatches. It does not prove historical PIT "
            "availability of those lifecycle fields, does not establish SZSE/BSE authority, and "
            "cannot promote full historical ST/PIT or Advanced Business."
        ),
    }
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": evidence["schema"],
        "status": evidence["status"],
        "normalized_security_count": evidence["lifecycle"]["normalized_security_count"],
        "securities_with_delist_date": evidence["lifecycle"]["securities_with_delist_date"],
        "comparable_date_count": comparable,
        "mismatch_count": len(mismatches),
        "projection_sha256": evidence["lifecycle"]["projection_sha256"],
        "adjudication": evidence["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
