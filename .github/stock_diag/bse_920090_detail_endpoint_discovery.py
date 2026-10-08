from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

PAGE="https://www.bse.cn/disclosure/announcement.html"
OUT=Path("stock_bse_920090_detail_endpoint_discovery.json")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE detail endpoint discovery"
IDENTIFIERS=("infoId","disclosureCode","dKey","filePath")

def sha256(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def same_bse(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="bse.cn" or host.endswith(".bse.cn")

def get(session,url):
    r=session.get(
        url,
        headers={
            "User-Agent":UA,
            "Accept":"text/html,application/javascript,text/javascript,*/*;q=0.8",
            "Referer":PAGE,
        },
        timeout=(10,30),
        allow_redirects=True,
    )
    meta={
        "status":r.status_code,
        "resolved_url":r.url,
        "content_type":r.headers.get("content-type"),
        "bytes":len(r.content),
        "sha256":sha256(r.content),
        "same_official_host":same_bse(r.url),
    }
    if r.status_code!=200 or not r.content or not meta["same_official_host"]:
        raise RuntimeError(f"official fetch failed: {url}: {meta}")
    return r,meta

def main()->int:
    s=requests.Session()
    page,page_meta=get(s,PAGE)
    html=page.content.decode(page.encoding or "utf-8",errors="replace")
    script_urls=[]
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',html,flags=re.I):
        u=urljoin(page.url,src)
        if same_bse(u):
            script_urls.append(u)
    script_urls=sorted(set(script_urls))

    contexts=[]
    candidate_urls=set()
    scripts=[]
    for url in script_urls:
        try:
            r,meta=get(s,url)
        except Exception as exc:
            scripts.append({"url":url,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"})
            continue
        text=r.content.decode(r.encoding or "utf-8",errors="replace")
        hits=0
        for ident in IDENTIFIERS:
            for m in re.finditer(re.escape(ident),text):
                hits+=1
                lo=max(0,m.start()-260)
                hi=min(len(text),m.end()+420)
                frag=" ".join(text[lo:hi].split())
                urls=[]
                for raw in re.findall(r'(?:(?:https?:)?//[^"\'\s]+|/[A-Za-z0-9_./?=&%{}$:-]{4,})',frag):
                    full=urljoin(r.url,raw)
                    if same_bse(full):
                        candidate_urls.add(full)
                        urls.append(full)
                contexts.append({
                    "identifier":ident,
                    "script_url":url,
                    "script_sha256":meta["sha256"],
                    "context_sha256":sha256(frag.encode("utf-8")),
                    "context":frag[:900],
                    "candidate_urls":sorted(set(urls)),
                })
        scripts.append({**meta,"url":url,"identifier_hit_count":hits})

    report={
        "schema":"stock-bse-920090-detail-endpoint-discovery-v1",
        "status":"PASS" if contexts else "NOT VERIFIED",
        "page":{**page_meta,"url":PAGE},
        "identifiers":list(IDENTIFIERS),
        "script_count":len(script_urls),
        "scripts":scripts,
        "identifier_context_count":len(contexts),
        "identifier_contexts":contexts,
        "candidate_urls":sorted(candidate_urls),
        "adjudication":{
            "first_party_identifier_usage":"PASS" if contexts else "NOT VERIFIED",
            "detail_endpoint_contract":"CANDIDATE_ONLY" if candidate_urls else "NOT VERIFIED",
            "effective_resume_date":"NOT VERIFIED",
            "bse_daily_suspension_pit":"NOT VERIFIED",
            "historical_st_pit":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
        "boundary":"Discovery only. URL strings and identifier contexts from first-party BSE JavaScript are candidates, not validated detail contracts. No date is promoted.",
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "status":report["status"],
        "identifier_context_count":report["identifier_context_count"],
        "candidate_urls":report["candidate_urls"],
        "contexts":report["identifier_contexts"][:24],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if contexts else 3

if __name__=="__main__":
    raise SystemExit(main())
