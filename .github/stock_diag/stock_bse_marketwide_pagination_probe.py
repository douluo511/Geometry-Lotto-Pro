from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
TYPE_ENDPOINT = "https://www.bse.cn/disclosureInfoController/disclosure_type.do"
OUT = Path("stock_bse_marketwide_pagination_probe.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE pagination probe"
START = "2018-01-01"
END = "2026-09-30"
KEYWORDS = ["风险警示", "退市风险警示", "撤销风险警示"]
NEED_FIELDS = [
    "companyCd", "companyName", "disclosureTitle", "disclosurePostTitle",
    "destFilePath", "publishDate", "xxfcbj", "fileExt", "xxzrlx",
]

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def same_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")

def parse_jsonp(payload: str):
    text = payload.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not m:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(m.group(1))

def find_records(obj):
    records = []
    def walk(x):
        if isinstance(x, dict):
            keys = set(x)
            if {"companyCd", "publishDate"} <= keys and (
                "disclosureTitle" in keys or "destFilePath" in keys
            ):
                records.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    unique = {}
    for r in records:
        key = (
            str(r.get("companyCd")), str(r.get("publishDate")),
            str(r.get("disclosureTitle")), str(r.get("destFilePath")),
        )
        unique[key] = r
    return [unique[k] for k in sorted(unique)]

def page_meta(obj):
    found = {}
    def walk(x):
        nonlocal found
        if isinstance(x, dict):
            keys = {"number", "numberOfElements", "size", "totalElements", "totalPages"}
            if keys <= set(x):
                found = {k: x.get(k) for k in sorted(keys)}
                return
            for v in x.values():
                if not found:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                if not found:
                    walk(v)
    walk(obj)
    return found

def request_json(session, url: str, *, params=None):
    r = session.get(
        url,
        params=params,
        headers={
            "User-Agent": UA,
            "Accept": "application/javascript,application/json,text/plain,*/*",
            "Referer": "https://www.bse.cn/disclosure/announcement.html",
        },
        timeout=(10, 30),
        allow_redirects=True,
    )
    meta = {
        "status": r.status_code,
        "resolved_url": r.url,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "sha256": sha256(r.content),
        "same_official_host": same_bse(r.url),
    }
    if r.status_code != 200 or not r.content or not same_bse(r.url):
        return None, meta
    try:
        obj = parse_jsonp(r.content.decode(r.encoding or "utf-8", errors="strict"))
        meta["parse"] = "PASS"
        return obj, meta
    except Exception as exc:
        meta["parse"] = "FAIL"
        meta["parse_error"] = f"{type(exc).__name__}: {exc}"
        return None, meta

def collect_type_values(obj):
    vals = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"distype", "dvalue", "disclosureType", "value"}:
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        vals.append(str(v).strip())
                    elif isinstance(v, list):
                        vals.extend(str(z).strip() for z in v if str(z).strip())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return list(dict.fromkeys(vals))

def request_page(session, keyword: str, page: int):
    base = {
        "callback": "stockAiBseMarketCb",
        "disclosureSubtype": "",
        "page": page,
        "companyCd": "",
        "isNewThree": 1,
        "startTime": START,
        "endTime": END,
        "keyword": keyword,
        "hyType": "",
    }
    pairs = list(base.items())
    pairs += [("disclosureType[]", "5"), ("xxfcbj[]", "2")]
    pairs += [("needFields[]", field) for field in NEED_FIELDS]
    r = session.post(
        ENDPOINT,
        data=pairs,
        headers={
            "User-Agent": UA,
            "Accept": "application/javascript,application/json,text/plain,*/*",
            "Referer": "https://www.bse.cn/disclosure/announcement.html",
        },
        timeout=(10, 30),
        allow_redirects=True,
    )
    meta = {
        "page_requested": page,
        "status": r.status_code,
        "resolved_url": r.url,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "sha256": sha256(r.content),
        "same_official_host": same_bse(r.url),
    }
    if r.status_code != 200 or not r.content or not same_bse(r.url):
        return None, meta
    try:
        obj = parse_jsonp(r.content.decode(r.encoding or "utf-8", errors="strict"))
        meta["parse"] = "PASS"
        return obj, meta
    except Exception as exc:
        meta["parse"] = "FAIL"
        meta["parse_error"] = f"{type(exc).__name__}: {exc}"
        return None, meta

def summarize(obj, transport, keyword):
    records = find_records(obj) if obj is not None else []
    meta = page_meta(obj) if obj is not None else {}
    title_hits = []
    for r in records:
        title = str(r.get("disclosureTitle") or "") + str(r.get("disclosurePostTitle") or "")
        if keyword in title:
            title_hits.append({
                "companyCd": r.get("companyCd"),
                "companyName": r.get("companyName"),
                "publishDate": r.get("publishDate"),
                "title": title,
                "destFilePath": r.get("destFilePath"),
            })
    return {
        "transport": transport,
        "page_meta": meta,
        "record_count": len(records),
        "title_keyword_match_count": len(title_hits),
        "title_keyword_sample": title_hits[:8],
        "record_code_sample": list(dict.fromkeys(
            str(r.get("companyCd") or "").strip() for r in records
            if str(r.get("companyCd") or "").strip()
        ))[:12],
    }

def main() -> int:
    session = requests.Session()
    type_obj, type_transport = request_json(session, TYPE_ENDPOINT, params={"type": 6})
    type_values = collect_type_values(type_obj) if type_obj is not None else []
    official_type_5 = "5" in type_values

    results = []
    surface_supported = official_type_5 and type_transport.get("parse") == "PASS"
    observed_event_sample = False

    for keyword in KEYWORDS:
        obj0, t0 = request_page(session, keyword, 0)
        s0 = summarize(obj0, t0, keyword)
        pm0 = s0["page_meta"]
        probe_pass = (
            t0.get("status") == 200
            and t0.get("same_official_host") is True
            and t0.get("parse") == "PASS"
            and isinstance(pm0.get("totalPages"), int)
            and isinstance(pm0.get("totalElements"), int)
            and isinstance(pm0.get("number"), int)
            and pm0.get("number") == 0
            and pm0.get("totalPages") >= 0
            and pm0.get("totalElements") >= 0
        )
        pages = [s0]
        total_pages = int(pm0.get("totalPages") or 0) if probe_pass else 0

        if probe_pass and total_pages > 1:
            obj1, t1 = request_page(session, keyword, 1)
            s1 = summarize(obj1, t1, keyword)
            pages.append(s1)
            pm1 = s1["page_meta"]
            probe_pass = probe_pass and (
                t1.get("status") == 200
                and t1.get("same_official_host") is True
                and t1.get("parse") == "PASS"
                and pm1.get("number") == 1
                and pm1.get("totalPages") == pm0.get("totalPages")
                and pm1.get("totalElements") == pm0.get("totalElements")
            )

        if probe_pass:
            objn, tn = request_page(session, keyword, total_pages)
            sn = summarize(objn, tn, keyword)
            pages.append(sn)
            probe_pass = probe_pass and (
                tn.get("status") == 200
                and tn.get("same_official_host") is True
                and tn.get("parse") == "PASS"
                and sn["record_count"] == 0
            )

        title_hits = sum(p["title_keyword_match_count"] for p in pages[:-1] if pages)
        observed_event_sample = observed_event_sample or title_hits > 0
        results.append({
            "keyword": keyword,
            "status": "PASS" if probe_pass else "NOT VERIFIED",
            "total_pages": total_pages,
            "total_elements": pm0.get("totalElements") if pm0 else None,
            "observed_title_hit_count_in_sampled_pages": title_hits,
            "pages": pages,
        })
        surface_supported = surface_supported and probe_pass

    adjudication = {
        "bse_marketwide_pagination_contract": "SUPPORTED_SAMPLE" if surface_supported else "NOT VERIFIED",
        "bse_marketwide_keyword_event_sample": "SUPPORTED_SAMPLE" if surface_supported and observed_event_sample else "NOT VERIFIED",
        "exhaustive_bse_event_corpus": "NOT VERIFIED",
        "bse_historical_st_pit": "NOT VERIFIED",
        "bse_historical_suspension_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "product_bytes_changed": False,
        "final_gate": "FAIL",
    }
    report = {
        "schema": "stock-bse-marketwide-pagination-probe-v1",
        "endpoint": ENDPOINT,
        "window": {"start": START, "end": END},
        "keywords": KEYWORDS,
        "official_type_contract": {
            "endpoint": TYPE_ENDPOINT,
            "transport": type_transport,
            "type_5_present": official_type_5,
            "candidate_count": len(type_values),
        },
        "results": results,
        "adjudication": adjudication,
        "boundary": (
            "This probe validates market-wide query/pagination semantics only. It samples page 0, "
            "page 1 when present, and the server-denominated N+1 page. It does not claim full-page "
            "retrieval, exhaustive BSE events, daily ST identity, suspension state, PIT, or Final."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "keyword_statuses": [x["status"] for x in results],
        "total_pages": {x["keyword"]: x["total_pages"] for x in results},
        "total_elements": {x["keyword"]: x["total_elements"] for x in results},
        "adjudication": adjudication,
    }, ensure_ascii=True, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
