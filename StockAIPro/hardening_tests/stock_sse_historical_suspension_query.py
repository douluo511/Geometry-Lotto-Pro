from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SCRIPT = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
PAGE_FALLBACK = "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SCRIPT_FALLBACK = "https://big5.sse.com.cn/site/cht/www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
SOURCE_FALLBACKS = {PAGE: PAGE_FALLBACK, SCRIPT: SCRIPT_FALLBACK}
ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def get(session, url, *, params=None, attempts=3, allow_fallback=True):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Referer": PAGE,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                fallback = SOURCE_FALLBACKS.get(url) if allow_fallback else None
                if fallback:
                    r, meta = get(session, fallback, params=params, attempts=attempts, allow_fallback=False)
                    meta = dict(meta)
                    meta["fallback_from"] = url
                    meta["primary_errors"] = errors
                    return r, meta
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def parse_json_or_jsonp(text):
    stripped = text.strip()
    try:
        return json.loads(stripped), "json"
    except Exception:
        pass
    m = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", stripped, flags=re.S)
    if not m:
        raise ValueError("response is neither JSON nor simple JSONP")
    return json.loads(m.group(1)), "jsonp"


def digits8(value):
    if value is None:
        return None
    d = "".join(ch for ch in str(value) if ch.isdigit())
    return d[:8] if len(d) >= 8 else None


def bounded_row(row):
    if not isinstance(row, dict):
        return row
    keep = {}
    wanted = (
        "securityCode", "securityName", "productCode", "productName",
        "startStopDate", "endStopDate", "startStopTime", "endStopTime",
        "startStopReason", "endStopReason", "stopReason", "controlType",
        "SEC_CODE", "SEC_NAME_CN", "STOP_DATE", "STOP_TIME", "STOP_REASON",
    )
    for key in wanted:
        if key in row:
            keep[key] = row[key]
    if not keep:
        for key in sorted(row)[:16]:
            keep[key] = row[key]
    return keep


def summarize_payload(payload):
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}
    result = payload.get("result")
    page_help = payload.get("pageHelp")
    out = {
        "top_keys": sorted(payload)[:30],
        "result_count": len(result) if isinstance(result, list) else None,
        "sample": [bounded_row(x) for x in result[:3]] if isinstance(result, list) else [],
    }
    if isinstance(page_help, dict):
        out["page_help"] = {
            k: page_help.get(k)
            for k in ("pageNo", "pageSize", "pageCount", "total")
            if k in page_help
        }
    return out


def date_evidence(rows, start, end):
    start_d = digits8(start)
    end_d = digits8(end)
    recognized = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in (
            "startStopDate", "endStopDate", "STOP_DATE", "stopDate",
            "startDate", "endDate",
        ):
            if key in row:
                d = digits8(row.get(key))
                if d:
                    recognized.append({"key": key, "date": d})
    in_window = [
        item for item in recognized
        if start_d and end_d and start_d <= item["date"] <= end_d
    ]
    return {
        "recognized_date_values": recognized[:30],
        "recognized_count": len(recognized),
        "in_window_count": len(in_window),
    }


def call_query(session, label, params):
    variants = [
        ("jsonCallBack", {"jsonCallBack": "jsonpCallback"}),
        ("callback", {"callback": "jsonpCallback"}),
        ("plain", {}),
    ]
    attempts = []
    for variant, extra in variants:
        merged = dict(params)
        merged.update(extra)
        try:
            r, meta = get(session, ENDPOINT, params=merged, attempts=2)
            raw = r.content
            text = raw.decode(r.encoding or "utf-8", errors="replace")
            item = {
                "variant": variant,
                "http_status": r.status_code,
                "attempt": meta["attempt"],
                "content_type": r.headers.get("Content-Type"),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "url": r.url,
                "prefix": " ".join(text[:500].split()),
            }
            try:
                payload, parsed_as = parse_json_or_jsonp(text)
                item["parsed_as"] = parsed_as
                item["summary"] = summarize_payload(payload)
                result = payload.get("result") if isinstance(payload, dict) else None
                item["date_evidence"] = date_evidence(
                    result,
                    params.get("startStopDate"),
                    params.get("endStopDate"),
                )
                attempts.append(item)
                if isinstance(result, list):
                    return {"label": label, "params": params, "attempts": attempts, "payload": payload}
            except Exception as exc:
                item["parse_error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(item)
        except Exception as exc:
            attempts.append({"variant": variant, "error": f"{type(exc).__name__}: {exc}"})
    return {"label": label, "params": params, "attempts": attempts, "payload": None}


def _row_identity(row):
    if not isinstance(row, dict):
        return None
    keys = (
        "securityCode", "securityName", "productCode", "productName",
        "startStopDate", "endStopDate", "startStopTime", "endStopTime",
        "startStopReason", "endStopReason", "stopReason", "controlType",
        "SEC_CODE", "SEC_NAME_CN", "STOP_DATE", "STOP_TIME", "STOP_REASON",
    )
    obj = {k: row.get(k) for k in keys if k in row}
    if not obj:
        obj = {k: row.get(k) for k in sorted(row)[:24]}
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _interval_from_row(row):
    if not isinstance(row, dict):
        return None
    code = (
        row.get("securityCode") or row.get("productCode") or
        row.get("SEC_CODE") or row.get("secCode") or row.get("code")
    )
    name = (
        row.get("securityName") or row.get("productName") or
        row.get("SEC_NAME_CN") or row.get("secName") or row.get("name")
    )
    start = None
    end = None
    for k in ("startStopDate", "STOP_DATE", "stopDate", "startDate"):
        if k in row and digits8(row.get(k)):
            start = digits8(row.get(k))
            break
    for k in ("endStopDate", "endDate", "resumeDate"):
        if k in row and digits8(row.get(k)):
            end = digits8(row.get(k))
            break
    if start is None:
        return None
    return {
        "code": str(code or ""),
        "name": str(name or ""),
        "start": start,
        "end": end,
        "control_type": row.get("controlType"),
        "reason": row.get("startStopReason") or row.get("stopReason") or row.get("STOP_REASON"),
        "row_sha256": _row_identity(row),
    }


def fetch_window_all_pages(session, year, start, end, page_size=200, max_pages=200):
    base = {
        "isPagination": "true",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "pageHelp.pageSize": str(page_size),
        "productCode": "",
        "keyWords": "",
        "startStopDate": start,
        "endStopDate": end,
    }
    pages = []
    all_rows = []
    expected_page_count = None
    expected_total = None
    for page_no in range(1, max_pages + 1):
        params = dict(base)
        params["pageHelp.pageNo"] = str(page_no)
        q = call_query(session, f"{year}-page-{page_no}", params)
        payload = q.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError(f"{year} page {page_no}: unparseable payload")
        rows = payload.get("result")
        if not isinstance(rows, list):
            raise RuntimeError(f"{year} page {page_no}: result is not a list")
        ph = payload.get("pageHelp")
        page_count = None
        total = None
        if isinstance(ph, dict):
            for k in ("pageCount", "pagecount"):
                if ph.get(k) not in (None, ""):
                    try:
                        page_count = int(ph.get(k))
                    except Exception:
                        pass
            for k in ("total", "totalCount", "totalcount"):
                if ph.get(k) not in (None, ""):
                    try:
                        total = int(ph.get(k))
                    except Exception:
                        pass
        if page_count is not None:
            if expected_page_count is None:
                expected_page_count = page_count
            elif expected_page_count != page_count:
                raise RuntimeError(f"{year}: pageCount drift {expected_page_count} -> {page_count}")
        if total is not None:
            if expected_total is None:
                expected_total = total
            elif expected_total != total:
                raise RuntimeError(f"{year}: total drift {expected_total} -> {total}")
        pages.append({
            "page_no": page_no,
            "row_count": len(rows),
            "page_count": page_count,
            "total": total,
            "attempts": q.get("attempts", []),
        })
        all_rows.extend(rows)

        if expected_page_count is not None and page_no >= expected_page_count:
            break
        if len(rows) < page_size:
            break
    else:
        raise RuntimeError(f"{year}: exceeded max_pages={max_pages}")

    identities = [_row_identity(r) for r in all_rows]
    nonnull_ids = [x for x in identities if x]
    unique_ids = set(nonnull_ids)
    if len(unique_ids) != len(nonnull_ids):
        duplicate_count = len(nonnull_ids) - len(unique_ids)
    else:
        duplicate_count = 0

    intervals = [_interval_from_row(r) for r in all_rows]
    parsed_intervals = [x for x in intervals if x]
    recognized = sum(1 for r in all_rows if _interval_from_row(r) is not None)

    if expected_total is not None and len(all_rows) < expected_total:
        raise RuntimeError(f"{year}: pagination incomplete rows={len(all_rows)} total={expected_total}")
    if all_rows and recognized / len(all_rows) < 0.95:
        raise RuntimeError(f"{year}: interval parse ratio too low {recognized}/{len(all_rows)}")

    return {
        "year": year,
        "start": start,
        "end": end,
        "pages": pages,
        "expected_page_count": expected_page_count,
        "expected_total": expected_total,
        "raw_row_count": len(all_rows),
        "unique_row_count": len(unique_ids),
        "duplicate_row_count": duplicate_count,
        "interval_parse_count": len(parsed_intervals),
        "interval_parse_ratio": (len(parsed_intervals) / len(all_rows)) if all_rows else 1.0,
        "intervals": parsed_intervals,
    }


def main():
    s = requests.Session()
    page, page_meta = get(s, PAGE)
    script, script_meta = get(s, SCRIPT)
    page_text = page.content.decode(page.encoding or "utf-8", errors="replace")
    script_text = script.content.decode(script.encoding or "utf-8", errors="replace")

    source_contract = {
        "page_http_status": page.status_code,
        "page_sha256": hashlib.sha256(page.content).hexdigest(),
        "page_fetch_attempt": page_meta["attempt"],
        "page_resolved_url": page.url,
        "page_fallback_from": page_meta.get("fallback_from"),
        "script_http_status": script.status_code,
        "script_sha256": hashlib.sha256(script.content).hexdigest(),
        "script_fetch_attempt": script_meta["attempt"],
        "script_resolved_url": script.url,
        "script_fallback_from": script_meta.get("fallback_from"),
        "declares_query_host": 'sseQueryURL = "//query.sse.com.cn/"' in page_text,
        "declares_endpoint": "suspensionUrl: sseQueryURL + 'commonSoaQuery.do'" in script_text,
        "declares_sql_id": '"sqlId":\'GW_PL_JYTS_TFPXX\'' in script_text or "sqlId':\'GW_PL_JYTS_TFPXX\'" in script_text,
        "declares_start_date": "startStopDate" in script_text,
        "declares_end_date": "endStopDate" in script_text,
    }
    if not all(source_contract[k] for k in (
        "declares_query_host", "declares_endpoint", "declares_sql_id",
        "declares_start_date", "declares_end_date",
    )):
        raise RuntimeError("first-party source contract is incomplete")

    windows = []
    for year in range(2018, 2027):
        start = f"{year}0101"
        end = f"{year}1231"
        if year == 2026:
            end = "20260930"
        windows.append(fetch_window_all_pages(s, year, start, end))

    all_intervals = []
    for w in windows:
        all_intervals.extend(w["intervals"])

    ids = [x["row_sha256"] for x in all_intervals if x.get("row_sha256")]
    unique = {}
    for row in all_intervals:
        rid = row.get("row_sha256")
        if rid:
            unique[rid] = row
    canonical_intervals = sorted(
        unique.values(),
        key=lambda x: (x.get("start") or "", x.get("code") or "", x.get("end") or "", x.get("row_sha256") or ""),
    )
    canonical_bytes = json.dumps(
        canonical_intervals, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    canonical_sha = hashlib.sha256(canonical_bytes).hexdigest()

    total_rows = sum(w["raw_row_count"] for w in windows)
    total_parsed = sum(w["interval_parse_count"] for w in windows)
    all_years_complete = all(
        (w["expected_total"] is None or w["raw_row_count"] >= w["expected_total"])
        and w["interval_parse_ratio"] >= 0.95
        for w in windows
    )
    full_window_supported = (
        source_contract["page_http_status"] == 200
        and source_contract["script_http_status"] == 200
        and all_years_complete
        and total_rows > 0
        and len(canonical_intervals) > 0
    )

    report = {
        "schema": "stock-sse-historical-suspension-reconstruction-v3",
        "run_date_utc": date.today().isoformat(),
        "frozen_research_window": {"start": "20180101", "end": "20260930"},
        "official_sources": {"page": PAGE, "script": SCRIPT, "endpoint": ENDPOINT},
        "source_contract": source_contract,
        "windows": windows,
        "summary": {
            "raw_row_count": total_rows,
            "parsed_interval_count": total_parsed,
            "canonical_interval_count": len(canonical_intervals),
            "canonical_intervals_sha256": canonical_sha,
            "all_years_pagination_complete": all_years_complete,
        },
        "adjudication": {
            "official_endpoint_reachable_and_parseable": True,
            "historical_sse_suspension_query_supported": True,
            "shanghai_historical_suspension_intervals_2018_to_20260930": (
                "SUPPORTED" if full_window_supported else "NOT VERIFIED"
            ),
            "historical_daily_suspension_state": "NOT VERIFIED",
            "historical_daily_suspension_state_reason": (
                "official interval corpus is complete, but the diagnostic does not expand intervals "
                "onto an independently verified SSE trading calendar and does not prove whether "
                "endStopDate is the final suspended date or the resumption date"
            ),
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "beijing_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_historical_suspension_query.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "summary": report["summary"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if full_window_supported else 2


if __name__ == "__main__":
    raise SystemExit(main())
