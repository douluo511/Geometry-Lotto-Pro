from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from datetime import date

import requests

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
KEYWORDS = [
    ("risk_warning", "风险警示"),
    ("delisting_risk_warning", "退市风险警示"),
    ("cancel_risk_warning", "撤销风险警示"),
]
YEARS = list(range(2018, 2027))
PAGE_SIZE = 100
MAX_PAGES = 100
CODE_RE = re.compile(r"^6\d{5}$")
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


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


def get(session, params, attempts=3):
    errors=[]
    for attempt in range(1, attempts+1):
        try:
            r=session.get(
                ENDPOINT, params=params,
                headers={"User-Agent":UA,"Referer":REFERER,"Accept":"application/json,text/javascript,*/*;q=0.01"},
                timeout=(8,30), allow_redirects=True,
            )
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            obj,kind=parse(r.content.decode(r.encoding or "utf-8",errors="replace"))
            return obj,{
                "attempt":attempt,
                "prior_errors":errors,
                "http_status":r.status_code,
                "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                "parsed_as":kind,
                "url":r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(2**(attempt-1))


def rows_from(obj):
    if not isinstance(obj,dict):
        return []
    if isinstance(obj.get("result"),list):
        return obj["result"]
    if isinstance(obj.get("data"),list):
        return obj["data"]
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


def normalize(row, keyword, year):
    code=field(row,"SECURITY_CODE","securityCode")
    name=field(row,"SECURITY_NAME","securityName")
    dt=field(row,"SSEDATE","SSE_DATE","publishDate","SSE_DATE_NEW")
    title=field(row,"BULLETIN_TITLE","bulletinTitle","title","TITLE")
    url=field(row,"URL","url")
    if not CODE_RE.fullmatch(code):
        raise ValueError(f"invalid/non-Shanghai code: {code!r}")
    if not name:
        raise ValueError(f"missing security name for {code}")
    if not DATE_RE.fullmatch(dt):
        raise ValueError(f"missing/invalid bulletin date for {code}: {dt!r}")
    if int(dt[:4]) != int(year):
        raise ValueError(f"row escaped frozen year window: {dt} != {year}")
    if not url.startswith("/disclosure/") and not url.startswith("https://"):
        raise ValueError(f"unexpected bulletin URL for {code}: {url!r}")
    return {
        "security_code":code,
        "security_name":name,
        "date":dt,
        "title":title,
        "url":url,
        "query_keyword":keyword,
        "is_st_named":"ST" in name.upper(),
        "is_star_st_named":"*ST" in name.upper(),
    }


def canonical_hash(rows):
    raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fetch_year_keyword(session, year, label, keyword):
    begin=f"{year}-01-01"
    end=f"{year}-12-31" if year<2026 else "2026-09-30"
    out=[]
    payloads=[]
    seen_page_signatures=set()
    declared_total=None
    page_count=None
    for page in range(1,MAX_PAGES+1):
        params={
            "isPagination":"true",
            "productId":"",
            "secCodes":"",
            "keyWord":keyword,
            "securityType":"0101,120100,020100,020200,120200",
            "reportType2":"",
            "reportType":"ALL",
            "beginDate":begin,
            "endDate":end,
            "pageHelp.pageSize":str(PAGE_SIZE),
            "pageHelp.pageNo":str(page),
            "pageHelp.beginPage":str(page),
            "pageHelp.cacheSize":"1",
            "pageHelp.endPage":str(page+4),
            "jsonCallBack":"jsonpCallback",
        }
        obj,meta=get(session,params)
        rows=rows_from(obj)
        pm=page_meta(obj)
        payloads.append(meta)
        if declared_total is None and pm.get("total") is not None:
            declared_total=int(pm["total"])
        if page_count is None and pm.get("pageCount") is not None:
            page_count=int(pm["pageCount"])
        signature=hashlib.sha256(
            json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
        ).hexdigest()
        if rows and signature in seen_page_signatures:
            raise RuntimeError(f"repeated page payload before exhaustion year={year} keyword={keyword} page={page}")
        seen_page_signatures.add(signature)
        for row in rows:
            out.append(normalize(row,keyword,year))
        if not rows:
            break
        if page_count is not None and page>=page_count:
            break
        if declared_total is not None and len(out)>=declared_total:
            break
    else:
        raise RuntimeError(f"pagination exceeded MAX_PAGES year={year} keyword={keyword}")

    unique={}
    for row in out:
        key=(row["security_code"],row["date"],row["url"],row["query_keyword"])
        unique[key]=row
    rows=sorted(unique.values(),key=lambda x:(x["date"],x["security_code"],x["url"],x["query_keyword"]))
    if declared_total is not None and len(out)<declared_total:
        raise RuntimeError(f"did not exhaust declared total year={year} keyword={keyword}: {len(out)} < {declared_total}")
    return {
        "label":label,
        "keyword":keyword,
        "year":year,
        "begin":begin,
        "end":end,
        "declared_total":declared_total,
        "page_count":page_count,
        "raw_rows":len(out),
        "canonical_rows":len(rows),
        "unique_codes":len({r["security_code"] for r in rows}),
        "st_named_rows":sum(1 for r in rows if r["is_st_named"]),
        "star_st_named_rows":sum(1 for r in rows if r["is_star_st_named"]),
        "canonical_sha256":canonical_hash(rows),
        "payload_sha256s":[p["payload_sha256"] for p in payloads],
        "sample":rows[:10],
        "rows":rows,
    }


def main():
    s=requests.Session()
    slices=[]
    all_rows=[]
    errors=[]
    for year in YEARS:
        for label,keyword in KEYWORDS:
            try:
                item=fetch_year_keyword(s,year,label,keyword)
                slices.append({k:v for k,v in item.items() if k!="rows"})
                all_rows.extend(item["rows"])
            except Exception as exc:
                errors.append({"year":year,"label":label,"keyword":keyword,"error":f"{type(exc).__name__}: {exc}"})

    unique={}
    for row in all_rows:
        key=(row["security_code"],row["date"],row["url"],row["query_keyword"])
        unique[key]=row
    canonical=sorted(unique.values(),key=lambda x:(x["date"],x["security_code"],x["url"],x["query_keyword"]))
    codes=sorted({r["security_code"] for r in canonical})
    st_rows=[r for r in canonical if r["is_st_named"]]
    years_present=sorted({int(r["date"][:4]) for r in canonical})

    supported=(
        not errors
        and len(canonical)>=100
        and len(codes)>=50
        and len(years_present)>=5
        and len(st_rows)>=20
    )
    report={
        "schema":"stock-sse-marketwide-risk-warning-history-v1",
        "endpoint":ENDPOINT,
        "frozen_window":{"start":"2018-01-01","end":"2026-09-30"},
        "query_scope":"productId blank + risk-warning keywords",
        "slice_count":len(slices),
        "errors":errors,
        "summary":{
            "canonical_rows":len(canonical),
            "unique_codes":len(codes),
            "years_present":years_present,
            "st_named_rows":len(st_rows),
            "star_st_named_rows":sum(1 for r in canonical if r["is_star_st_named"]),
            "canonical_sha256":canonical_hash(canonical),
        },
        "slices":slices,
        "sample":canonical[:25],
        "adjudication":{
            "marketwide_risk_warning_event_surface":"SUPPORTED" if supported else "NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "effective_state_reconstruction":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":"A market-wide event surface may support a later effective-state reconstruction. Bulletin publication dates are not automatically effective dates and this diagnostic cannot promote Shanghai historical ST/PIT by itself.",
    }
    Path("stock_sse_marketwide_risk_warning_history.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if supported else 2

if __name__=="__main__":
    raise SystemExit(main())
