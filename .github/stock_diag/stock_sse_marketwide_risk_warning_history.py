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
KEYWORDS = [
    ("risk_warning", "风险警示"),
    ("delisting_risk_warning", "退市风险警示"),
    ("cancel_risk_warning", "撤销风险警示"),
]
# Frozen representative years across the research window. This is a bounded
# source-surface discovery gate, not an exhaustive event corpus.
YEARS = [2018, 2020, 2022, 2024, 2026]
PAGE_SIZE = 100
CODE_RE = re.compile(r"^6\d{5}$")
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
    if not isinstance(obj,dict):
        return []
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


def field(row,*keys):
    for k in keys:
        value=row.get(k) if isinstance(row,dict) else None
        if value not in (None,""):
            return str(value).strip()
    return ""


def bounded(row):
    code=field(row,"SECURITY_CODE","securityCode")
    name=field(row,"SECURITY_NAME","securityName")
    dt=field(row,"SSEDATE","SSE_DATE","publishDate","SSE_DATE_NEW")
    title=field(row,"BULLETIN_TITLE","bulletinTitle","title","TITLE")
    url=field(row,"URL","url")
    return {"security_code":code,"security_name":name,"date":dt,"title":title,"url":url}


def main():
    s=requests.Session()
    probes=[]
    errors=[]
    observed_codes=set()
    nonempty_years=set()
    payload_by_key={}
    total_positive=0
    missing_name_rows=0

    for year in YEARS:
        begin=f"{year}-01-01"
        end=f"{year}-12-31" if year<2026 else "2026-09-30"
        for label,keyword in KEYWORDS:
            params={
                "isPagination":"true",
                "productId":"",
                "secCodes":"",
                "keyWord":keyword,
                "securityType":"0101,120100,020100,020200,120200",
                "reportType2":"","reportType":"ALL",
                "beginDate":begin,"endDate":end,
                "pageHelp.pageSize":str(PAGE_SIZE),
                "pageHelp.pageNo":"1","pageHelp.beginPage":"1",
                "pageHelp.cacheSize":"1","pageHelp.endPage":"5",
                "jsonCallBack":"jsonpCallback",
            }
            try:
                obj,meta=get(s,params)
                rows=rows_from(obj)
                pm=page_meta(obj)
                normalized=[]
                for row in rows:
                    b=bounded(row)
                    code,name,dt,url=b["security_code"],b["security_name"],b["date"],b["url"]
                    if B_SHARE_RE.fullmatch(code):
                        skipped_b_share_rows += 1
                        continue
                    if not CODE_RE.fullmatch(code):
                        raise ValueError(f"unexpected non-A/non-B Shanghai code: {code!r}")
                    if not name:
                        missing_name_rows += 1
                    if not DATE_RE.fullmatch(dt) or int(dt[:4])!=year:
                        raise ValueError(f"date filter not honored: {dt!r} for year {year}")
                    if not (url.startswith("/disclosure/") or url.startswith("https://")):
                        raise ValueError(f"unexpected URL for {code}: {url!r}")
                    normalized.append(b)
                    observed_codes.add(code)
                total=int(pm.get("total") or 0)
                page_count=int(pm.get("pageCount") or 0)
                if total>0:
                    total_positive+=1
                    nonempty_years.add(year)
                    if not rows or page_count<1:
                        raise ValueError("positive total without first-page rows/pageCount")
                payload_by_key[(year,label)]=meta["payload_sha256"]
                probes.append({
                    "year":year,"label":label,"keyword":keyword,
                    "begin":begin,"end":end,"fetch":meta,"page":pm,
                    "row_count":len(rows),"unique_codes":len({x["security_code"] for x in normalized}),
                    "missing_name_rows":sum(1 for x in normalized if not x["security_name"]),
                    "st_named_rows":sum(1 for x in normalized if x["security_name"] and "ST" in x["security_name"].upper()),
                    "sample":normalized[:12],
                })
            except Exception as exc:
                errors.append({"year":year,"label":label,"keyword":keyword,"error":f"{type(exc).__name__}: {exc}"})

    # Date filtering is meaningful only if the same keyword does not return an
    # identical payload for every frozen year.
    keyword_date_discrimination={}
    for label,_ in KEYWORDS:
        hashes=[payload_by_key.get((year,label)) for year in YEARS if payload_by_key.get((year,label))]
        keyword_date_discrimination[label]=len(set(hashes))>=2

    supported=(
        not errors
        and len(probes)==len(YEARS)*len(KEYWORDS)
        and len(nonempty_years)>=4
        and total_positive>=5
        and len(observed_codes)>=20
        and all(keyword_date_discrimination.values())
    )

    report={
        "schema":"stock-sse-marketwide-risk-warning-surface-v3",
        "endpoint":ENDPOINT,
        "frozen_probe_years":YEARS,
        "query_scope":"productId blank; bounded first-page probes; Shanghai A-share target; recognized 900xxx B-share rows explicitly excluded",
        "probe_count":len(probes),
        "errors":errors,
        "summary":{
            "nonempty_years":sorted(nonempty_years),
            "positive_total_probe_count":total_positive,
            "observed_unique_codes":len(observed_codes),
            "missing_name_rows":missing_name_rows,
            "name_field_complete":missing_name_rows == 0,
            "skipped_known_b_share_rows":skipped_b_share_rows,
            "keyword_date_discrimination":keyword_date_discrimination,
        },
        "probes":probes,
        "adjudication":{
            "marketwide_risk_warning_query_surface":"SUPPORTED" if supported else "NOT VERIFIED",
            "exhaustive_marketwide_event_corpus":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "effective_state_reconstruction":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":"This bounded gate only proves that official SSE market-wide historical query parameters discriminate dates/keywords and expose multi-security paginated results. Missing SECURITY_NAME is retained as an explicit field-coverage gap and MUST NOT be used to infer ST identity. It does not exhaust pages, infer effective dates, or promote historical ST/PIT.",
    }
    Path("stock_sse_marketwide_risk_warning_history.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if supported else 2


if __name__=="__main__":
    raise SystemExit(main())
