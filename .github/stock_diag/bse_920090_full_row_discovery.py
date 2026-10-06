from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

ENDPOINT="https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
OUT=Path("stock_bse_920090_full_row_discovery.json")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE exact-row discovery"
TARGET_DATE="2023-08-08"
TARGET_TITLE_TOKENS=("同辉","复牌")
DATE_RE=re.compile(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}")

def same_bse(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="bse.cn" or host.endswith(".bse.cn")

def sha256(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def parse_jsonp(raw:bytes):
    text=raw.decode("utf-8",errors="strict").strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        m=re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?",text,flags=re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def walk_records(obj):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            if {"companyCd","publishDate"} <= set(x) and ("disclosureTitle" in x or "destFilePath" in x):
                out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x,list):
            for v in x:
                walk(v)
    walk(obj)
    return out

def page_meta(obj):
    found={}
    def walk(x):
        nonlocal found
        if found:
            return
        if isinstance(x,dict):
            keys={"number","numberOfElements","size","totalElements","totalPages"}
            if keys <= set(x):
                found={k:x.get(k) for k in sorted(keys)}
                return
            for v in x.values():
                walk(v)
        elif isinstance(x,list):
            for v in x:
                walk(v)
    walk(obj)
    return found

def fetch_page(session,page:int):
    pairs=[
        ("callback","stockAiBseFullRowCb"),
        ("disclosureSubtype",""),
        ("page",page),
        ("companyCd",""),
        ("isNewThree",1),
        ("startTime",TARGET_DATE),
        ("endTime",TARGET_DATE),
        ("keyword","复牌"),
        ("hyType",""),
        ("disclosureType[]","5"),
        ("xxfcbj[]","2"),
    ]
    r=session.post(
        ENDPOINT,
        data=pairs,
        headers={
            "User-Agent":UA,
            "Accept":"application/javascript,application/json,text/plain,*/*",
            "Referer":"https://www.bse.cn/disclosure/announcement.html",
        },
        timeout=(10,30),
        allow_redirects=True,
    )
    meta={
        "page":page,
        "status":r.status_code,
        "resolved_url":r.url,
        "content_type":r.headers.get("content-type"),
        "bytes":len(r.content),
        "sha256":sha256(r.content),
        "same_official_host":same_bse(r.url),
    }
    if r.status_code!=200 or not r.content or not meta["same_official_host"]:
        return None,meta
    obj=parse_jsonp(r.content)
    meta["parse"]="PASS"
    return obj,meta

def scalar_view(row):
    out={}
    for k,v in sorted(row.items()):
        if v is None or isinstance(v,(str,int,float,bool)):
            out[k]=v
    return out

def main()->int:
    s=requests.Session()
    obj0,t0=fetch_page(s,0)
    if obj0 is None:
        report={"schema":"stock-bse-920090-full-row-discovery-v1","status":"NOT VERIFIED","page0_transport":t0}
        OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=True,sort_keys=True))
        return 2

    meta0=page_meta(obj0)
    total_pages=int(meta0.get("totalPages") or 1)
    pages=[]
    matches=[]
    for page in range(total_pages):
        if page==0:
            obj,transport=obj0,t0
        else:
            obj,transport=fetch_page(s,page)
        pages.append({"page":page,"transport":transport,"page_meta":page_meta(obj) if obj is not None else {}})
        if obj is None:
            continue
        for row in walk_records(obj):
            title=str(row.get("disclosureTitle") or "")+str(row.get("disclosurePostTitle") or "")
            pub=str(row.get("publishDate") or "")
            if pub.startswith(TARGET_DATE) and all(tok in title for tok in TARGET_TITLE_TOKENS):
                scalars=scalar_view(row)
                candidate_text=[]
                for k,v in scalars.items():
                    if not isinstance(v,str):
                        continue
                    vv=v.strip()
                    if len(vv)>=20 and ("复牌" in vv or DATE_RE.search(vv)):
                        candidate_text.append({
                            "field":k,
                            "chars":len(vv),
                            "sha256":sha256(vv.encode("utf-8")),
                            "contains_resume":"复牌" in vv,
                            "contains_date":bool(DATE_RE.search(vv)),
                            "preview":vv[:500],
                        })
                matches.append({
                    "row_keys":sorted(row.keys()),
                    "scalar_fields":scalars,
                    "candidate_text_fields":candidate_text,
                    "row_sha256":sha256(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")),
                })

    report={
        "schema":"stock-bse-920090-full-row-discovery-v1",
        "status":"PASS" if matches else "NOT VERIFIED",
        "endpoint":ENDPOINT,
        "query":{
            "date":TARGET_DATE,
            "keyword":"复牌",
            "disclosureType":"5",
            "xxfcbj":"2",
            "needFields_omitted":True,
        },
        "pages":pages,
        "match_count":len(matches),
        "matches":matches,
        "adjudication":{
            "first_party_exact_row_discovered":"PASS" if matches else "NOT VERIFIED",
            "official_text_authority":"SUPPORTED_CANDIDATE" if any(m["candidate_text_fields"] for m in matches) else "NOT VERIFIED",
            "effective_resume_date":"NOT VERIFIED",
            "bse_daily_suspension_pit":"NOT VERIFIED",
            "historical_st_pit":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
        "boundary":"Discovery only. Full-row fields are preserved from the first-party BSE endpoint. No publication date, title date, or candidate text field is promoted to an effective resume date without a separate direct semantic relation.",
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "status":report["status"],
        "match_count":report["match_count"],
        "row_keys":[m["row_keys"] for m in matches],
        "identifier_fields":[{
            k:m["scalar_fields"].get(k)
            for k in ("companyCd","infoId","disclosureCode","dKey","filePath","destFilePath","fileExt","publishDate","pubDate","upDate","upTime")
        } for m in matches],
        "candidate_text_fields":[m["candidate_text_fields"] for m in matches],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if matches else 3

if __name__=="__main__":
    raise SystemExit(main())
