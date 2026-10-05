from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
SUSPENSION_PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SUSPENSION_SCRIPT = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
CALENDAR_PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/calendar/index.shtml"
CLOSED_LIST = "https://www.sse.com.cn/disclosure/dealinstruc/closed/list/"
ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
DAILY_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonQuery.do"

def fetch(session, url, *, params=None, attempts=3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Referer": SUSPENSION_PAGE,
                    "Accept": "text/html,application/json,text/javascript,*/*;q=0.01",
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

def post_fetch(session, url, *, data=None, attempts=3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.post(
                url,
                data=data,
                headers={
                    "User-Agent": UA,
                    "Referer": SUSPENSION_PAGE,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def decode(resp) -> str:
    return resp.content.decode(resp.encoding or "utf-8", errors="replace")

def snippets(text: str, needle: str, radius: int = 420, limit: int = 12):
    out = []
    lower = text.lower()
    n = needle.lower()
    start = 0
    while len(out) < limit:
        i = lower.find(n, start)
        if i < 0:
            break
        lo = max(0, i - radius)
        hi = min(len(text), i + len(needle) + radius)
        frag = re.sub(r"\s+", " ", text[lo:hi]).strip()
        out.append(frag)
        start = i + len(needle)
    return out

def script_urls(html: str, base: str):
    urls = []
    for m in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I):
        u = urljoin(base, m.group(1))
        if urlparse(u).netloc.endswith("sse.com.cn"):
            urls.append(u)
    return sorted(set(urls))

def parse_json_or_jsonp(text: str):
    s = text.strip()
    try:
        return json.loads(s), "json"
    except Exception:
        pass
    m = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", s, flags=re.S)
    if not m:
        raise ValueError("not JSON/JSONP")
    return json.loads(m.group(1)), "jsonp"

def bounded_row(row):
    if not isinstance(row, dict):
        return row
    wanted = (
        "securityCode", "securityName", "productCode", "productName",
        "startStopDate", "endStopDate", "startStopTime", "endStopTime",
        "startStopReason", "endStopReason", "stopReason", "controlType",
    )
    return {k: row.get(k) for k in wanted if k in row}


def daily_suspension_probe(session, search_date: str):
    params = {
        "isPagination": "true",
        "sqlId": "COMMON_SSE_XXPL_JYTS_TFPXX_L",
        "SEARCH_DATE": search_date,
        "pageHelp.pageSize": "200",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "jsonCallBack": "jsonpCallback",
    }
    r, meta = post_fetch(session, DAILY_ENDPOINT, data=params, attempts=3)
    payload, parsed_as = parse_json_or_jsonp(decode(r))
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"daily suspension result is not a list for {search_date}")
    bounded = []
    for row in rows[:200]:
        if isinstance(row, dict):
            bounded.append({
                k: row.get(k)
                for k in (
                    "PRODUCT_CODE", "PRODUCT_NAME", "STOP_DATE", "STOP_TIME",
                    "STOP_REASON", "CONTROLTYPE", "SEC_CODE", "SEC_NAME_CN",
                )
                if k in row
            })
    return {
        "searchDate": search_date,
        "status": r.status_code,
        "url": r.url,
        "sha256": sha256(r.content),
        "attempt": meta["attempt"],
        "parsed_as": parsed_as,
        "row_count": len(rows),
        "rows": bounded[:50],
    }


def trade_day_probe(session, biz_date: str):
    params = {
        "sqlId": "GW_PL_JYTS_TFPXX_TRADEDAY",
        "bizDate": biz_date,
        "jsonCallBack": "jsonpCallback",
    }
    r, meta = post_fetch(session, ENDPOINT, data=params, attempts=3)
    payload, parsed_as = parse_json_or_jsonp(decode(r))
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"trade-day result is not a list for {biz_date}")
    return {
        "bizDate": biz_date,
        "status": r.status_code,
        "url": r.url,
        "sha256": sha256(r.content),
        "attempt": meta["attempt"],
        "parsed_as": parsed_as,
        "row_count": len(rows),
        "rows": rows[:5],
    }

def main():
    s = requests.Session()

    source_report = {}
    texts = {}

    trade_day_dates = [
        "20260924",  # last regular day before 2026 Mid-Autumn closure
        "20260925",  # official closure
        "20260927",  # weekend / official closure
        "20260928",  # reopen
        "20260930",  # last regular day before National Day closure
        "20261001",  # official closure
        "20261005",  # official closure
        "20261008",  # reopen
        "20260223",  # Spring Festival closure
        "20260224",  # reopen
    ]
    trade_day_contract = {
        d: trade_day_probe(s, d)
        for d in trade_day_dates
    }

    daily_probe_dates = [
        "20260924",
        "20260930",
        "20240104",
        "20220104",
    ]
    daily_suspension_contract = {}
    daily_suspension_errors = {}
    for d in daily_probe_dates:
        try:
            daily_suspension_contract[d] = daily_suspension_probe(s, d)
        except Exception as exc:
            daily_suspension_errors[d] = f"{type(exc).__name__}: {exc}"
    trade_day_before_values = {}
    for d, item in trade_day_contract.items():
        rows = item.get("rows") or []
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        trade_day_before_values[d] = row.get("beforeTradeDay")
    trade_day_endpoint_supported = all(
        isinstance(v, str) and len(v) == 8 and v.isdigit()
        for v in trade_day_before_values.values()
    )
    for label, url in [
        ("suspension_page", SUSPENSION_PAGE),
        ("suspension_script", SUSPENSION_SCRIPT),
        ("calendar_page", CALENDAR_PAGE),
        ("closed_list", CLOSED_LIST),
    ]:
        r, meta = fetch(s, url)
        text = decode(r)
        texts[label] = text
        source_report[label] = {
            "url": r.url,
            "status": r.status_code,
            "bytes": len(r.content),
            "sha256": sha256(r.content),
            "content_type": r.headers.get("Content-Type"),
            "attempt": meta["attempt"],
        }

    frontend_semantics = {
        "endStopDate": snippets(texts["suspension_script"], "endStopDate"),
        "endStopReason": snippets(texts["suspension_script"], "endStopReason"),
        "startStopDate": snippets(texts["suspension_script"], "startStopDate"),
        "resume_terms": snippets(texts["suspension_script"], "复牌") + snippets(texts["suspension_script"], "恢复"),
    }

    discovered = {}
    all_scripts = set()
    for label in ("suspension_page", "calendar_page", "closed_list"):
        urls = script_urls(texts[label], source_report[label]["url"])
        discovered[label] = urls
        all_scripts.update(urls)

    candidate_scripts = []
    for url in sorted(all_scripts):
        lower = url.lower()
        if not any(k in lower for k in ("calendar", "trade", "query", "closed", "dealinstruc", "public")):
            continue
        try:
            r, meta = fetch(s, url, attempts=2)
            txt = decode(r)
            hits = {}
            for term in ("sqlId", "commonSoaQuery", "calendar", "tradeDate", "tradeDay", "休市", "开市", "endStopDate"):
                ss = snippets(txt, term, radius=260, limit=4)
                if ss:
                    hits[term] = ss
            if hits:
                candidate_scripts.append({
                    "url": r.url,
                    "status": r.status_code,
                    "bytes": len(r.content),
                    "sha256": sha256(r.content),
                    "attempt": meta["attempt"],
                    "hits": hits,
                })
        except Exception as exc:
            candidate_scripts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    params = {
        "isPagination": "true",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "pageHelp.pageSize": "100",
        "pageHelp.pageNo": "1",
        "productCode": "",
        "keyWords": "",
        "startStopDate": "20260101",
        "endStopDate": "20260930",
        "jsonCallBack": "jsonpCallback",
    }
    rr, rmeta = fetch(s, ENDPOINT, params=params)
    payload, parsed_as = parse_json_or_jsonp(decode(rr))
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("official suspension endpoint result is not a list")
    with_end = [bounded_row(x) for x in rows if isinstance(x, dict) and x.get("endStopDate")]
    with_end_reason = [x for x in with_end if x.get("endStopReason")]

    report = {
        "schema": "stock-sse-calendar-semantic-probe-v1",
        "source_report": source_report,
        "frontend_semantics": frontend_semantics,
        "discovered_script_urls": discovered,
        "candidate_scripts": candidate_scripts,
        "daily_suspension_contract": {
            "endpoint": DAILY_ENDPOINT,
            "sqlId": "COMMON_SSE_XXPL_JYTS_TFPXX_L",
            "probe_dates": daily_probe_dates,
            "responses": daily_suspension_contract,
            "errors": daily_suspension_errors,
            "endpoint_supported": bool(daily_suspension_contract) and not daily_suspension_errors,
        },
        "trade_day_contract": {
            "sqlId": "GW_PL_JYTS_TFPXX_TRADEDAY",
            "probe_dates": trade_day_dates,
            "beforeTradeDay": trade_day_before_values,
            "responses": trade_day_contract,
            "endpoint_supported": trade_day_endpoint_supported,
        },
        "suspension_sample": {
            "endpoint": rr.url,
            "status": rr.status_code,
            "sha256": sha256(rr.content),
            "attempt": rmeta["attempt"],
            "parsed_as": parsed_as,
            "row_count": len(rows),
            "rows_with_endStopDate": len(with_end),
            "rows_with_endStopReason": len(with_end_reason),
            "sample_with_endStopDate": with_end[:20],
        },
        "adjudication": {
            "official_sources_reached": True,
            "frontend_endStopDate_semantics": "SUPPORTED" if frontend_semantics["endStopDate"] else "NOT VERIFIED",
            "sse_daily_suspension_snapshot_endpoint": (
                "SUPPORTED"
                if bool(daily_suspension_contract) and not daily_suspension_errors
                else "NOT VERIFIED"
            ),
            "sse_trade_day_endpoint": "SUPPORTED" if trade_day_endpoint_supported else "NOT VERIFIED",
            "independent_sse_trading_calendar_contract": "SUPPORTED_ENDPOINT_ONLY" if trade_day_endpoint_supported else "NOT VERIFIED",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_calendar_semantic_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "frontend_endStopDate_fragments": len(frontend_semantics["endStopDate"]),
        "resume_term_fragments": len(frontend_semantics["resume_terms"]),
        "candidate_script_count": len(candidate_scripts),
        "daily_suspension_snapshot_supported": bool(daily_suspension_contract) and not daily_suspension_errors,
        "daily_suspension_row_counts": {
            d: item.get("row_count")
            for d, item in daily_suspension_contract.items()
        },
        "daily_suspension_errors": daily_suspension_errors,
        "trade_day_endpoint_supported": trade_day_endpoint_supported,
        "trade_day_before_values": trade_day_before_values,
        "sample_rows_with_endStopDate": len(with_end),
        "historical_daily_suspension_state": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
