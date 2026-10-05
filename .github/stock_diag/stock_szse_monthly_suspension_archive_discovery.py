from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

OUT=Path("stock_szse_monthly_suspension_archive_discovery.json")
INDEX_ROOTS=[
    "https://www.szse.cn/certificate/secondb/GEMmsb/",
    "https://www.szse.cn/www/certificate/secondb/GEMmsb/",
    "https://www.szse.cn/certificate/maind/monthlyReport/",
    "https://www.szse.cn/www/certificate/maind/monthlyReport/",
]
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36"
MONTH_LINK_RE=re.compile(r'''(?:href|src)=["']([^"']*(?:docs\.static\.szse\.cn)?/www/market/periodical/month/[^"']+\.html[^"']*)["']''',re.I)
ABS_MONTH_RE=re.compile(r'''https://docs\.static\.szse\.cn/www/market/periodical/month/W\d+\.html''',re.I)
MONTH_TEXT_RE=re.compile(r"(20\d{2})[.年/-](0?[1-9]|1[0-2])(?:月)?")
TABLE_MARKERS=("证券停牌情况","SUSPENDED","停牌时间","复牌时间")
SCRIPT_SRC_RE=re.compile(r'''<script[^>]+src=["']([^"']+)["']''',re.I)
API_TOKEN_RE=re.compile(r'''(?i)(?:https?:)?//[^"'\s<>]+|/api/[^"'\s<>]+|CATALOGID[^"'\s<>]{0,120}|catalogId[^"'\s<>]{0,120}|componentId[^"'\s<>]{0,120}|monthlyReport[^"'\s<>]{0,160}|GEMmsb[^"'\s<>]{0,160}''')

def official(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="szse.cn" or host.endswith(".szse.cn")

def get(session,url,attempts=3):
    errs=[]
    for n in range(1,attempts+1):
        try:
            r=session.get(url,headers={"User-Agent":UA,"Referer":"https://www.szse.cn/","Accept":"text/html,application/xhtml+xml,*/*;q=0.8"},timeout=(8,30),allow_redirects=True)
            if r.status_code in {403,429} or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not official(r.url):
                raise RuntimeError(f"redirected off official host: {r.url}")
            return r,errs
        except Exception as exc:
            errs.append(f"{type(exc).__name__}: {exc}")
            if n==attempts:
                return None,errs
            time.sleep(1.5*n)
    return None,errs

def canonical_sha(rows):
    blob=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(blob).hexdigest()

def main():
    session=requests.Session()
    index_receipts=[]
    links={}
    script_urls=set()
    api_contexts=[]
    for root in INDEX_ROOTS:
        for page in range(0,8):
            suffix="index.html" if page==0 else f"index_{page}.html"
            url=urljoin(root,suffix)
            r,errors=get(session,url)
            rec={"url":url,"errors":errors,"status":"NOT VERIFIED"}
            if r is None:
                index_receipts.append(rec)
                continue
            text=r.text
            rec.update({"status":"PASS","http_status":r.status_code,"final_url":r.url,"bytes":len(r.content),"sha256":hashlib.sha256(r.content).hexdigest()})
            found=set(ABS_MONTH_RE.findall(text))
            for rel in MONTH_LINK_RE.findall(text):
                u=urljoin(r.url,rel)
                if official(u) and "/www/market/periodical/month/" in u:
                    found.add(u.split("#",1)[0].split("?",1)[0])
            scripts=[]
            for rel in SCRIPT_SRC_RE.findall(text):
                su=urljoin(r.url,rel)
                if official(su):
                    scripts.append(su)
                    script_urls.add(su)
            tokens=[]
            for m in API_TOKEN_RE.finditer(text):
                token=m.group(0)[:300]
                if token not in tokens:
                    tokens.append(token)
            rec["month_link_count"]=len(found)
            rec["script_urls"]=scripts
            rec["api_tokens"]=tokens[:80]
            api_contexts.extend({"source":url,"token":t} for t in tokens[:80])
            index_receipts.append(rec)
            for u in found:
                links[u]={"discovered_from":url}

    script_receipts=[]
    for su in sorted(script_urls):
        r,errors=get(session,su)
        rec={"url":su,"errors":errors,"status":"NOT VERIFIED"}
        if r is None:
            script_receipts.append(rec)
            continue
        text=r.text
        tokens=[]
        for m in API_TOKEN_RE.finditer(text):
            token=m.group(0)[:300]
            if token not in tokens:
                tokens.append(token)
        rec.update({"status":"PASS","http_status":r.status_code,"bytes":len(r.content),"sha256":hashlib.sha256(r.content).hexdigest(),"api_tokens":tokens[:120]})
        script_receipts.append(rec)
        api_contexts.extend({"source":su,"token":t} for t in tokens[:120])

    pages=[]
    month_map={}
    for url in sorted(links):
        r,errors=get(session,url)
        rec={"url":url,"errors":errors,"status":"NOT VERIFIED"}
        if r is None:
            pages.append(rec); continue
        text=r.text
        compact=re.sub(r"\s+","",text)
        months=sorted({f"{int(y):04d}-{int(m):02d}" for y,m in MONTH_TEXT_RE.findall(text)})
        markers={m:(m.replace(" ","") in compact) for m in TABLE_MARKERS}
        has_table=("证券停牌情况" in compact and "停牌时间" in compact and "复牌时间" in compact) or ("SUSPENDED" in text.upper() and "Resume" in text)
        rec.update({
            "status":"PASS","http_status":r.status_code,"final_url":r.url,"bytes":len(r.content),
            "sha256":hashlib.sha256(r.content).hexdigest(),"months":months,
            "suspension_table_detected":has_table,"markers":markers,
        })
        pages.append(rec)
        if has_table:
            target=[m for m in months if "2021-10" <= m <= "2026-09"]
            for month in target:
                month_map.setdefault(month,[]).append(url)

    expected=[]
    y,m=2021,10
    while (y,m) <= (2026,9):
        expected.append(f"{y:04d}-{m:02d}")
        m+=1
        if m==13:
            y+=1;m=1
    covered=sorted(set(month_map))
    missing=[m for m in expected if m not in month_map]
    report={
      "schema":"stock-szse-monthly-suspension-archive-discovery-v1",
      "index_receipts":index_receipts,
      "discovered_month_page_count":len(links),
      "script_receipts":script_receipts,
      "api_contexts":api_contexts[:500],
      "month_pages":pages,
      "frozen_window":{"start":"2021-10","end":"2026-09","expected_months":len(expected),"covered_months":len(covered),"coverage":len(covered)/len(expected),"missing_months":missing,"month_map":month_map},
      "canonical_sha256":canonical_sha(pages),
      "adjudication":{
        "index_shell_fetch":"PASS" if any(x.get("status")=="PASS" for x in index_receipts) else "NOT VERIFIED",
        "official_szse_monthly_suspension_archive_surface":"SUPPORTED" if any(x.get("suspension_table_detected") for x in pages) else "NOT VERIFIED",
        "frozen_monthly_archive_coverage":"SUPPORTED" if len(covered)==len(expected) else "PARTIAL_SUPPORTED",
        "shenzhen_historical_suspension_state":"NOT VERIFIED",
        "shenzhen_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"This first inspects official SZSE monthly-report HTML and official scripts for the real data contract, then measures any discovered official static month pages. Dynamic-shell HTML with zero direct links is a discovery result, not evidence that the monthly archive is absent. No daily-state promotion is allowed."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"discovered_month_page_count":len(links),"frozen_window":report["frozen_window"],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if any(x.get("status")=="PASS" for x in index_receipts) else 2

if __name__=="__main__":
    raise SystemExit(main())
