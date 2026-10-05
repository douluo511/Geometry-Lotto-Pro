from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

import requests

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
BEGIN = "2018-01-01"
END = "2026-09-30"
KEYWORDS = [
    ("risk_warning", "风险警示"),
    ("delisting_risk_warning", "退市风险警示"),
    ("cancel_risk_warning", "撤销风险警示"),
]
PAGE_SIZE = 100
MAX_PAGES = 100
A_SHARE_RE = re.compile(r"^6\d{5}$")
B_SHARE_RE = re.compile(r"^900\d{3}$")
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


def parse(text: str):
    t=text.strip()
    try:
        return json.loads(t),"json"
    except Exception:
        pass
    m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",t,flags=re.S)
    if m:
        return json.loads(m.group(1)),"jsonp"
    raise ValueError("response is neither JSON nor simple JSONP")


def params_for(keyword: str, page_no: int):
    return {
        "isPagination":"true",
        "productId":"",
        "keyWord":keyword,
        "securityType":"0101,120100,020100,020200,120200",
        "reportType2":"","reportType":"ALL",
        "beginDate":BEGIN,"endDate":END,
        "pageHelp.pageSize":str(PAGE_SIZE),
        "pageHelp.pageNo":str(page_no),
        # Exact navigation window is the only pagination mode independently
        # validated by PR #215. Sliding/fixed windows are intentionally rejected.
        "pageHelp.beginPage":str(page_no),
        "pageHelp.cacheSize":"1",
        "pageHelp.endPage":str(page_no),
        "jsonCallBack":"jsonpCallback",
    }


def get(session,keyword,page_no,attempts=3):
    errors=[]
    params=params_for(keyword,page_no)
    for attempt in range(1,attempts+1):
        try:
            r=session.get(
                ENDPOINT,params=params,
                headers={"User-Agent":UA,"Referer":REFERER,"Accept":"application/json,text/javascript,*/*;q=0.01"},
                timeout=(8,30),allow_redirects=True,
            )
            if r.status_code in (403,429) or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            obj,kind=parse(r.content.decode(r.encoding or "utf-8",errors="replace"))
            return obj,{
                "attempt":attempt,"prior_errors":errors,"http_status":r.status_code,
                "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                "parsed_as":kind,"url":r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(2**(attempt-1))


def rows_from(obj):
    if isinstance(obj,dict):
        if isinstance(obj.get("result"),list):
            return obj["result"]
        ph=obj.get("pageHelp")
        if isinstance(ph,dict):
            for key in ("data","result"):
                if isinstance(ph.get(key),list):
                    return ph[key]
    return []


def page_meta(obj):
    ph=obj.get("pageHelp") if isinstance(obj,dict) else None
    if not isinstance(ph,dict):
        return {}
    return {k:ph.get(k) for k in ("pageNo","pageSize","pageCount","total","beginPage","endPage") if k in ph}


def field(row,*keys):
    for k in keys:
        value=row.get(k) if isinstance(row,dict) else None
        if value not in (None,""):
            return str(value).strip()
    return ""


def normalized(row):
    return {
        "security_code":field(row,"SECURITY_CODE","securityCode"),
        "security_name":field(row,"SECURITY_NAME","securityName"),
        "date":field(row,"SSEDATE","SSE_DATE","publishDate","SSE_DATE_NEW","END_DATE"),
        "title":field(row,"BULLETIN_TITLE","bulletinTitle","title","TITLE"),
        "url":field(row,"URL","url"),
    }


def identity(x):
    return (x["security_code"],x["date"],x["url"],x["title"])


def canonical_sha(rows):
    payload=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fetch_keyword(session,label,keyword):
    first_obj,first_meta=get(session,keyword,1)
    first_rows=rows_from(first_obj)
    pm=page_meta(first_obj)
    total=int(pm.get("total") or 0)
    page_count=int(pm.get("pageCount") or 0)
    if total<=0 or page_count<=0:
        raise RuntimeError(f"{label}: non-positive total/pageCount")
    expected=math.ceil(total/PAGE_SIZE)
    if page_count!=expected:
        raise RuntimeError(f"{label}: pageCount mismatch server={page_count} expected={expected}")
    if page_count>MAX_PAGES:
        raise RuntimeError(f"{label}: pageCount {page_count} exceeds MAX_PAGES={MAX_PAGES}")

    pages=[]
    all_rows=[]
    seen=set()
    for page_no in range(1,page_count+1):
        if page_no==1:
            obj,meta=first_obj,first_meta
        else:
            obj,meta=get(session,keyword,page_no)
        rows=rows_from(obj)
        pmeta=page_meta(obj)
        if int(pmeta.get("pageNo") or -1)!=page_no:
            raise RuntimeError(f"{label}: page echo mismatch requested={page_no} got={pmeta.get('pageNo')}")
        if int(pmeta.get("total") or -1)!=total or int(pmeta.get("pageCount") or -1)!=page_count:
            raise RuntimeError(f"{label}: pagination denominator drift at page {page_no}")
        expected_rows=PAGE_SIZE if page_no<page_count else (total-PAGE_SIZE*(page_count-1) or PAGE_SIZE)
        if len(rows)!=expected_rows:
            raise RuntimeError(f"{label}: row-count mismatch page={page_no} observed={len(rows)} expected={expected_rows}")
        norm=[normalized(r) for r in rows]
        ids=[identity(x) for x in norm]
        if len(set(ids))!=len(ids):
            raise RuntimeError(f"{label}: duplicate identity within page {page_no}")
        overlap=seen & set(ids)
        if overlap:
            raise RuntimeError(f"{label}: cross-page duplicate identities page={page_no} count={len(overlap)}")
        seen.update(ids)
        for x in norm:
            code=x["security_code"]; dt=x["date"]; url=x["url"]
            if B_SHARE_RE.fullmatch(code):
                pass
            elif not A_SHARE_RE.fullmatch(code):
                raise RuntimeError(f"{label}: unexpected Shanghai code {code!r}")
            if not DATE_RE.fullmatch(dt) or not (BEGIN<=dt<=END):
                raise RuntimeError(f"{label}: out-of-window/invalid date {dt!r}")
            if not (url.startswith("/disclosure/") or url.startswith("https://")):
                raise RuntimeError(f"{label}: unexpected bulletin URL {url!r}")
        all_rows.extend(norm)
        pages.append({
            "page":page_no,"rows":len(rows),
            "payload_sha256":meta["payload_sha256"],
            "page_meta":pmeta,
            "first_identity":list(ids[0]) if ids else None,
            "last_identity":list(ids[-1]) if ids else None,
        })
        time.sleep(0.08)

    # Page N+1 MUST be empty under the exact navigation contract.
    beyond_obj,beyond_meta=get(session,keyword,page_count+1)
    beyond_rows=rows_from(beyond_obj)
    if beyond_rows:
        raise RuntimeError(f"{label}: page N+1 is non-empty ({len(beyond_rows)} rows)")

    a_rows=[x for x in all_rows if A_SHARE_RE.fullmatch(x["security_code"])]
    b_rows=[x for x in all_rows if B_SHARE_RE.fullmatch(x["security_code"])]
    return {
        "label":label,"keyword":keyword,
        "server":{"total":total,"page_count":page_count,"page_size":PAGE_SIZE},
        "pages":pages,
        "beyond_page":{
            "page":page_count+1,"rows":0,
            "payload_sha256":beyond_meta["payload_sha256"],
            "page_meta":page_meta(beyond_obj),
        },
        "raw_rows":len(all_rows),
        "a_share_rows":len(a_rows),
        "b_share_rows":len(b_rows),
        "missing_security_name_rows":sum(1 for x in a_rows if not x["security_name"]),
        "st_named_a_share_rows":sum(1 for x in a_rows if "ST" in x["security_name"].upper()),
        "canonical_sha256":canonical_sha(all_rows),
        "a_share_canonical_sha256":canonical_sha(a_rows),
        "records":a_rows,
    }


def main():
    s=requests.Session()
    keyword_results=[]
    combined={}
    for label,keyword in KEYWORDS:
        item=fetch_keyword(s,label,keyword)
        for row in item["records"]:
            combined[identity(row)]=row
        item.pop("records")
        keyword_results.append(item)

    corpus=[combined[k] for k in sorted(combined)]
    corpus_sha=canonical_sha(corpus)
    supported=bool(corpus) and all(x["raw_rows"]==x["server"]["total"] for x in keyword_results)

    report={
        "schema":"stock-sse-marketwide-risk-warning-corpus-v4",
        "endpoint":ENDPOINT,
        "window":{"begin":BEGIN,"end":END},
        "pagination_contract":"exact_navigation_window",
        "keywords":keyword_results,
        "corpus":{
            "unique_a_share_event_rows":len(corpus),
            "unique_codes":len({x["security_code"] for x in corpus}),
            "st_named_rows":sum(1 for x in corpus if "ST" in x["security_name"].upper()),
            "missing_security_name_rows":sum(1 for x in corpus if not x["security_name"]),
            "canonical_sha256":corpus_sha,
        },
        "adjudication":{
            "pagination_integrity":"PASS" if supported else "FAIL",
            "marketwide_risk_warning_query_surface":"SUPPORTED" if supported else "NOT VERIFIED",
            "exhaustive_marketwide_event_corpus":"SUPPORTED" if supported else "NOT VERIFIED",
            "event_semantics_complete":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "effective_state_reconstruction":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":"This exhausts the official SSE bulletin-search corpus for three frozen risk-warning keywords using the independently validated exact-navigation pagination contract. It proves event-source completeness for those queries only; bulletin semantics/effective state transitions still require primary-document validation before Shanghai historical ST/PIT can pass.",
    }
    Path("stock_sse_marketwide_risk_warning_history.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps({
        "schema":report["schema"],
        "corpus":report["corpus"],
        "keyword_summaries":[{k:x[k] for k in ("label","raw_rows","a_share_rows","b_share_rows","st_named_a_share_rows","missing_security_name_rows","canonical_sha256")} for x in keyword_results],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if supported else 2


if __name__=="__main__":
    raise SystemExit(main())
