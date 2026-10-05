from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
BEGIN = "2018-01-01"
END = "2026-10-06"
KEYWORD = "风险警示"
PAGE_SIZE = 100
MAX_PAGES = 200


def parse(text: str):
    t = text.strip()
    try:
        return json.loads(t), "json"
    except Exception:
        pass
    m = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", t, flags=re.S)
    if m:
        return json.loads(m.group(1)), "jsonp"
    raise ValueError("response is neither JSON nor simple JSONP")


def get(session, params, attempts=4):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                ENDPOINT,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Referer": REFERER,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            obj, kind = parse(r.content.decode(r.encoding or "utf-8", errors="replace"))
            return obj, {
                "attempt": attempt,
                "prior_errors": errors,
                "http_status": r.status_code,
                "payload_sha256": hashlib.sha256(r.content).hexdigest(),
                "parsed_as": kind,
                "url": r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def rows_from(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("result"), list):
            return obj["result"]
        ph = obj.get("pageHelp")
        if isinstance(ph, dict):
            for key in ("data", "result"):
                if isinstance(ph.get(key), list):
                    return ph[key]
    return []


def page_meta(obj):
    ph = obj.get("pageHelp") if isinstance(obj, dict) else None
    if not isinstance(ph, dict):
        return {}
    return {k: ph.get(k) for k in ("pageNo", "pageSize", "pageCount", "total")}


def pick(row, *names):
    for n in names:
        v = row.get(n) if isinstance(row, dict) else None
        if v not in (None, ""):
            return str(v)
    return ""


def canonical(row):
    return {
        "code": pick(row, "SECURITY_CODE", "securityCode"),
        "name": pick(row, "SECURITY_NAME", "securityName"),
        "date": pick(row, "SSEDATE", "SSE_DATE", "publishDate", "END_DATE"),
        "title": pick(row, "BULLETIN_TITLE", "bulletinTitle", "TITLE", "title"),
        "url": pick(row, "URL", "url"),
        "type": pick(row, "BULLETIN_TYPE", "bulletinType"),
    }


def main():
    s = requests.Session()
    rows = []
    fetches = []
    total_expected = None
    page_count = None

    for page_no in range(1, MAX_PAGES + 1):
        params = {
            "isPagination": "true",
            "productId": "",
            "keyWord": KEYWORD,
            "securityType": "0101,120100,020100,020200,120200",
            "reportType2": "",
            "reportType": "ALL",
            "beginDate": BEGIN,
            "endDate": END,
            "pageHelp.pageSize": str(PAGE_SIZE),
            "pageHelp.pageNo": str(page_no),
            "pageHelp.beginPage": str(max(1, page_no - 2)),
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": str(page_no + 2),
            "jsonCallBack": "jsonpCallback",
        }
        obj, meta = get(s, params)
        page_rows = rows_from(obj)
        pm = page_meta(obj)
        fetches.append({
            "page": page_no,
            "row_count": len(page_rows),
            "payload_sha256": meta["payload_sha256"],
            "http_status": meta["http_status"],
            "parsed_as": meta["parsed_as"],
            "page_meta": pm,
        })
        if total_expected is None and pm.get("total") is not None:
            total_expected = int(pm["total"])
        if page_count is None and pm.get("pageCount") is not None:
            page_count = int(pm["pageCount"])
        rows.extend(canonical(x) for x in page_rows)
        if not page_rows:
            break
        if page_count is not None and page_no >= page_count:
            break
        time.sleep(0.15)

    dedup = {}
    for row in rows:
        key = (row["code"], row["date"], row["url"], row["title"])
        dedup[key] = row
    rows = sorted(dedup.values(), key=lambda x: (x["date"], x["code"], x["url"]))

    dates = [x["date"] for x in rows if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["date"])]
    codes = sorted({x["code"] for x in rows if re.fullmatch(r"\d{6}", x["code"])})
    st_rows = [x for x in rows if x["name"].upper().startswith(("ST", "*ST"))]
    title_risk = [x for x in rows if "风险警示" in x["title"]]
    title_cancel = [x for x in rows if "撤销" in x["title"] and "风险警示" in x["title"]]
    title_implement = [x for x in rows if ("实施" in x["title"] or "被实施" in x["title"]) and "风险警示" in x["title"]]

    canonical_bytes = (json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    report = {
        "schema": "stock-sse-global-risk-warning-bulletin-corpus-v1",
        "endpoint": ENDPOINT,
        "window": {"begin": BEGIN, "end": END},
        "keyword": KEYWORD,
        "fetches": fetches,
        "summary": {
            "raw_rows": sum(x["row_count"] for x in fetches),
            "canonical_rows": len(rows),
            "unique_codes": len(codes),
            "st_named_rows": len(st_rows),
            "risk_title_rows": len(title_risk),
            "implement_title_rows": len(title_implement),
            "cancel_title_rows": len(title_cancel),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "endpoint_total": total_expected,
            "page_count": page_count,
            "canonical_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        },
        "samples": {
            "first": rows[:10],
            "st_named": st_rows[:20],
            "implement": title_implement[:20],
            "cancel": title_cancel[:20],
        },
        "adjudication": {
            "official_global_query": "SUPPORTED" if rows and codes else "NOT VERIFIED",
            "global_risk_warning_bulletin_corpus": "SUPPORTED" if len(rows) >= 100 and len(codes) >= 20 else "NOT VERIFIED",
            "event_semantics_complete": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_global_risk_warning_corpus.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["adjudication"]["global_risk_warning_bulletin_corpus"] == "SUPPORTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
