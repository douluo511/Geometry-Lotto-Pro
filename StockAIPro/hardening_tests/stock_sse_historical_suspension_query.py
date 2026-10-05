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
ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def get(session, url, *, params=None, attempts=3):
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
        "script_http_status": script.status_code,
        "script_sha256": hashlib.sha256(script.content).hexdigest(),
        "script_fetch_attempt": script_meta["attempt"],
        "declares_query_host": 'sseQueryURL = "//query.sse.com.cn/"' in page_text,
        "declares_endpoint": "suspensionUrl: sseQueryURL + 'commonSoaQuery.do'" in script_text,
        "declares_sql_id": '"sqlId":\'GW_PL_JYTS_TFPXX\'' in script_text or "sqlId':\'GW_PL_JYTS_TFPXX\'" in script_text,
        "declares_start_date": "startStopDate" in script_text,
        "declares_end_date": "endStopDate" in script_text,
    }

    queries = []
    base = {
        "isPagination": "true",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "pageHelp.pageSize": "200",
        "pageHelp.pageNo": "1",
        "productCode": "",
        "keyWords": "",
    }
    for year in (2019, 2024):
        compact = dict(base, startStopDate=f"{year}0101", endStopDate=f"{year}1231")
        dashed = dict(base, startStopDate=f"{year}-01-01", endStopDate=f"{year}-12-31")
        queries.append(call_query(s, f"{year}-compact", compact))
        queries.append(call_query(s, f"{year}-dashed", dashed))

    recent = dict(base, startStopDate="20260901", endStopDate="20260930")
    queries.append(call_query(s, "2026-09-compact", recent))

    trade_day = call_query(s, "trade-day-20260930", {
        "sqlId": "GW_PL_JYTS_TFPXX_TRADEDAY",
        "bizDate": "20260930",
    })
    queries.append(trade_day)

    historical_hits = []
    for q in queries:
        payload = q.get("payload")
        if not isinstance(payload, dict):
            continue
        rows = payload.get("result")
        if not isinstance(rows, list) or not rows:
            continue
        ev = date_evidence(rows, q["params"].get("startStopDate"), q["params"].get("endStopDate"))
        if q["label"].startswith(("2019", "2024")) and ev["in_window_count"] > 0:
            historical_hits.append({
                "label": q["label"],
                "rows": len(rows),
                "date_evidence": ev,
                "sample": [bounded_row(x) for x in rows[:3]],
            })

    endpoint_reachable_and_parseable = any(
        isinstance(q.get("payload"), dict)
        for q in queries
    )
    historical_query_supported = bool(historical_hits)

    report = {
        "schema": "stock-sse-historical-suspension-query-v1",
        "run_date_utc": date.today().isoformat(),
        "official_sources": {
            "page": PAGE,
            "script": SCRIPT,
            "endpoint": ENDPOINT,
        },
        "source_contract": source_contract,
        "queries": [
            {
                "label": q["label"],
                "params": q["params"],
                "attempts": q["attempts"],
                "parsed_summary": summarize_payload(q["payload"]) if isinstance(q.get("payload"), dict) else None,
            }
            for q in queries
        ],
        "historical_hits": historical_hits,
        "adjudication": {
            "official_endpoint_reachable_and_parseable": endpoint_reachable_and_parseable,
            "historical_sse_suspension_query_supported": historical_query_supported,
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
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
        "source_contract": source_contract,
        "official_endpoint_reachable_and_parseable": endpoint_reachable_and_parseable,
        "historical_sse_suspension_query_supported": historical_query_supported,
        "historical_hits": historical_hits,
        "historical_daily_suspension_state": "NOT VERIFIED",
        "shanghai_historical_st_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
