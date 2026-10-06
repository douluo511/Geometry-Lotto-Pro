from __future__ import annotations
import hashlib, importlib.util, json, re
from datetime import date
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
STATE=HERE/"stock_bse_post_implementation_state_sequence.py"
EFFECTIVE=HERE/"stock_bse_risk_warning_effective_dates.py"
STATE_OUT=Path("stock_bse_post_implementation_state_sequence.json")
OUT=Path("stock_bse_delisting_name_effective_dates.json")
DATE=r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
PATTERNS=[
 ("delisting_period_start",re.compile(r"(?:退市整理期(?:交易)?(?:的)?(?:起始日|开始日|首个交易日)|进入退市整理期交易(?:的)?起始日)[：:\s]*"+DATE)),
 ("from_date_delisting_period",re.compile(r"(?:自|于|从)\s*"+DATE+r"\s*(?:起|开市起)?[^。；\n]{0,140}(?:进入|开始)(?:股票)?退市整理期")),
 ("date_enter_delisting_period",re.compile(DATE+r"[^。；\n]{0,120}(?:起|开市起)?[^。；\n]{0,120}(?:进入|开始)(?:股票)?退市整理期")),
 ("delisting_name_from_date",re.compile(r"(?:股票简称|证券简称)[^。；\n]{0,120}(?:自|于|从)\s*"+DATE+r"\s*(?:起|开市起)?[^。；\n]{0,120}(?:变更为|改为)[^。；\n]{0,40}退")),
]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def iso(g):
    y,m,d=map(int,g); return date(y,m,d).isoformat()

def hits(text):
    out=[]
    for label,pat in PATTERNS:
        for mt in pat.finditer(text):
            g=mt.groups()[-3:]
            try: dt=iso(g)
            except Exception: continue
            ctx=re.sub(r"\s+"," ",text[max(0,mt.start()-160):min(len(text),mt.end()+220)]).strip()
            out.append({"rule":label,"date":dt,"context_sha256":hashlib.sha256(ctx.encode()).hexdigest()})
    dedup={(x["rule"],x["date"],x["context_sha256"]):x for x in out}
    return [dedup[k] for k in sorted(dedup)]

def main():
    st=load("state",STATE); eff=load("eff",EFFECTIVE)
    rc=st.main()
    if rc!=0: raise RuntimeError("state-sequence prerequisite failed")
    src=json.loads(STATE_OUT.read_text(encoding="utf-8"))
    targets=[]
    for comp in src.get("companies") or []:
        trans=[x for x in comp.get("post_warning_transitions") or [] if x.get("name_state")=="DELISTING_NAME"]
        if trans:
            targets.append({
              "canonical_code":comp.get("canonical_code"),
              "effective_warning_start":comp.get("effective_date"),
              "transition":trans[0],
            })
    if len(targets)!=2:
        raise RuntimeError(f"expected exactly two first delisting-name transitions, got {len(targets)}")
    session=requests.Session(); rows=[]
    for item in targets:
        tr=item["transition"]; path=str(tr.get("destFilePath") or "").strip()
        url=eff.urljoin(eff.BSE_ROOT+"/",path.lstrip("/")) if hasattr(eff,"urljoin") else eff.BSE_ROOT+"/"+path.lstrip("/")
        payload,transport=eff.fetch_pdf(session,url)
        rec={**item,"url":url,"transport":transport,"document_status":"NOT VERIFIED","effective_date_status":"NOT VERIFIED","candidate_dates":[]}
        if payload is None:
            rows.append(rec); continue
        try: text,pages=eff.extract_pdf_text(payload)
        except Exception as exc:
            rec["parse_error"]=f"{type(exc).__name__}: {exc}"; rows.append(rec); continue
        rec["document_status"]="PASS"; rec["pdf_pages"]=pages
        rec["pdf_text_sha256"]=hashlib.sha256(text.encode("utf-8")).hexdigest()
        hh=hits(text); dates=sorted({x["date"] for x in hh})
        rec["semantic_hits"]=hh; rec["candidate_dates"]=dates
        if len(dates)==1:
            rec["effective_date_status"]="SUPPORTED_UNIQUE_PRIMARY_DATE"
            rec["delisting_state_effective_date"]=dates[0]
        elif len(dates)>1:
            rec["effective_date_status"]="MULTI_DATE_AMBIGUOUS"
        else:
            rec["effective_date_status"]="NO_STRONG_DATE"
        rows.append(rec)
    pdf_pass=sum(x["document_status"]=="PASS" for x in rows)
    unique=sum(x["effective_date_status"]=="SUPPORTED_UNIQUE_PRIMARY_DATE" for x in rows)
    report={
      "schema":"stock-bse-delisting-name-effective-dates-v1",
      "target_count":len(rows),"pdf_pass_count":pdf_pass,"unique_effective_date_count":unique,
      "rows":rows,
      "adjudication":{
        "warning_to_delisting_name_transition":"SUPPORTED" if unique==len(rows)==2 else "NOT VERIFIED",
        "delisting_transition_primary_document_semantics":"SUPPORTED" if unique==2 else "NOT VERIFIED",
        "removal_event_history_complete":"NOT VERIFIED",
        "bse_effective_state_reconstruction":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"This validates only the two observed *ST-to-delisting-name transitions found by the exhaustive post-implementation announcement sequence. Delisting is not a normal risk-warning removal. No ordinary-name removal is inferred, and complete BSE historical PIT remains non-PASS until state replay and independent completeness checks close."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"target_count":len(rows),"pdf_pass_count":pdf_pass,"unique_effective_date_count":unique,"rows":[{"canonical_code":x["canonical_code"],"publishDate":x["transition"].get("publishDate"),"companyName":x["transition"].get("companyName"),"effective_date_status":x["effective_date_status"],"candidate_dates":x["candidate_dates"],"document_status":x["document_status"]} for x in rows],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if pdf_pass==2 and unique==2 else 2
if __name__=="__main__": raise SystemExit(main())
