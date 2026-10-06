from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
HEADERS = {
    "Pragma": "no-cache",
    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
STATUS_VARIANTS = {
    "current_frozen": "2,4,5,7,8",
    "unfiltered": "",
    "wide_1_to_9": "1,2,3,4,5,6,7,8,9",
}


def _values(rows: list[dict], key: str, limit: int = 10) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _fetch(stock_type: str, company_status: str) -> dict:
    params = {
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "COMPANY_STATUS": company_status,
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.endPage": "1",
    }
    request = Request(f"{URL}?{urlencode(params)}", headers=HEADERS, method="GET")
    retrieved_at_unix = time.time()
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        http_status = int(getattr(response, "status", 0) or 0)
        content_type = str(response.headers.get("Content-Type") or "")
    payload_sha256 = hashlib.sha256(raw).hexdigest()
    obj = json.loads(raw.decode("utf-8-sig"))
    rows = obj.get("result")
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise RuntimeError("official SSE result is malformed")
    keys = sorted({str(key) for row in rows for key in row.keys()})
    nonempty_delist = [
        str(row.get("DELIST_DATE") or "").strip()
        for row in rows
        if str(row.get("DELIST_DATE") or "").strip() not in ("", "-")
    ]
    return {
        "http_status": http_status,
        "content_type": content_type,
        "retrieved_at_unix": retrieved_at_unix,
        "payload_sha256": payload_sha256,
        "row_count": len(rows),
        "all_keys": keys,
        "list_date_samples": _values(rows, "LIST_DATE"),
        "delist_date_samples": _values(rows, "DELIST_DATE"),
        "nonempty_delist_count": len(nonempty_delist),
        "nonempty_delist_samples": sorted(set(nonempty_delist))[:12],
        "state_code_samples": _values(rows, "STATE_CODE"),
        "state_code_stock_samples": _values(rows, "STATE_CODE_STOCK"),
        "product_status_samples": _values(rows, "PRODUCT_STATUS"),
        "company_status_filter": company_status,
        "stock_type": stock_type,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    probes: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for stock_type, board in (("1", "main_a"), ("8", "star")):
        for variant, status_filter in STATUS_VARIANTS.items():
            key = f"{board}:{variant}"
            try:
                probes[key] = _fetch(stock_type, status_filter)
            except Exception as exc:
                failures[key] = f"{type(exc).__name__}: {exc}"

    baseline_keys = ("main_a:current_frozen", "star:current_frozen")
    baseline_ok = all(key in probes and probes[key]["row_count"] > 0 for key in baseline_keys)
    date_schema_ok = all(
        "LIST_DATE" in probes[key]["all_keys"] and "DELIST_DATE" in probes[key]["all_keys"]
        for key in baseline_keys
        if key in probes
    ) if baseline_ok else False
    delisted_variants = {
        key: value["nonempty_delist_count"]
        for key, value in probes.items()
        if value.get("nonempty_delist_count", 0) > 0
    }
    historical_candidate = bool(date_schema_ok and delisted_variants)

    evidence = {
        "schema": "rmf-sse-historical-universe-schema-probe-v2",
        "status": "PASS" if baseline_ok else "FAIL",
        "scope": "official SSE schema/status-filter discovery only; not historical survivorship qualification",
        "source_provider": "sse_official_equity_universe",
        "source_url": URL,
        "probes": probes,
        "probe_failures": failures,
        "baseline_date_schema_present": date_schema_ok,
        "variants_with_nonempty_delist_dates": delisted_variants,
        "historical_reconstruction_schema_candidate": historical_candidate,
        "business_survivorship_gate": "NOT VERIFIED",
        "historical_pit_availability": "NOT VERIFIED",
        "boundary": (
            "PASS means live official SSE payloads and their listing/delisting schema were observed "
            "with payload SHA-256 and retrieval time. Even if delisted records are discoverable, "
            "historical membership must still be reconstructed, cross-checked, frozen by as-of date, "
            "and bound to the research window before the survivorship business gate can PASS."
        ),
    }
    args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0 if baseline_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
