from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

import requests

INTERVAL_ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
DAILY_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonQuery.do"
REFERER = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
WINDOW_START = "20180101"
WINDOW_END = "20260930"
SAMPLE_DATES = ("20220104", "20240104", "20260924", "20260930")
A_SHARE = re.compile(r"^(?:600|601|603|605|688|689)\d{3}$")


def request(session: requests.Session, method: str, url: str, *, params=None, data=None, attempts=4):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            kwargs = {
                "headers": {
                    "User-Agent": UA,
                    "Referer": REFERER,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
                "timeout": (8, 30),
                "allow_redirects": True,
            }
            if method == "GET":
                kwargs["params"] = params
                r = session.get(url, **kwargs)
            else:
                kwargs["data"] = data
                r = session.post(url, **kwargs)
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def parse_payload(text: str):
    s = text.strip()
    try:
        obj = json.loads(s)
        return obj, "json"
    except Exception:
        pass
    m = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", s, re.S)
    if m:
        return json.loads(m.group(1)), "jsonp"
    m = re.match(r"^\(\s*(\{.*\})\s*\)\s*;?\s*$", s, re.S)
    if m:
        return json.loads(m.group(1)), "parenthesized_json"
    raise ValueError("payload is not JSON/JSONP/parenthesized JSON")


def digits8(value):
    d = "".join(ch for ch in str(value or "") if ch.isdigit())
    return d[:8] if len(d) >= 8 else None


def code_of(row: dict):
    for k in ("securityCode", "productCode", "SEC_CODE", "secCode", "code", "PRODUCT_CODE"):
        v = str(row.get(k) or "").strip()
        if v:
            return v
    return ""


def interval_of(row: dict):
    code = code_of(row)
    if not A_SHARE.fullmatch(code):
        return None
    start = None
    end = None
    for k in ("startStopDate", "STOP_DATE", "stopDate", "startDate"):
        if digits8(row.get(k)):
            start = digits8(row.get(k))
            break
    for k in ("endStopDate", "endDate", "resumeDate"):
        if digits8(row.get(k)):
            end = digits8(row.get(k))
            break
    if not start:
        return None
    return {"code": code, "start": start, "end": end}


def page_numbers(payload: dict, page_size: int, row_count: int):
    ph = payload.get("pageHelp") if isinstance(payload, dict) else None
    if isinstance(ph, dict):
        for key in ("pageCount", "pagecount"):
            try:
                n = int(ph.get(key))
                if n > 0:
                    return n
            except Exception:
                pass
        for key in ("total", "totalCount", "totalcount"):
            try:
                total = int(ph.get(key))
                if total >= 0:
                    return max(1, math.ceil(total / page_size))
            except Exception:
                pass
    return 1 if row_count < page_size else None


def fetch_interval_corpus(session: requests.Session):
    page_size = 200
    all_rows = []
    page_hashes = []
    expected_pages = None
    page_no = 1
    while True:
        params = {
            "isPagination": "true",
            "sqlId": "GW_PL_JYTS_TFPXX",
            "pageHelp.pageSize": str(page_size),
            "pageHelp.pageNo": str(page_no),
            "productCode": "",
            "keyWords": "",
            "startStopDate": WINDOW_START,
            "endStopDate": WINDOW_END,
            "jsonCallBack": "jsonpCallback",
        }
        r, meta = request(session, "GET", INTERVAL_ENDPOINT, params=params)
        obj, kind = parse_payload(r.content.decode(r.encoding or "utf-8", errors="replace"))
        rows = obj.get("result") if isinstance(obj, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"interval page {page_no}: result is not a list")
        all_rows.extend(rows)
        page_hashes.append({
            "page": page_no,
            "rows": len(rows),
            "sha256": hashlib.sha256(r.content).hexdigest(),
            "parsed_as": kind,
            "attempt": meta["attempt"],
        })
        if expected_pages is None:
            expected_pages = page_numbers(obj, page_size, len(rows))
        if expected_pages is not None and page_no >= expected_pages:
            break
        if len(rows) < page_size:
            break
        page_no += 1
        if page_no > 100:
            raise RuntimeError("interval pagination exceeded 100 pages")
    intervals = [x for x in (interval_of(r) for r in all_rows) if x]
    canonical = sorted({(x["code"], x["start"], x["end"] or "") for x in intervals})
    corpus_bytes = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        "raw_rows": len(all_rows),
        "a_share_intervals": len(canonical),
        "page_count": len(page_hashes),
        "pages": page_hashes,
        "canonical_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "intervals": canonical,
    }


def fetch_daily_snapshot(session: requests.Session, d: str):
    data = {
        "isPagination": "true",
        "sqlId": "COMMON_SSE_XXPL_JYTS_TFPXX_L",
        "SEARCH_DATE": d,
        "pageHelp.pageSize": "500",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "jsonCallBack": "jsonpCallback",
    }
    r, meta = request(session, "POST", DAILY_ENDPOINT, data=data)
    obj, kind = parse_payload(r.content.decode(r.encoding or "utf-8", errors="replace"))
    rows = obj.get("result") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"daily snapshot {d}: result is not a list")
    codes = sorted({
        code_of(row)
        for row in rows
        if isinstance(row, dict) and A_SHARE.fullmatch(code_of(row))
    })
    return {
        "date": d,
        "raw_rows": len(rows),
        "a_share_codes": codes,
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "parsed_as": kind,
        "attempt": meta["attempt"],
    }


def expected_codes(intervals, d: str):
    out = set()
    for code, start, end in intervals:
        if start <= d and (not end or d <= end):
            out.add(code)
    return sorted(out)


def main():
    s = requests.Session()
    corpus = fetch_interval_corpus(s)
    comparisons = []
    for d in SAMPLE_DATES:
        snap = fetch_daily_snapshot(s, d)
        expected = expected_codes(corpus["intervals"], d)
        actual = snap["a_share_codes"]
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        comparisons.append({
            "date": d,
            "expected_count": len(expected),
            "actual_count": len(actual),
            "exact_match": expected == actual,
            "missing": missing,
            "unexpected": unexpected,
            "snapshot": {k: v for k, v in snap.items() if k != "a_share_codes"},
            "actual_codes": actual,
            "expected_codes": expected,
        })
    semantic_supported = (
        corpus["raw_rows"] > 0
        and corpus["a_share_intervals"] > 0
        and all(x["exact_match"] for x in comparisons)
        and sum(x["actual_count"] for x in comparisons) > 0
    )
    report = {
        "schema": "stock-sse-daily-snapshot-interval-consistency-v1",
        "authoritative_product_head": "43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
        "frozen_research_window": {"start": WINDOW_START, "end": WINDOW_END},
        "official_contracts": {
            "interval_endpoint": INTERVAL_ENDPOINT,
            "interval_sql_id": "GW_PL_JYTS_TFPXX",
            "daily_endpoint": DAILY_ENDPOINT,
            "daily_sql_id": "COMMON_SSE_XXPL_JYTS_TFPXX_L",
        },
        "interval_corpus": {k: v for k, v in corpus.items() if k != "intervals"},
        "comparisons": comparisons,
        "adjudication": {
            "daily_snapshot_endpoint_reproducible": "PASS",
            "interval_to_daily_state_semantics": "SUPPORTED" if semantic_supported else "NOT VERIFIED",
            "shanghai_historical_daily_suspension_state": "SUPPORTED" if semantic_supported else "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "beijing_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_daily_snapshot_interval_consistency.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "interval_raw_rows": corpus["raw_rows"],
        "a_share_intervals": corpus["a_share_intervals"],
        "interval_canonical_sha256": corpus["canonical_sha256"],
        "comparisons": [
            {
                "date": x["date"],
                "expected_count": x["expected_count"],
                "actual_count": x["actual_count"],
                "exact_match": x["exact_match"],
                "missing_count": len(x["missing"]),
                "unexpected_count": len(x["unexpected"]),
            }
            for x in comparisons
        ],
        "interval_to_daily_state_semantics": report["adjudication"]["interval_to_daily_state_semantics"],
        "shanghai_historical_daily_suspension_state": report["adjudication"]["shanghai_historical_daily_suspension_state"],
        "full_historical_st_pit": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    return 0 if semantic_supported else 2


if __name__ == "__main__":
    raise SystemExit(main())
