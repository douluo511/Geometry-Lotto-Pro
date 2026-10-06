from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
PROBE=HERE/"stock_bse_marketwide_pagination_probe.py"
CONTRACT=HERE/"stock_bse_company_announcement_contract.py"
OUT=Path("stock_bse_removal_vocabulary.json")
KEYWORDS=[
  "撤销退市风险警示",
  "申请撤销退市风险警示",
  "撤销股票退市风险警示",
  "终止实施退市风险警示",
  "取消退市风险警示",
]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def sha(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def ident(r):
    return (str(r.get("companyCd") or ""),str(r.get("publishDate") or ""),str(r.get("disclosureTitle") or ""),str(r.get("disclosurePostTitle") or ""),str(r.get("destFilePath") or ""))

def main():
    probe=load("probe",PROBE); contract=load("contract",CONTRACT); session=requests.Session()
    mapping,_=contract.fetch_code_mapping(session)
    old_to_new={old:new for new,olds in mapping.items() for old in olds}
    queries=[]; combined={}
    all_transport=True
    for keyword in KEYWORDS:
        obj0,t0=probe.request_page(session,keyword,0)
        s0=probe.summarize(obj0,t0,keyword); pm=s0["page_meta"]
        pages=pm.get("totalPages"); total=pm.get("totalElements")
        ok=(t0.get("status")==200 and t0.get("same_official_host") is True and t0.get("parse")=="PASS" and isinstance(pages,int) and isinstance(total,int) and 0<=pages<=1000 and isinstance(pm.get("number"),int) and pm.get("number")==0)
        rows={}
        receipts=[]
        if ok:
            for p in range(pages):
                if p==0: obj,tr,sm=obj0,t0,s0
                else:
                    obj,tr=probe.request_page(session,keyword,p); sm=probe.summarize(obj,tr,keyword)
                recs=probe.find_records(obj) if obj is not None else []
                pok=(tr.get("status")==200 and tr.get("same_official_host") is True and tr.get("parse")=="PASS" and sm["page_meta"].get("number")==p and sm["page_meta"].get("totalPages")==pages and sm["page_meta"].get("totalElements")==total and sm["page_meta"].get("numberOfElements")==len(recs))
                receipts.append({"page":p,"status":"PASS" if pok else "FAIL","rows":len(recs),"sha256":tr.get("sha256")})
                ok=ok and pok
                for r in recs: rows[ident(r)]=r
            objn,tn=probe.request_page(session,keyword,pages); sn=probe.summarize(objn,tn,keyword)
            n1=(tn.get("status")==200 and tn.get("parse")=="PASS" and sn["record_count"]==0)
            ok=ok and n1 and len(rows)==total
        events=[]
        for k in sorted(rows):
            r=rows[k]
            title=str(r.get("disclosureTitle") or "")+str(r.get("disclosurePostTitle") or "")
            if keyword not in title: continue
            raw=str(r.get("companyCd") or "")
            e={"keyword":keyword,"raw_company_code":raw,"canonical_company_code":old_to_new.get(raw,raw),"companyName":r.get("companyName"),"publishDate":r.get("publishDate"),"title":title,"destFilePath":r.get("destFilePath")}
            events.append(e)
            combined[(e["raw_company_code"],str(e["publishDate"]),e["title"],str(e["destFilePath"]))]=e
        queries.append({"keyword":keyword,"status":"PASS" if ok else "NOT VERIFIED","total_pages":pages,"total_elements":total,"title_event_count":len(events),"canonical_sha256":sha(events),"events":events,"page_receipts":receipts})
        all_transport=all_transport and ok
    combined_rows=[combined[k] for k in sorted(combined)]
    actual=[r for r in combined_rows if not str(r["title"]).startswith("申请") and "申请撤销" not in str(r["title"])]
    report={
      "schema":"stock-bse-removal-vocabulary-v1",
      "queries":queries,
      "combined_unique_events":len(combined_rows),
      "actual_removal_candidate_count":len(actual),
      "actual_removal_candidates":actual,
      "combined_sha256":sha(combined_rows),
      "adjudication":{
        "removal_vocabulary_query_transport":"PASS" if all_transport else "NOT VERIFIED",
        "removal_event_candidates":"SUPPORTED_DIAGNOSTIC" if actual else "NOT VERIFIED",
        "bse_removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Synonym queries can recover candidate removal announcements missed by a narrower keyword. They do not prove vocabulary completeness or effective removal dates."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"query_summary":{x["keyword"]:{"status":x["status"],"total":x["total_elements"],"events":x["title_event_count"]} for x in queries},"combined_unique_events":len(combined_rows),"actual_removal_candidate_count":len(actual),"actual_removal_candidates":actual[:20],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if all_transport else 2
if __name__=="__main__": raise SystemExit(main())
