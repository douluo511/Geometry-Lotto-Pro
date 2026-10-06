from __future__ import annotations
import hashlib, importlib.util, json, re
from collections import Counter
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
FULL=HERE/"stock_sse_primary_transition_full_corpus.py"
spec=importlib.util.spec_from_file_location("fullmod",FULL)
if spec is None or spec.loader is None: raise RuntimeError("cannot load full corpus module")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s=m.s
OUT=Path("stock_sse_transition_date_role_parser.json")
DATE=r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
ROLE_PATTERNS=[
 ("effective_from",re.compile(r"(?:自|于|从)\s*"+DATE+r"\s*(?:起|开始)?[^。；]{0,80}(?:实施|撤销|取消|解除|变更)(?:退市风险警示|其他风险警示|风险警示|证券简称|股票简称)")),
 ("effective_on",re.compile(r"(?:实施|撤销|取消|解除|变更)(?:退市风险警示|其他风险警示|风险警示|证券简称|股票简称)[^。；]{0,100}"+DATE)),
 ("resume_and_change",re.compile(DATE+r"[^。；]{0,100}(?:撤销|取消|解除)(?:退市风险警示|其他风险警示|风险警示)")),
]
EXCLUDE_CONTEXT=("董事会","股东大会","收到","披露","公告日","审计报告","年度报告","申请","提交申请")

def iso(groups):
    y,mo,d=map(int,groups); return f"{y:04d}-{mo:02d}-{d:02d}"

def extract_role_dates(text):
    compact=re.sub(r"\s+","",text or "")
    hits=[]
    for role,pat in ROLE_PATTERNS:
        for mt in pat.finditer(compact):
            groups=mt.groups()
            date_groups=groups[-3:]
            context=compact[max(0,mt.start()-80):min(len(compact),mt.end()+120)]
            hits.append({"role":role,"date":iso(date_groups),"context_sha256":hashlib.sha256(context.encode()).hexdigest(),"excluded_context_terms":[x for x in EXCLUDE_CONTEXT if x in context]})
    dedup={}
    for h in hits: dedup[(h["role"],h["date"],h["context_sha256"])]=h
    return [dedup[k] for k in sorted(dedup)]

def build_candidates(session):
    corpus=s.build_corpus(session); out=[]
    for row in corpus:
        klass=s.inventory.classify(row.get("title") or "")
        if klass in m.TARGET_CLASSES: out.append({**row,"transition_title_class":klass})
    return sorted(out,key=lambda x:(x["transition_title_class"],str(x.get("date") or ""),str(x.get("security_code") or ""),str(x.get("url") or "")))

def main():
    session=requests.Session(); candidates=build_candidates(session); records=[]
    for i,row in enumerate(candidates,1):
        rec={"ordinal":i,"security_code":row.get("security_code"),"date":row.get("date"),"title":row.get("title"),"url":row.get("url"),"class":row["transition_title_class"],"status":"NOT VERIFIED"}
        raw=None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                resp,meta=s.fetch_pdf(session,url)
                if resp.content.startswith(b"%PDF"):
                    raw=resp.content; rec["pdf_url"]=url; rec["pdf_sha256"]=hashlib.sha256(raw).hexdigest(); break
            except Exception as exc: rec.setdefault("download_errors",[]).append(f"{type(exc).__name__}: {exc}")
        if raw is None: rec["status"]="DOWNLOAD_NOT_VERIFIED"; records.append(rec); continue
        try: text,pages=s.extract_text(raw)
        except Exception as exc: rec["status"]="TEXT_NOT_VERIFIED"; rec["error"]=f"{type(exc).__name__}: {exc}"; records.append(rec); continue
        hits=extract_role_dates(text); dates=sorted({h["date"] for h in hits})
        clean=sorted({h["date"] for h in hits if not h["excluded_context_terms"]})
        rec.update({"pages":pages,"role_hits":hits,"role_dates":dates,"clean_role_dates":clean,"role_date_count":len(dates),"clean_role_date_count":len(clean),"text_sha256":hashlib.sha256(text.encode()).hexdigest()})
        if len(clean)==1: rec["status"]="UNIQUE_CLEAN_ROLE_DATE"
        elif len(clean)>1: rec["status"]="MULTI_CLEAN_ROLE_DATE"
        elif len(dates)==1: rec["status"]="UNIQUE_ROLE_DATE_WITH_EXCLUDED_CONTEXT"
        elif len(dates)>1: rec["status"]="MULTI_ROLE_DATE_WITH_EXCLUDED_CONTEXT"
        else: rec["status"]="NO_ROLE_DATE"
        records.append(rec)
    counts=dict(sorted(Counter(x["status"] for x in records).items()))
    unique=sum(1 for x in records if x["status"]=="UNIQUE_CLEAN_ROLE_DATE")
    report={"schema":"stock-sse-transition-date-role-parser-v1","selected":len(records),"status_counts":counts,"unique_clean_role_date":unique,"records":records,
      "adjudication":{"role_parser_diagnostic":"SUPPORTED" if records else "NOT VERIFIED","unique_effective_date_mapping":"NOT VERIFIED","primary_document_semantics_complete":"NOT VERIFIED","effective_state_reconstruction":"NOT VERIFIED","shanghai_historical_st_pit":"NOT VERIFIED","full_historical_st_pit":"NOT VERIFIED","advanced_business":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"},
      "boundary":"Role-aware parsing separates transition-effective language from generic nearby dates. It remains diagnostic until ambiguous/no-role rows are resolved and replay is independently cross-checked."}
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"selected":len(records),"status_counts":counts,"unique_clean_role_date":unique,"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if records else 2
if __name__=="__main__": raise SystemExit(main())
