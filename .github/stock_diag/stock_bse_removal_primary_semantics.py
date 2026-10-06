from __future__ import annotations
import hashlib, importlib.util, json, re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
import requests

HERE=Path(__file__).resolve().parent
ACTION=HERE/"stock_bse_removal_action_vocabulary.py"
EFFECTIVE=HERE/"stock_bse_risk_warning_effective_dates.py"
OUT=Path("stock_bse_removal_primary_semantics.json")
ACTION_OUT=Path("stock_bse_removal_action_vocabulary.json")
DATE=r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
PATTERNS=[
 ("remove_delisting_warning",re.compile(r"(?:撤销|解除|取消)(?:股票交易)?(?:退市)?风险警示")),
 ("terminate_delisting_warning",re.compile(r"(?:终止|不再)实施(?:退市)?风险警示")),
 ("name_from_st",re.compile(r"(?:证券简称|股票简称)[^。；\n]{0,120}(?:由|从)[^。；\n]{0,50}(?:\*ST|ST)[^。；\n]{0,100}(?:变更为|改为)")),
]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def sha(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def iso(g):
    y,m,d=map(int,g); return date(y,m,d).isoformat()

def strong_hits(text):
    hits=[]
    for label,pat in PATTERNS:
        for mt in pat.finditer(text):
            lo=max(0,mt.start()-220); hi=min(len(text),mt.end()+260)
            ctx=re.sub(r"\s+"," ",text[lo:hi]).strip()
            dates=[]
            for dm in re.finditer(DATE,ctx):
                try: dates.append(iso(dm.groups()))
                except Exception: pass
            hits.append({
                "semantic":label,
                "context_sha256":hashlib.sha256(ctx.encode("utf-8")).hexdigest(),
                "candidate_dates":sorted(set(dates)),
            })
    dedup={(x["semantic"],x["context_sha256"]):x for x in hits}
    return [dedup[k] for k in sorted(dedup)]

def main():
    action=load("action",ACTION); eff=load("eff",EFFECTIVE)
    rc=action.main()
    if rc!=0: raise RuntimeError("action vocabulary prerequisite failed")
    src=json.loads(ACTION_OUT.read_text(encoding="utf-8"))
    candidates=src.get("transition_candidates") or []
    session=requests.Session(); rows=[]
    for item in candidates:
        path=str(item.get("destFilePath") or "").strip()
        url=urljoin(eff.BSE_ROOT+"/",path.lstrip("/"))
        payload,transport=eff.fetch_pdf(session,url)
        rec={
          "companyCd":item.get("companyCd"),"companyName":item.get("companyName"),
          "publishDate":item.get("publishDate"),"title":item.get("title"),
          "destFilePath":path,"url":url,"document_status":"NOT VERIFIED",
          "semantic_status":"NOT VERIFIED","semantic_hits":[],"transport":transport,
        }
        if payload is None:
            rows.append(rec); continue
        try: text,pages=eff.extract_pdf_text(payload)
        except Exception as exc:
            rec["parse_error"]=f"{type(exc).__name__}: {exc}"; rows.append(rec); continue
        rec["document_status"]="PASS"; rec["pdf_pages"]=pages
        rec["pdf_text_sha256"]=hashlib.sha256(text.encode("utf-8")).hexdigest()
        hits=strong_hits(text); rec["semantic_hits"]=hits
        if hits:
            dates=sorted({d for h in hits for d in h["candidate_dates"]})
            rec["semantic_status"]="STRONG_REMOVAL_SEMANTICS"
            rec["candidate_dates"]=dates
            rec["effective_date_status"]="UNIQUE_CANDIDATE" if len(dates)==1 else ("MULTI_CANDIDATE" if len(dates)>1 else "NO_DATE_CANDIDATE")
        else:
            rec["semantic_status"]="NO_STRONG_REMOVAL_SEMANTICS"
            rec["candidate_dates"]=[]
            rec["effective_date_status"]="NOT APPLICABLE"
        rows.append(rec)
    docs_pass=sum(x["document_status"]=="PASS" for x in rows)
    strong=[x for x in rows if x["semantic_status"]=="STRONG_REMOVAL_SEMANTICS"]
    unique=[x for x in strong if x.get("effective_date_status")=="UNIQUE_CANDIDATE"]
    report={
      "schema":"stock-bse-removal-primary-semantics-v1",
      "source_action_schema":src.get("schema"),
      "selected_title_candidates":len(rows),
      "pdf_pass_count":docs_pass,
      "strong_removal_semantic_count":len(strong),
      "unique_date_candidate_count":len(unique),
      "strong_removal_rows":strong,
      "records":rows,
      "canonical_sha256":sha(rows),
      "adjudication":{
        "candidate_primary_pdf_transport":"PASS" if rows and docs_pass==len(rows) else "NOT VERIFIED",
        "strong_removal_primary_semantics":"SUPPORTED_DIAGNOSTIC" if strong else "NOT VERIFIED",
        "unique_removal_effective_date_mapping":"NOT VERIFIED",
        "removal_vocabulary_complete":"NOT VERIFIED",
        "bse_removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Only explicit primary-document risk-warning removal semantics survive this filter. Title action-word matches such as restricted-share release are rejected. Even strong matches do not prove vocabulary/history completeness or daily PIT without unique effective dates and state replay."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"selected_title_candidates":len(rows),"pdf_pass_count":docs_pass,"strong_removal_semantic_count":len(strong),"unique_date_candidate_count":len(unique),"strong_rows":[{"companyCd":x["companyCd"],"publishDate":x["publishDate"],"title":x["title"],"effective_date_status":x.get("effective_date_status"),"candidate_dates":x.get("candidate_dates")} for x in strong],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if rows and docs_pass==len(rows) else 2
if __name__=="__main__": raise SystemExit(main())
