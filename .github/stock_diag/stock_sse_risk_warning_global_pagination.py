from __future__ import annotations
import hashlib,json,math,re,time
from pathlib import Path
import requests

ENDPOINT="https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER="https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
BEGIN="1990-01-01"; END="2026-10-06"; KEYWORD="风险警示"; PAGE_SIZE=100

def parse(text):
    t=text.strip()
    try:return json.loads(t)
    except Exception:pass
    m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",t,re.S)
    if not m: raise ValueError("not JSON/JSONP")
    return json.loads(m.group(1))

def fetch(session,page):
    params={"isPagination":"true","productId":"","keyWord":KEYWORD,
      "securityType":"0101,120100,020100,020200,120200","reportType2":"","reportType":"ALL",
      "beginDate":BEGIN,"endDate":END,"pageHelp.pageSize":str(PAGE_SIZE),
      "pageHelp.pageNo":str(page),"pageHelp.beginPage":str(page),
      "pageHelp.cacheSize":"1","pageHelp.endPage":str(page),"jsonCallBack":"jsonpCallback"}
    errs=[]
    for attempt in range(1,4):
      try:
        r=session.get(ENDPOINT,params=params,headers={"User-Agent":UA,"Referer":REFERER,"Accept":"application/json,text/javascript,*/*;q=0.01"},timeout=(8,35))
        if r.status_code==429 or r.status_code>=500: raise RuntimeError(f"retryable HTTP {r.status_code}")
        r.raise_for_status()
      except Exception as exc:
        err=f"{type(exc).__name__}: {exc}"
        errs.append(err)
        if attempt==3:
          return None,{"attempt":attempt,"prior_errors":list(errs),"transport_error":err,
            "url":getattr(locals().get("r",None),"url",ENDPOINT)}
        time.sleep(2**(attempt-1)); continue

      decoded=r.content.decode(r.encoding or "utf-8",errors="replace")
      meta={"attempt":attempt,"prior_errors":list(errs),"http_status":r.status_code,
        "payload_sha256":hashlib.sha256(r.content).hexdigest(),"url":r.url,
        "content_type":r.headers.get("content-type"),"encoding":r.encoding,
        "body_prefix":decoded[:512]}
      try:
        obj=parse(decoded)
      except Exception as exc:
        err=f"{type(exc).__name__}: {exc}"
        errs.append(err); meta["parse_error"]=err; meta["prior_errors"]=list(errs)
        if attempt==3: return None,meta
        time.sleep(2**(attempt-1)); continue
      return obj,meta

def rows(obj):
    if isinstance(obj,dict):
      if isinstance(obj.get("result"),list): return obj["result"]
      ph=obj.get("pageHelp")
      if isinstance(ph,dict):
        for k in ("data","result"):
          if isinstance(ph.get(k),list): return ph[k]
    return []

def field(row,*keys):
    for k in keys:
      v=row.get(k) if isinstance(row,dict) else None
      if v not in (None,""): return str(v).strip()
    return ""

def identity(row):
    return (
      field(row,"SECURITY_CODE","securityCode"),
      field(row,"SSEDATE","SSE_DATE","publishDate","END_DATE"),
      field(row,"URL","url"),
      field(row,"BULLETIN_TITLE","bulletinTitle","TITLE","title"),
    )

def main():
    s=requests.Session(); obj,first=fetch(s,1)
    ph=(obj.get("pageHelp") or {}) if isinstance(obj,dict) else {}
    page_count=int(ph.get("pageCount") or 0); total=int(ph.get("total") or 0)
    first_rows=rows(obj)
    report={"schema":"stock-sse-risk-warning-global-pagination-v1","endpoint":ENDPOINT,
      "query":{"keyword":KEYWORD,"begin":BEGIN,"end":END,"page_size":PAGE_SIZE},
      "first_page":{"fetch":first,"pageHelp":{k:ph.get(k) for k in ("pageNo","pageSize","pageCount","total","beginPage","endPage")},"row_count":len(first_rows)},
      "probes":[],"adjudication":{"global_query_surface":"NOT VERIFIED","pagination_contract":"NOT VERIFIED",
      "market_wide_corpus_completeness":"NOT VERIFIED","shanghai_historical_st_pit":"NOT VERIFIED",
      "full_historical_st_pit":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"}}
    if obj is None:
      Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
      print(json.dumps(report,ensure_ascii=True,sort_keys=True)); return 2
    if total<=0 or page_count<=0:
      Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
      print(json.dumps(report,ensure_ascii=True,sort_keys=True)); return 2
    expected_page_count=math.ceil(total/PAGE_SIZE) if total else 0
    expected_last_rows=total-PAGE_SIZE*(page_count-1) if page_count else 0
    if expected_last_rows==0 and total: expected_last_rows=PAGE_SIZE
    probe_pages=sorted(set([1,2 if page_count>=2 else 1,max(1,page_count//2),page_count,page_count+1]))
    identity_sets={}
    for p in probe_pages:
      po,meta=(obj,first) if p==1 else fetch(s,p)
      if po is None:
        report["probes"].append({"page":p,"fetch":meta,"row_count":0,"pageHelp":{},"sample_signature_sha256":None,"sample_codes":[]})
        Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=True,sort_keys=True)); return 2
      rr=rows(po); pph=po.get("pageHelp") or {}
      ids=[identity(row) for row in rr if isinstance(row,dict)]
      ids=[x for x in ids if any(x)]
      identity_sets[p]=set(ids)
      digest=hashlib.sha256(
        json.dumps(sorted(ids),ensure_ascii=False,separators=(",",":")).encode("utf-8")
      ).hexdigest()
      report["probes"].append({"page":p,"fetch":meta,"row_count":len(rr),"unique_identity_count":len(set(ids)),
        "pageHelp":{k:pph.get(k) for k in ("pageNo","pageSize","pageCount","total","beginPage","endPage")},"sample_signature_sha256":digest,
        "sample_codes":sorted(set(field(x,"SECURITY_CODE","securityCode") for x in rr[:20] if isinstance(x,dict)))[:20]})

    valid_pages=[p for p in probe_pages if p<=page_count]
    overlaps={}
    for i,left in enumerate(valid_pages):
      for right in valid_pages[i+1:]:
        overlaps[f"{left}-{right}"]=len(identity_sets[left] & identity_sets[right])
    by_page={x["page"]:x for x in report["probes"]}
    checks={
      "page_count_matches_total": page_count==expected_page_count,
      "metadata_denominator_consistent": all(
        int(by_page[p]["pageHelp"].get("total") or -1)==total and
        int(by_page[p]["pageHelp"].get("pageCount") or -1)==page_count
        for p in valid_pages
      ),
      "page_echo_matches": all(int(by_page[p]["pageHelp"].get("pageNo") or -1)==p for p in valid_pages),
      "nonfinal_probe_pages_full": all(by_page[p]["row_count"]==PAGE_SIZE for p in valid_pages if p<page_count),
      "last_page_expected_remainder": by_page[page_count]["row_count"]==expected_last_rows,
      "page_n_plus_1_empty": by_page[page_count+1]["row_count"]==0,
      "within_page_unique": all(by_page[p]["row_count"]==by_page[p]["unique_identity_count"] for p in valid_pages),
      "cross_probe_pages_disjoint": all(v==0 for v in overlaps.values()),
    }
    report["pagination_validation"]={
      "mode":"exact_navigation_window",
      "expected_page_count":expected_page_count,
      "expected_last_rows":expected_last_rows,
      "checks":checks,
      "overlaps":overlaps,
    }
    global_ok=total>0 and len(first_rows)>0
    pagination_ok=global_ok and all(checks.values())
    report["adjudication"]["global_query_surface"]="SUPPORTED" if global_ok else "NOT VERIFIED"
    report["adjudication"]["pagination_contract"]="SUPPORTED" if pagination_ok else "NOT VERIFIED"
    # Deliberately do not promote corpus completeness from sparse probes.
    Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if global_ok and pagination_ok else 2
if __name__=="__main__": raise SystemExit(main())
