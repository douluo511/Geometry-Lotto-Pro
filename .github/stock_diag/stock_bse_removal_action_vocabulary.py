from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
CORPUS=HERE/"stock_bse_risk_warning_marketwide_corpus.py"
PROBE=HERE/"stock_bse_marketwide_pagination_probe.py"
OUT=Path("stock_bse_removal_action_vocabulary.json")
ACTIONS=["撤销","解除","取消","终止","恢复","简称","特别处理","摘帽"]

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

def main():
    corpus=load("corpus",CORPUS); probe=load("probe",PROBE)
    rc=corpus.main()
    if rc != 0: raise RuntimeError("risk-warning corpus regeneration failed")
    base=json.loads(Path("stock_bse_risk_warning_marketwide_corpus.json").read_text(encoding="utf-8"))
    risk_codes=sorted({str(x.get("raw_company_code") or "") for x in base.get("combined_events",[]) if x.get("raw_company_code")})
    session=requests.Session()
    queries=[]; candidates={}; all_transport=True
    for action in ACTIONS:
        obj0,t0=probe.request_page(session,action,0); s0=probe.summarize(obj0,t0,action); pm=s0["page_meta"]
        pages=pm.get("totalPages"); total=pm.get("totalElements")
        ok=(t0.get("status")==200 and t0.get("same_official_host") is True and t0.get("parse")=="PASS" and isinstance(pages,int) and isinstance(total,int) and 0<=pages<=1000 and pm.get("number")==0)
        rows={}; receipts=[]
        if ok:
            for p in range(pages):
                if p==0: obj,tr,sm=obj0,t0,s0
                else:
                    obj,tr=probe.request_page(session,action,p); sm=probe.summarize(obj,tr,action)
                recs=probe.find_records(obj) if obj is not None else []
                pok=(tr.get("status")==200 and tr.get("same_official_host") is True and tr.get("parse")=="PASS" and sm["page_meta"].get("number")==p and sm["page_meta"].get("totalPages")==pages and sm["page_meta"].get("totalElements")==total and sm["page_meta"].get("numberOfElements")==len(recs))
                ok=ok and pok
                receipts.append({"page":p,"status":"PASS" if pok else "FAIL","rows":len(recs),"sha256":tr.get("sha256")})
                for r in recs: rows[ident(r)]=r
            objn,tn=probe.request_page(session,action,pages); sn=probe.summarize(objn,tn,action)
            ok=ok and tn.get("status")==200 and tn.get("parse")=="PASS" and sn["record_count"]==0 and len(rows)==total
        matched=[]
        for k in sorted(rows):
            r=rows[k]; code=str(r.get("companyCd") or "")
            if code not in risk_codes: continue
            t=title(r)
            ev={"action_query":action,"companyCd":code,"companyName":r.get("companyName"),"publishDate":r.get("publishDate"),"title":t,"destFilePath":r.get("destFilePath")}
            matched.append(ev); candidates[(code,str(ev["publishDate"]),t,str(ev["destFilePath"]))]=ev
        queries.append({"action":action,"status":"PASS" if ok else "NOT VERIFIED","total_pages":pages,"total_elements":total,"risk_company_matches":len(matched),"matches":matched[:50],"canonical_sha256":sha(matched),"page_receipts":receipts})
        all_transport=all_transport and ok
    rows=[candidates[k] for k in sorted(candidates)]
    transition_terms=("撤销","解除","取消","终止","恢复","摘帽","不再")
    transition=[x for x in rows if any(term in x["title"] for term in transition_terms)]
    report={
      "schema":"stock-bse-removal-action-vocabulary-v1",
      "risk_warning_company_code_count":len(risk_codes),
      "risk_warning_company_codes":risk_codes,
      "queries":queries,
      "candidate_event_count":len(rows),
      "transition_candidate_count":len(transition),
      "transition_candidates":transition,
      "candidate_sha256":sha(rows),
      "adjudication":{
        "broad_action_query_transport":"PASS" if all_transport else "NOT VERIFIED",
        "removal_transition_candidates":"SUPPORTED_DIAGNOSTIC" if transition else "NOT VERIFIED",
        "removal_vocabulary_complete":"NOT VERIFIED",
        "bse_removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Broad action queries are joined only to companies already present in the verified risk-warning title corpus. Candidate titles still require primary-document semantics/effective dates; absence under this finite vocabulary is not proof that removal history is complete."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"risk_warning_company_code_count":len(risk_codes),"query_summary":{q["action"]:{ "status":q["status"],"total":q["total_elements"],"risk_company_matches":q["risk_company_matches"]} for q in queries},"candidate_event_count":len(rows),"transition_candidate_count":len(transition),"transition_candidates":transition[:30],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if all_transport else 2
if __name__=="__main__": raise SystemExit(main())
