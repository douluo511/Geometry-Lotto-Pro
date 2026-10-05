from __future__ import annotations
import hashlib,json,re,time
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
    m=re.match(r"^[A-Za-z0-9_.$]+\\((.*)\\)\\s*;?\\s*$",t,re.S)
    if not m: raise ValueError("not JSON/JSONP")
    return json.loads(m.group(1))

def fetch(session,page):
    params={"isPagination":"true","productId":"","keyWord":KEYWORD,
      "securityType":"0101,120100,020100,020200,120200","reportType2":"","reportType":"ALL",
      "beginDate":BEGIN,"endDate":END,"pageHelp.pageSize":str(PAGE_SIZE),
      "pageHelp.pageNo":str(page),"pageHelp.beginPage":str(max(1,page-2)),
      "pageHelp.cacheSize":"1","pageHelp.endPage":str(page+2),"jsonCallBack":"jsonpCallback"}
    errs=[]
    for attempt in range(1,4):
      try:
        r=session.get(ENDPOINT,params=params,headers={"User-Agent":UA,"Referer":REFERER,"Accept":"application/json,text/javascript,*/*;q=0.01"},timeout=(8,35))
        if r.status_code==429 or r.status_code>=500: raise RuntimeError(f"retryable HTTP {r.status_code}")
        r.raise_for_status()
        obj=parse(r.content.decode(r.encoding or "utf-8",errors="replace"))
        return obj,{"attempt":attempt,"prior_errors":errs,"http_status":r.status_code,
          "payload_sha256":hashlib.sha256(r.content).hexdigest(),"url":r.url}
      except Exception as exc:
        errs.append(f"{type(exc).__name__}: {exc}")
        if attempt==3: raise
        time.sleep(2**(attempt-1))

def rows(obj):
    if isinstance(obj,dict):
      if isinstance(obj.get("result"),list): return obj["result"]
      ph=obj.get("pageHelp")
      if isinstance(ph,dict):
        for k in ("data","result"):
          if isinstance(ph.get(k),list): return ph[k]
    return []

def main():
    s=requests.Session(); obj,first=fetch(s,1); ph=obj.get("pageHelp") or {}
    page_count=int(ph.get("pageCount") or 0); total=int(ph.get("total") or 0)
    first_rows=rows(obj)
    report={"schema":"stock-sse-risk-warning-global-pagination-v1","endpoint":ENDPOINT,
      "query":{"keyword":KEYWORD,"begin":BEGIN,"end":END,"page_size":PAGE_SIZE},
      "first_page":{"fetch":first,"pageHelp":{k:ph.get(k) for k in ("pageNo","pageSize","pageCount","total","beginPage","endPage")},"row_count":len(first_rows)},
      "probes":[],"adjudication":{"global_query_surface":"NOT VERIFIED","pagination_contract":"NOT VERIFIED",
      "market_wide_corpus_completeness":"NOT VERIFIED","shanghai_historical_st_pit":"NOT VERIFIED",
      "full_historical_st_pit":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"}}
    if total<=0 or page_count<=0:
      Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
      print(json.dumps(report,ensure_ascii=True,sort_keys=True)); return 2
    probe_pages=sorted(set([1,2 if page_count>=2 else 1,max(1,page_count//2),page_count]))
    seen=set()
    for p in probe_pages:
      po,meta=(obj,first) if p==1 else fetch(s,p); rr=rows(po); pph=po.get("pageHelp") or {}
      sig=[]
      for row in rr[:10]:
        if isinstance(row,dict):
          sig.append("|".join(str(row.get(k) or "") for k in ("SECURITY_CODE","SSEDATE","URL","TITLE")))
      digest=hashlib.sha256("\\n".join(sig).encode()).hexdigest()
      seen.add(digest)
      report["probes"].append({"page":p,"fetch":meta,"row_count":len(rr),"pageHelp":{k:pph.get(k) for k in ("pageNo","pageSize","pageCount","total")},"sample_signature_sha256":digest,
        "sample_codes":sorted(set(str(x.get("SECURITY_CODE") or "") for x in rr[:20] if isinstance(x,dict)))[:20]})
    global_ok=total>0 and len(first_rows)>0
    pagination_ok=(page_count==1) or (len(seen)>=2 and all(x["row_count"]>0 for x in report["probes"]))
    report["adjudication"]["global_query_surface"]="SUPPORTED" if global_ok else "NOT VERIFIED"
    report["adjudication"]["pagination_contract"]="SUPPORTED" if pagination_ok else "NOT VERIFIED"
    # Deliberately do not promote corpus completeness from sparse probes.
    Path("stock_sse_risk_warning_global_pagination.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if global_ok and pagination_ok else 2
if __name__=="__main__": raise SystemExit(main())
