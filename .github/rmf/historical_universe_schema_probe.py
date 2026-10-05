from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
PARAMS = {
    "STOCK_TYPE": "1",
    "REG_PROVINCE": "",
    "CSRC_CODE": "",
    "STOCK_CODE": "",
    "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
    "COMPANY_STATUS": "2,4,5,7,8",
    "type": "inParams",
    "isPagination": "true",
    "pageHelp.cacheSize": "1",
    "pageHelp.beginPage": "1",
    "pageHelp.pageSize": "10000",
    "pageHelp.pageNo": "1",
    "pageHelp.endPage": "1",
}
HEADERS = {
    "Pragma": "no-cache",
    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def _values(rows: list[dict], key: str, limit: int = 8) -> list[str]:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    query = urlencode(PARAMS)
    request = Request(f"{URL}?{query}", headers=HEADERS, method="GET")
    retrieved_at_unix = time.time()
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        http_status = int(getattr(response, "status", 0) or 0)
        content_type = str(response.headers.get("Content-Type") or "")

    payload_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        evidence = {
            "schema": "rmf-sse-historical-universe-schema-probe-v1",
            "status": "FAIL",
            "http_status": http_status,
            "content_type": content_type,
            "payload_sha256": payload_sha256,
            "retrieved_at_unix": retrieved_at_unix,
            "error": f"{type(exc).__name__}: {exc}",
            "business_survivorship_gate": "NOT VERIFIED",
        }
        args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 2

    rows = obj.get("result")
    if not isinstance(rows, list) or not rows or not all(isinstance(x, dict) for x in rows):
        raise RuntimeError("official SSE result is empty or malformed")

    keys = sorted({str(key) for row in rows for key in row.keys()})
    upper = {key: key.upper() for key in keys}
    date_like = [key for key in keys if "DATE" in upper[key]]
    listing_like = [
        key for key in keys
        if any(token in upper[key] for token in ("LIST_DATE", "LISTING_DATE", "LISTED_DATE", "LISTING"))
    ]
    delisting_like = [
        key for key in keys
        if any(token in upper[key] for token in ("DELIST", "TERMINAT", "WITHDRAW", "END_DATE"))
    ]
    status_like = [key for key in keys if any(token in upper[key] for token in ("STATUS", "STATE"))]
    market_like = [key for key in keys if any(token in upper[key] for token in ("MARKET", "BOARD", "STOCK_TYPE"))]

    candidate_keys = sorted(set(date_like + listing_like + delisting_like + status_like + market_like))
    samples = {key: _values(rows, key) for key in candidate_keys}
    reconstruction_candidate = bool(listing_like and (delisting_like or status_like))

    evidence = {
        "schema": "rmf-sse-historical-universe-schema-probe-v1",
        "status": "PASS",
        "scope": "schema discovery only; not a historical survivorship qualification",
        "source_provider": "sse_official_current_shanghai_equity_universe",
        "source_url": URL,
        "source_filter": "STOCK_TYPE=1;COMPANY_STATUS=2,4,5,7,8",
        "http_status": http_status,
        "content_type": content_type,
        "retrieved_at_unix": retrieved_at_unix,
        "payload_sha256": payload_sha256,
        "row_count": len(rows),
        "all_keys": keys,
        "date_like_fields": date_like,
        "listing_like_fields": listing_like,
        "delisting_like_fields": delisting_like,
        "status_like_fields": status_like,
        "market_like_fields": market_like,
        "candidate_field_samples": samples,
        "historical_reconstruction_schema_candidate": reconstruction_candidate,
        "business_survivorship_gate": "NOT VERIFIED",
        "boundary": (
            "PASS means the official live SSE schema was observed and payload-bound. "
            "It does not prove historical point-in-time membership, historical source availability, "
            "or survivorship-safe business qualification."
        ),
    }
    args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
