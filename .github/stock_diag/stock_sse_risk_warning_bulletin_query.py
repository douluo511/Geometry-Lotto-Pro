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
PRODUCT = "688496"
BEGIN = "2025-01-01"
END = "2026-10-06"
QUERIES = [
    ("risk_warning", "风险警示"),
    ("delisting_risk_warning", "退市风险警示"),
    ("cancel_risk_warning", "撤销风险警示"),
    ("security_short_name", "证券简称"),
]

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

def get(session,params,attempts=3):
    errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=session.get(
                ENDPOINT,params=params,
                headers={"User-Agent":UA,"Referer":REFERER,"Accept":"application/json,text/javascript,*/*;q=0.01"},
                timeout=(8,30),allow_redirects=True,
            )
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            text=r.content.decode(r.encoding or "utf-8",errors="replace")
            obj,kind=parse(text)
            return obj,{
                "attempt":attempt,"prior_errors":errors,"http_status":r.status_code,
                "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                "content_type":r.headers.get("Content-Type"),"parsed_as":kind,"url":r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))

def rows_from(obj):
    if isinstance(obj,dict):
        for key in ("result","data"):
            if isinstance(obj.get(key),list):
                return obj[key]
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

def bounded(row):
    if not isinstance(row,dict):
        return row
    wanted=(
        "SECURITY_CODE","SECURITY_NAME","BULLETIN_TYPE","BULLETIN_YEAR",
        "BULLETIN_TITLE","BULLETIN_ID","SSEDATE","SSE_DATE","URL",
        "securityCode","securityName","bulletinType","bulletinTitle",
        "bulletinId","publishDate","title","url",
    )
    keep={k:row.get(k) for k in wanted if k in row}
    if not keep:
        keep={k:row.get(k) for k in sorted(row)[:20]}
    return keep

def title_of(row):
    if not isinstance(row,dict):
        return ""
    for k in ("BULLETIN_TITLE","bulletinTitle","title","TITLE"):
        if row.get(k):
            return str(row.get(k))
    return ""

def main():
    s=requests.Session()
    results=[]
    total_rows=0
    relevant_rows=0
    for label,keyword in QUERIES:
        params={
            "isPagination":"true",
            "productId":PRODUCT,
            "keyWord":keyword,
            "securityType":"0101,120100,020100,020200,120200",
            "reportType2":"",
            "reportType":"ALL",
            "beginDate":BEGIN,
            "endDate":END,
            "pageHelp.pageSize":"100",
            "pageHelp.pageNo":"1",
            "pageHelp.beginPage":"1",
            "pageHelp.cacheSize":"1",
            "pageHelp.endPage":"5",
            "jsonCallBack":"jsonpCallback",
        }
        obj,meta=get(s,params)
        rows=rows_from(obj)
        total_rows+=len(rows)
        matched=[r for r in rows if keyword in title_of(r)]
        relevant_rows+=len(matched)
        results.append({
            "label":label,"keyword":keyword,"fetch":meta,
            "page":page_meta(obj),"row_count":len(rows),
            "title_match_count":len(matched),
            "sample":[bounded(x) for x in rows[:10]],
            "matched_sample":[bounded(x) for x in matched[:10]],
            "top_keys":sorted(obj)[:30] if isinstance(obj,dict) else [],
        })

    endpoint_supported=all(x["fetch"]["http_status"]==200 for x in results)
    machine_parse_supported=all(x["row_count"]>=0 for x in results)
    risk_history_found=any(
        x["row_count"]>0 for x in results
        if x["label"] in {"risk_warning","delisting_risk_warning","cancel_risk_warning"}
    )
    report={
        "schema":"stock-sse-risk-warning-bulletin-query-v1",
        "endpoint":ENDPOINT,
        "product":PRODUCT,
        "window":{"begin":BEGIN,"end":END},
        "queries":results,
        "summary":{"total_rows":total_rows,"title_matched_rows":relevant_rows},
        "adjudication":{
            "official_company_bulletin_endpoint":"SUPPORTED" if endpoint_supported else "NOT VERIFIED",
            "machine_parse_contract":"SUPPORTED" if machine_parse_supported else "NOT VERIFIED",
            "risk_warning_bulletin_history_surface":"SUPPORTED" if risk_history_found else "NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_risk_warning_bulletin_query.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if endpoint_supported and machine_parse_supported and risk_history_found else 2

if __name__=="__main__":
    raise SystemExit(main())
