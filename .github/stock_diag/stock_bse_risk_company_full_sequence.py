from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
CORPUS=HERE/"stock_bse_risk_warning_marketwide_corpus.py"
PROBE=HERE/"stock_bse_marketwide_pagination_probe.py"
CONTRACT=HERE/"stock_bse_company_announcement_contract.py"
OUT=Path("stock_bse_risk_company_full_sequence.json")

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def sha(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def ident(r):
    return (str(r.get("companyCd") or ""),str(r.get("publishDate") or ""),str(r.get("disclosureTitle") or ""),str(r.get("disclosurePostTitle") or ""),str(r.get("destFilePath") or ""))

def title(r):
    return str(r.get("disclosureTitle") or "")+str(r.get("disclosurePostTitle") or "")

def request_company_page(session, probe, code, page):
    base={
      "callback":"stockAiBseRiskCompanyCb",
      "disclosureSubtype":"",
      "page":page,
      "companyCd":code,
      "isNewThree":1,
      "startTime":probe.START,
      "endTime":probe.END,
      "keyword":"",
      "hyType":"",
    }
    pairs=list(base.items())
    pairs += [("disclosureType[]","5"),("xxfcbj[]","2")]
    pairs += [("needFields[]",field) for field in probe.NEED_FIELDS]
    r=session.post(
      probe.ENDPOINT,data=pairs,
      headers={"User-Agent":probe.UA,"Accept":"application/javascript,application/json,text/plain,*/*","Referer":"https://www.bse.cn/disclosure/announcement.html"},
      timeout=(10,30),allow_redirects=True,
    )
    meta={"page_requested":page,"status":r.status_code,"resolved_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content),"sha256":probe.sha256(r.content),"same_official_host":probe.same_bse(r.url)}
    if r.status_code!=200 or not r.content or not meta["same_official_host"]:
      return None,meta
    try:
      obj=probe.parse_jsonp(r.content.decode(r.encoding or "utf-8",errors="strict")); meta["parse"]="PASS"; return obj,meta
    except Exception as exc:
      meta["parse"]="FAIL"; meta["parse_error"]=f"{type(exc).__name__}: {exc}"; return None,meta

def main():
    corpus=load("corpus",CORPUS); probe=load("probe",PROBE); contract=load("contract",CONTRACT)
    if corpus.main()!=0: raise RuntimeError("risk corpus prerequisite failed")
    src=json.loads(Path("stock_bse_risk_warning_marketwide_corpus.json").read_text(encoding="utf-8"))
    raw_codes=sorted({str(x.get("raw_company_code") or "") for x in src.get("combined_events",[]) if x.get("raw_company_code")})
    session=requests.Session()
    mapping,_=contract.fetch_code_mapping(session)
    aliases={}
    for new,olds in mapping.items():
      for old in olds: aliases.setdefault(old,[]).append(new)
      aliases.setdefault(new,[]).extend(olds)
    company_reports=[]; all_transport=True; all_rows=[]
    for code in raw_codes:
      obj0,t0=request_company_page(session,probe,code,0)
      pm=probe.page_meta(obj0) if obj0 is not None else {}
      pages=pm.get("totalPages"); total=pm.get("totalElements")
      ok=(t0.get("status")==200 and t0.get("parse")=="PASS" and isinstance(pages,int) and isinstance(total,int) and 0<=pages<=300 and pm.get("number")==0)
      rows={}; receipts=[]
      if ok:
        for p in range(pages):
          if p==0: obj,tr=obj0,t0
          else: obj,tr=request_company_page(session,probe,code,p)
          recs=probe.find_records(obj) if obj is not None else []
          ppm=probe.page_meta(obj) if obj is not None else {}
          pok=(tr.get("status")==200 and tr.get("parse")=="PASS" and ppm.get("number")==p and ppm.get("totalPages")==pages and ppm.get("totalElements")==total and ppm.get("numberOfElements")==len(recs))
          ok=ok and pok
          receipts.append({"page":p,"status":"PASS" if pok else "FAIL","rows":len(recs),"sha256":tr.get("sha256")})
          for r in recs:
            if str(r.get("companyCd") or "")==code: rows[ident(r)]=r
        objn,tn=request_company_page(session,probe,code,pages)
        sn=probe.find_records(objn) if objn is not None else []
        ok=ok and tn.get("status")==200 and tn.get("parse")=="PASS" and len(sn)==0
      seq=[]
      for k in sorted(rows):
        r=rows[k]; t=title(r)
        seq.append({"companyCd":code,"companyName":r.get("companyName"),"publishDate":r.get("publishDate"),"title":t,"destFilePath":r.get("destFilePath")})
      focus=[x for x in seq if any(tok in x["title"] for tok in ("风险警示","*ST","ST","证券简称","股票简称","撤销","解除","取消","终止实施","继续实施","叠加实施"))]
      company_reports.append({"companyCd":code,"aliases":sorted(set(aliases.get(code,[]))),"status":"PASS" if ok else "NOT VERIFIED","total_pages":pages,"server_total_elements":total,"exact_company_rows":len(seq),"focus_rows":focus,"focus_count":len(focus),"sequence_sha256":sha(seq),"page_receipts":receipts})
      all_transport=all_transport and ok
      all_rows.extend(focus)
    report={
      "schema":"stock-bse-risk-company-full-sequence-v1",
      "risk_company_count":len(raw_codes),
      "risk_company_codes":raw_codes,
      "company_reports":company_reports,
      "focus_event_count":len(all_rows),
      "focus_event_sha256":sha(all_rows),
      "adjudication":{
        "risk_company_full_sequence_transport":"PASS" if all_transport else "NOT VERIFIED",
        "company_scoped_transition_inventory":"SUPPORTED_DIAGNOSTIC" if all_rows else "NOT VERIFIED",
        "removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Company-scoped complete announcement sequences avoid broad market keyword noise. Focus rows are only transition candidates; titles/publication dates are not effective dates and do not prove removal-history completeness or daily PIT."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"risk_company_count":len(raw_codes),"company_summary":{x["companyCd"]:{ "status":x["status"],"rows":x["exact_company_rows"],"focus":x["focus_count"]} for x in company_reports},"focus_event_count":len(all_rows),"focus_sample":all_rows[:50],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if all_transport else 2
if __name__=="__main__": raise SystemExit(main())
