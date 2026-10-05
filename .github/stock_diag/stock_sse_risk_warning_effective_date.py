from __future__ import annotations

import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
PRODUCT = "688496"
BEGIN = "2026-01-01"
END = "2026-10-06"
KEYWORD = "风险警示"
STATIC_BASE = "https://static.sse.com.cn"
STATIC_HTTP_BASE = "http://static.sse.com.cn"
WWW_BASE = "https://www.sse.com.cn"
BIG5_BASE = "https://big5.sse.com.cn/site/cht/www.sse.com.cn"

DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
TERM_RE = re.compile(r"(实施退市风险警示|实施其他风险警示|撤销退市风险警示|撤销其他风险警示|风险警示|证券简称|股票简称)")
TRANSITION_RE = re.compile(r"(实施退市风险警示|实施其他风险警示|撤销退市风险警示|撤销其他风险警示)")

def fetch(session,url,*,params=None,attempts=3,referer=REFERER):
    errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=session.get(
                url,params=params,
                headers={"User-Agent":UA,"Referer":referer,"Accept":"*/*"},
                timeout=(8,35),allow_redirects=True,
            )
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r,{
                "attempt":attempt,"prior_errors":errors,"http_status":r.status_code,
                "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                "content_type":r.headers.get("Content-Type"),"url":r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))

def parse_jsonp(text):
    t=text.strip()
    try:
        return json.loads(t)
    except Exception:
        m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",t,flags=re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def rows_from(obj):
    if isinstance(obj,dict):
        if isinstance(obj.get("result"),list):
            return obj["result"]
        ph=obj.get("pageHelp")
        if isinstance(ph,dict) and isinstance(ph.get("data"),list):
            return ph["data"]
    return []

def row_title(row):
    for k in ("TITLE","BULLETIN_TITLE","bulletinTitle","title"):
        if row.get(k):
            return str(row[k])
    return ""

def row_url(row):
    for k in ("URL","url","bulletinUrl","BULLETIN_URL"):
        if row.get(k):
            return str(row[k])
    return ""

def pdf_candidates(path):
    if path.startswith("http://") or path.startswith("https://"):
        return [path]
    return [
        urljoin(STATIC_BASE,path),
        urljoin(STATIC_HTTP_BASE,path),
        urljoin(WWW_BASE,path),
        urljoin(BIG5_BASE + "/", path.lstrip("/")),
    ]


def html_diagnostic(raw, content_type, final_url):
    text=raw.decode("utf-8",errors="replace")
    compact=" ".join(text[:6000].split())
    urls=sorted(set(re.findall(r"https?://[^\\s\"'<>]+",text,re.I)))[:20]
    hrefs=sorted(set(re.findall(r"(?:href|src)=[\"']([^\"']+)",text,re.I)))[:30]
    return {
        "content_type":content_type,
        "final_url":final_url,
        "bytes":len(raw),
        "prefix":compact[:1800],
        "absolute_urls":urls,
        "href_src_candidates":hrefs,
    }

def extract_pdf_text(raw):
    reader=PdfReader(io.BytesIO(raw))
    pages=[]
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages),len(reader.pages)

def snippets(text,term="风险警示",radius=240):
    out=[]
    for m in re.finditer(term,text):
        a=max(0,m.start()-radius); b=min(len(text),m.end()+radius)
        s=" ".join(text[a:b].split())
        if s not in out:
            out.append(s[:1000])
        if len(out)>=10:
            break
    return out

def date_strings_near_transition(text):
    matches=[]
    for m in TRANSITION_RE.finditer(text):
        a=max(0,m.start()-220); b=min(len(text),m.end()+220)
        segment=text[a:b]
        dates=[]
        for d in DATE_RE.finditer(segment):
            y,mo,day=map(int,d.groups())
            dates.append(f"{y:04d}-{mo:02d}-{day:02d}")
        matches.append({
            "transition":m.group(1),
            "dates":sorted(set(dates)),
            "snippet":" ".join(segment.split())[:1200],
        })
    return matches

def main():
    s=requests.Session()
    params={
        "isPagination":"true","productId":PRODUCT,"keyWord":KEYWORD,
        "securityType":"0101,120100,020100,020200,120200",
        "reportType2":"","reportType":"ALL","beginDate":BEGIN,"endDate":END,
        "pageHelp.pageSize":"100","pageHelp.pageNo":"1","pageHelp.beginPage":"1",
        "pageHelp.cacheSize":"1","pageHelp.endPage":"5","jsonCallBack":"jsonpCallback",
    }
    r,query_meta=fetch(s,ENDPOINT,params=params)
    obj=parse_jsonp(r.content.decode(r.encoding or "utf-8",errors="replace"))
    rows=rows_from(obj)
    selected=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict):
            continue
        path=row_url(row)
        if not path or path in seen:
            continue
        seen.add(path)
        selected.append({
            "security_code":str(row.get("SECURITY_CODE") or row.get("securityCode") or ""),
            "security_name":str(row.get("SECURITY_NAME") or row.get("securityName") or ""),
            "sse_date":str(row.get("SSEDATE") or row.get("SSE_DATE") or row.get("publishDate") or ""),
            "title":row_title(row),
            "url":path,
        })

    pdfs=[]
    downloadable=0
    extractable=0
    transition_docs=0
    for item in selected:
        attempts=[]
        raw=None
        meta=None
        chosen=None
        for url in pdf_candidates(item["url"]):
            try:
                rr,mm=fetch(s,url,attempts=2,referer=REFERER)
                attempts.append({"url":url,"status":"PASS","meta":mm})
                if rr.content.startswith(b"%PDF"):
                    raw=rr.content; meta=mm; chosen=url
                    break
                attempts[-1]["status"]="NOT_PDF"
                attempts[-1]["html_diagnostic"]=html_diagnostic(
                    rr.content,rr.headers.get("Content-Type"),rr.url
                )
            except Exception as exc:
                attempts.append({"url":url,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"})
        record={**item,"download_attempts":attempts}
        if raw is None:
            record["status"]="DOWNLOAD_NOT_VERIFIED"
            pdfs.append(record)
            continue
        downloadable+=1
        record["pdf_url"]=chosen
        record["pdf_sha256"]=hashlib.sha256(raw).hexdigest()
        record["pdf_bytes"]=len(raw)
        try:
            text,pages=extract_pdf_text(raw)
        except Exception as exc:
            record["status"]="TEXT_NOT_VERIFIED"
            record["extract_error"]=f"{type(exc).__name__}: {exc}"
            pdfs.append(record)
            continue
        record["pages"]=pages
        record["text_sha256"]=hashlib.sha256(text.encode("utf-8")).hexdigest()
        record["text_chars"]=len(text)
        record["risk_warning_snippets"]=snippets(text)
        record["transition_evidence"]=date_strings_near_transition(text)
        record["has_risk_warning_term"]=bool(TERM_RE.search(text))
        record["has_explicit_transition"]=bool(record["transition_evidence"])
        if record["has_risk_warning_term"]:
            extractable+=1
        if record["has_explicit_transition"]:
            transition_docs+=1
        record["status"]="PASS" if record["has_risk_warning_term"] else "TEXT_NO_RISK_TERM"
        pdfs.append(record)

    source_supported=(len(selected)>=2 and downloadable==len(selected) and extractable==len(selected))
    effective_date_semantics_supported=(transition_docs>=2)
    report={
        "schema":"stock-sse-risk-warning-effective-date-v1",
        "product":PRODUCT,
        "window":{"begin":BEGIN,"end":END},
        "query":{"fetch":query_meta,"row_count":len(rows),"unique_pdf_count":len(selected)},
        "pdfs":pdfs,
        "summary":{
            "selected_pdf_count":len(selected),
            "downloadable_pdf_count":downloadable,
            "risk_term_extractable_pdf_count":extractable,
            "explicit_transition_pdf_count":transition_docs,
        },
        "adjudication":{
            "official_risk_warning_pdf_surface":"SUPPORTED" if source_supported else "NOT VERIFIED",
            "risk_warning_effective_date_semantics":"SUPPORTED_SAMPLE" if effective_date_semantics_supported else "NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_risk_warning_effective_date.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if source_supported and effective_date_semantics_supported else 2

if __name__=="__main__":
    raise SystemExit(main())
