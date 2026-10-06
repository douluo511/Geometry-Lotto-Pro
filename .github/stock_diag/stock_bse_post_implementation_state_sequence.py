from __future__ import annotations
import hashlib, importlib.util, json
from collections import defaultdict
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
CONTRACT=HERE/"stock_bse_company_announcement_contract.py"
OUT=Path("stock_bse_post_implementation_state_sequence.json")
END="2026-09-30"
INITIAL=[
 {"canonical_code":"920305","effective_date":"2025-05-06","title":"云创数据 initial"},
 {"canonical_code":"920680","effective_date":"2025-05-06","title":"广道数字 initial"},
 {"canonical_code":"920023","effective_date":"2026-04-30","title":"田野股份 initial"},
 {"canonical_code":"920090","effective_date":"2026-04-24","title":"同辉信息 initial"},
 {"canonical_code":"920575","effective_date":"2026-05-06","title":"康乐卫士 initial"},
]

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

def state(name):
    n="".join(str(name or "").split()).upper()
    if not n: return "UNKNOWN"
    if "*ST" in n or n.startswith("ST"): return "ST_WARNING"
    if n.endswith("退") or "退市" in n: return "DELISTING_NAME"
    return "NON_ST_NAME"

def query_all(contract,session,query_code,start,end,dtypes):
    receipts=[]; rows={}; all_pass=True
    for dtype in dtypes:
        base={
          "callback":"stockAiStateCb","disclosureSubtype":"","companyCd":query_code,
          "isNewThree":1,"startTime":start,"endTime":end,"keyword":"","hyType":"",
        }
        def params(page):
            pairs=list({**base,"page":page}.items())
            pairs += [("disclosureType[]",dtype),("xxfcbj[]","2")]
            pairs += [("needFields[]",field) for field in contract.NEED_FIELDS]
            return pairs
        obj0,meta0=contract.request_variant(session,f"{query_code}_{dtype}_page0","POST",params(0))
        pm=contract.list_info_meta(obj0) if obj0 is not None else {}
        pages=pm.get("totalPages"); total=pm.get("totalElements")
        ok=(meta0.get("status")==200 and meta0.get("same_official_host") is True and meta0.get("parse")=="PASS"
            and isinstance(pages,int) and isinstance(total,int) and 0<=pages<=200 and pm.get("number")==0)
        if not ok:
            receipts.append({"code":query_code,"dtype":dtype,"page":0,"status":"FAIL","transport":meta0,"page_meta":pm})
            all_pass=False; continue
        for p in range(pages):
            if p==0: obj,meta=obj0,meta0
            else: obj,meta=contract.request_variant(session,f"{query_code}_{dtype}_page{p}","POST",params(p))
            page_meta=contract.list_info_meta(obj) if obj is not None else {}
            recs=contract.find_records(obj) if obj is not None else []
            pok=(meta.get("status")==200 and meta.get("same_official_host") is True and meta.get("parse")=="PASS"
                 and page_meta.get("number")==p and page_meta.get("totalPages")==pages and page_meta.get("totalElements")==total)
            receipts.append({"code":query_code,"dtype":dtype,"page":p,"status":"PASS" if pok else "FAIL",
                             "row_count":len(recs),"transport_sha256":meta.get("sha256"),"page_meta":page_meta})
            all_pass=all_pass and pok
            for r in recs:
                if str(r.get("companyCd") or "").strip()==query_code:
                    rows[ident(r)]=r
        objn,metan=contract.request_variant(session,f"{query_code}_{dtype}_page{pages}","POST",params(pages))
        recsn=contract.find_records(objn) if objn is not None else []
        nplus=(metan.get("status")==200 and metan.get("parse")=="PASS" and len(recsn)==0)
        receipts.append({"code":query_code,"dtype":dtype,"page":pages,"status":"PASS" if nplus else "FAIL","n_plus_one":True,"row_count":len(recsn)})
        all_pass=all_pass and nplus
    return [rows[k] for k in sorted(rows)],receipts,all_pass

def main():
    c=load("contract",CONTRACT); session=requests.Session()
    type_obj,type_meta=c.get_control_json(session,c.TYPE_ENDPOINT,{"type":6})
    dtypes=c.collect_values(type_obj,{"distype","dvalue","disclosureType","value"})[:40]
    mapping,map_meta=c.fetch_code_mapping(session)
    if type_meta.get("parse")!="PASS" or map_meta.get("parse")!="PASS" or not dtypes:
        raise RuntimeError("official BSE classification/code-mapping prerequisites not verified")
    reports=[]; all_queries=True
    for item in INITIAL:
        canonical=item["canonical_code"]; aliases=mapping.get(canonical,[])
        codes=list(dict.fromkeys([canonical]+aliases))
        merged={}; recpts=[]; qpass=True
        for code in codes:
            rows,receipts,ok=query_all(c,session,code,item["effective_date"],END,dtypes)
            qpass=qpass and ok; recpts.extend(receipts)
            for r in rows: merged[ident(r)]=r
        events=[]
        for k in sorted(merged):
            r=merged[k]
            name=str(r.get("companyName") or "")
            events.append({
              "companyCd":r.get("companyCd"),"companyName":name,"name_state":state(name),
              "publishDate":r.get("publishDate"),"title":title(r),"destFilePath":r.get("destFilePath"),
            })
        events.sort(key=lambda x:(str(x["publishDate"]),str(x["companyCd"]),str(x["title"])))
        warning=[x for x in events if x["name_state"]=="ST_WARNING"]
        after_warning=False; transitions=[]
        for e in events:
            if e["name_state"]=="ST_WARNING": after_warning=True
            elif after_warning and e["name_state"] in {"NON_ST_NAME","DELISTING_NAME"}:
                transitions.append(e)
        reports.append({
          **item,"official_aliases":aliases,"queried_codes":codes,"query_status":"PASS" if qpass else "NOT VERIFIED",
          "announcement_count":len(events),"first_announcement":events[0] if events else None,
          "last_announcement":events[-1] if events else None,
          "warning_name_observation_count":len(warning),
          "post_warning_non_st_or_delisting_transition_count":len(transitions),
          "post_warning_transitions":transitions,
          "events":events,"page_receipts":recpts,
          "canonical_sha256":sha(events),
        })
        all_queries=all_queries and qpass
    any_transition=sum(x["post_warning_non_st_or_delisting_transition_count"] for x in reports)
    all_have_warning=all(x["warning_name_observation_count"]>0 for x in reports)
    report={
      "schema":"stock-bse-post-implementation-state-sequence-v1",
      "window_end":END,"official_disclosure_types":dtypes,
      "classification_transport":type_meta,"code_mapping_transport":map_meta,
      "companies":reports,
      "summary":{
        "company_count":len(reports),
        "query_pass_count":sum(x["query_status"]=="PASS" for x in reports),
        "warning_name_observed_count":sum(x["warning_name_observation_count"]>0 for x in reports),
        "post_warning_transition_event_count":any_transition,
      },
      "adjudication":{
        "company_announcement_pagination":"PASS" if all_queries else "NOT VERIFIED",
        "post_implementation_name_state_sequence":"SUPPORTED" if all_queries and all_have_warning else "NOT VERIFIED",
        "observed_warning_to_non_st_transition":"SUPPORTED_DIAGNOSTIC" if any_transition else "NONE_OBSERVED",
        "removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"This exhausts official company-announcement pagination only for the five independently verified initial BSE warning implementations and their first-party old/new code aliases through 2026-09-30. Announcement-time companyName state is evidence, but absence of a non-ST transition is not by itself proof of complete removal history. Any observed transition still requires primary-document effective-date semantics."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"summary":report["summary"],"companies":[{"canonical_code":x["canonical_code"],"query_status":x["query_status"],"announcement_count":x["announcement_count"],"warning_name_observation_count":x["warning_name_observation_count"],"transition_count":x["post_warning_non_st_or_delisting_transition_count"],"transitions":x["post_warning_transitions"][:8],"last_announcement":x["last_announcement"]} for x in reports],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if all_queries and all_have_warning else 2
if __name__=="__main__": raise SystemExit(main())
