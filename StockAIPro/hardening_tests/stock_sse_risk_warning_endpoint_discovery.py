from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PAGE_GROUPS = [
    [
        "https://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=603070",
        "https://big5.sse.com.cn/site/cht/www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=603070",
    ],
    [
        "https://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=603388",
        "https://big5.sse.com.cn/site/cht/www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=603388",
    ],
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
TOKENS = (
    "query.sse.com.cn", "commonSoaQuery", "sqlId", "announcement",
    "bulletin", "risk", "风险警示", "公告", "category", "COMPANY_CODE",
)


def fetch(session, url, attempts=3):
    errors=[]
    for attempt in range(1, attempts+1):
        try:
            r=session.get(
                url,
                headers={"User-Agent":UA,"Referer":"https://www.sse.com.cn/"},
                timeout=(8,30),
                allow_redirects=True,
            )
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r, {"attempt":attempt,"prior_errors":errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))


def bounded_matches(text, url):
    out=[]
    lines=text.splitlines()
    low=[x.lower() for x in TOKENS]
    for i,line in enumerate(lines):
        ll=line.lower()
        if any(t.lower() in ll for t in low):
            start=max(0,i-2); end=min(len(lines),i+3)
            snippet=" ".join(x.strip() for x in lines[start:end] if x.strip())
            out.append({"line":i+1,"snippet":snippet[:2500]})
            if len(out)>=80:
                break
    return {"url":url,"matches":out}


def main():
    s=requests.Session()
    pages=[]
    script_urls=set()
    for candidates in PAGE_GROUPS:
        failures=[]
        chosen=None
        for url in candidates:
            try:
                r,meta=fetch(s,url,attempts=2)
                chosen=(url,r,meta)
                break
            except Exception as exc:
                failures.append({"url":url,"error":f"{type(exc).__name__}: {exc}"})
        if chosen is None:
            raise RuntimeError(f"all official SSE company-page variants failed: {failures}")
        url,r,meta=chosen
        text=r.content.decode(r.encoding or "utf-8",errors="replace")
        soup=BeautifulSoup(text,"html.parser")
        scripts=[]
        for tag in soup.find_all("script"):
            src=tag.get("src")
            if not src:
                continue
            full=urljoin(url,src)
            if "sse.com.cn" in full:
                scripts.append(full)
                script_urls.add(full)
        pages.append({
            "url":url,
            "candidate_failures":failures,
            "status":r.status_code,
            "sha256":hashlib.sha256(r.content).hexdigest(),
            "fetch_attempt":meta["attempt"],
            "script_count":len(scripts),
            "scripts":scripts,
            "inline_matches":bounded_matches(text,url)["matches"],
            "has_risk_warning_label":"风险警示" in text or "風險警示" in text,
            "has_company_announcements_label":"公司公告" in text or "公司公告" in text,
        })

    scripts=[]
    endpoint_candidates=[]
    sql_ids=set()
    for url in sorted(script_urls):
        try:
            r,meta=fetch(s,url,attempts=2)
            text=r.content.decode(r.encoding or "utf-8",errors="replace")
            matches=bounded_matches(text,url)["matches"]
            if not matches:
                continue
            for m in re.finditer(r"sqlId[^A-Za-z0-9_]{0,20}([A-Za-z0-9_\-]+)",text,re.I):
                sql_ids.add(m.group(1))
            for pat in (
                r"https?://query\.sse\.com\.cn/[A-Za-z0-9_./?=&%-]+",
                r"commonSoaQuery\.do",
                r"commonQuery\.do",
            ):
                for m in re.finditer(pat,text,re.I):
                    endpoint_candidates.append(m.group(0))
            scripts.append({
                "url":url,
                "status":r.status_code,
                "sha256":hashlib.sha256(r.content).hexdigest(),
                "fetch_attempt":meta["attempt"],
                "matches":matches,
            })
        except Exception as exc:
            scripts.append({"url":url,"error":f"{type(exc).__name__}: {exc}","matches":[]})

    candidates=sorted(set(endpoint_candidates))
    relevant_sql=sorted(
        x for x in sql_ids
        if any(k in x.upper() for k in ("ANN","BULLET","NOTICE","DISC","COMP","GP","GG","XXPL"))
    )
    discovery_supported=bool(candidates or relevant_sql)
    report={
        "schema":"stock-sse-risk-warning-endpoint-discovery-v1",
        "authoritative_product_head":"43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
        "pages":pages,
        "scripts_scanned":scripts,
        "endpoint_candidates":candidates,
        "sql_ids":sorted(sql_ids),
        "relevant_sql_ids":relevant_sql,
        "adjudication":{
            "company_page_risk_warning_surface":"SUPPORTED" if any(x["has_risk_warning_label"] for x in pages) else "NOT VERIFIED",
            "company_announcement_surface":"SUPPORTED" if all(x["has_company_announcements_label"] for x in pages) else "NOT VERIFIED",
            "machine_query_contract_discovery":"SUPPORTED" if discovery_supported else "NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_risk_warning_endpoint_discovery.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "scripts_scanned":len(scripts),
        "endpoint_candidates":candidates,
        "relevant_sql_ids":relevant_sql,
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if discovery_supported else 2


if __name__=="__main__":
    raise SystemExit(main())
