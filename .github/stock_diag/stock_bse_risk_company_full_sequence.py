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

def compact(value):
    return "".join(str(value or "").split())

REMOVAL_VERBS=("撤销","取消","终止实施","不再实施")
PROSPECTIVE_TOKENS=("可能被实施","风险提示","提示性公告","申请")
IMPLEMENTATION_TOKENS=("被实施","将被实施","实施退市风险警示","实施其他风险警示","实施风险警示")

def classify_transition_title(text):
    t=compact(text)
    has_warning="风险警示" in t
    if has_warning and "申请" in t and any(v in t for v in REMOVAL_VERBS):
        return "removal_application"
    if has_warning and any(v in t for v in REMOVAL_VERBS):
        return "actual_removal_candidate"
    if has_warning and any(tok in t for tok in ("继续实施","叠加实施")):
        return "continuation_or_overlay"
    if has_warning and any(tok in t for tok in PROSPECTIVE_TOKENS):
        return "prospective_risk_notice"
    if has_warning and any(tok in t for tok in IMPLEMENTATION_TOKENS):
        return "implementation_candidate"
    if has_warning:
        return "risk_warning_other"
    if any(tok in t for tok in ("解除限售","取消监事会","稳定股价","权益分派")):
        return "explicit_non_st_transition"
    if any(tok in t for tok in ("证券简称","股票简称")):
        return "name_reference_other"
    return "other"

def warning_name_state(name):
    n=compact(name)
    if n.startswith("*ST"):
        return 2
    if n.startswith("ST"):
        return 1
    return 0

def observed_name_transitions(seq):
    out=[]
    previous=None
    for row in seq:
        state=warning_name_state(row.get("companyName"))
        marker=(state, compact(row.get("companyName")))
        if previous is None:
            previous={"state":state,"name":row.get("companyName"),"date":row.get("publishDate")}
            continue
        if state != previous["state"]:
            out.append({
                "publishDate":row.get("publishDate"),
                "from_state":previous["state"],
                "from_name":previous["name"],
                "to_state":state,
                "to_name":row.get("companyName"),
                "title":row.get("title"),
                "destFilePath":row.get("destFilePath"),
                "direction":"warning_to_normal" if previous["state"]>0 and state==0 else (
                    "normal_to_warning" if previous["state"]==0 and state>0 else "warning_level_change"
                ),
            })
        previous={"state":state,"name":row.get("companyName"),"date":row.get("publishDate")}
    return out

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
      classified=[]
      for x in seq:
        category=classify_transition_title(x["title"])
        if category!="other":
          classified.append({**x,"transition_category":category})
      transitions=observed_name_transitions(seq)
      removal_titles=[x for x in classified if x["transition_category"]=="actual_removal_candidate"]
      removal_apps=[x for x in classified if x["transition_category"]=="removal_application"]
      implementations=[x for x in classified if x["transition_category"]=="implementation_candidate"]
      prospective=[x for x in classified if x["transition_category"]=="prospective_risk_notice"]
      name_removals=[x for x in transitions if x["direction"]=="warning_to_normal"]
      company_reports.append({
        "companyCd":code,
        "aliases":sorted(set(aliases.get(code,[]))),
        "status":"PASS" if ok else "NOT VERIFIED",
        "total_pages":pages,
        "server_total_elements":total,
        "exact_company_rows":len(seq),
        "classified_rows":classified,
        "classified_count":len(classified),
        "actual_removal_title_candidates":removal_titles,
        "actual_removal_title_count":len(removal_titles),
        "removal_application_rows":removal_apps,
        "removal_application_count":len(removal_apps),
        "implementation_candidates":implementations,
        "implementation_candidate_count":len(implementations),
        "prospective_risk_rows":prospective,
        "prospective_risk_count":len(prospective),
        "observed_name_transitions":transitions,
        "warning_to_normal_name_transitions":name_removals,
        "warning_to_normal_name_transition_count":len(name_removals),
        "sequence_sha256":sha(seq),
        "page_receipts":receipts,
      })
      all_transport=all_transport and ok
      all_rows.extend(classified)
    report={
      "schema":"stock-bse-risk-company-full-sequence-v1",
      "risk_company_count":len(raw_codes),
      "risk_company_codes":raw_codes,
      "company_reports":company_reports,
      "classified_event_count":len(all_rows),
      "classified_event_sha256":sha(all_rows),
      "actual_removal_title_candidate_count":sum(x["actual_removal_title_count"] for x in company_reports),
      "removal_application_count":sum(x["removal_application_count"] for x in company_reports),
      "implementation_candidate_count":sum(x["implementation_candidate_count"] for x in company_reports),
      "prospective_risk_count":sum(x["prospective_risk_count"] for x in company_reports),
      "warning_to_normal_name_transition_count":sum(x["warning_to_normal_name_transition_count"] for x in company_reports),
      "adjudication":{
        "risk_company_full_sequence_transport":"PASS" if all_transport else "NOT VERIFIED",
        "company_scoped_transition_inventory":"SUPPORTED_DIAGNOSTIC" if all_transport and all_rows else "NOT VERIFIED",
        "observed_warning_name_sequence":"SUPPORTED_DIAGNOSTIC" if all_transport else "NOT VERIFIED",
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
    print(json.dumps({
      "schema":report["schema"],
      "risk_company_count":len(raw_codes),
      "company_summary":{
        x["companyCd"]:{
          "status":x["status"],
          "rows":x["exact_company_rows"],
          "classified":x["classified_count"],
          "actual_removal_titles":x["actual_removal_title_count"],
          "removal_applications":x["removal_application_count"],
          "implementations":x["implementation_candidate_count"],
          "prospective":x["prospective_risk_count"],
          "warning_to_normal_name_transitions":x["warning_to_normal_name_transition_count"],
        } for x in company_reports
      },
      "classified_event_count":report["classified_event_count"],
      "actual_removal_title_candidate_count":report["actual_removal_title_candidate_count"],
      "removal_application_count":report["removal_application_count"],
      "implementation_candidate_count":report["implementation_candidate_count"],
      "prospective_risk_count":report["prospective_risk_count"],
      "warning_to_normal_name_transition_count":report["warning_to_normal_name_transition_count"],
      "removal_title_sample":[x for r in company_reports for x in r["actual_removal_title_candidates"]][:30],
      "warning_to_normal_sample":[x for r in company_reports for x in r["warning_to_normal_name_transitions"]][:30],
      "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if all_transport else 2
if __name__=="__main__": raise SystemExit(main())
