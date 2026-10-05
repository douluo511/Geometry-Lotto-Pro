from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE=Path(__file__).resolve().parent
BASE=HERE/"stock_sse_primary_transition_semantics_sample.py"
spec=importlib.util.spec_from_file_location("samplemod",BASE)
if spec is None or spec.loader is None: raise RuntimeError("cannot load sample module")
s=importlib.util.module_from_spec(spec); spec.loader.exec_module(s)

OUT=Path("stock_sse_directed_transition_dates.json")
DATE=r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
PATTERNS=[
 ("date_then_from_transition",re.compile(DATE+r"(?:起|开始|开市起|复牌起)?[^。；]{0,90}?(实施退市风险警示|实施其他风险警示|撤销退市风险警示|撤销其他风险警示|撤销股票退市风险警示|撤销股票其他风险警示)")),
 ("transition_then_from_date",re.compile(r"(实施退市风险警示|实施其他风险警示|撤销退市风险警示|撤销其他风险警示|撤销股票退市风险警示|撤销股票其他风险警示)[^。；]{0,90}?(?:自|于|从)?"+DATE+r"(?:起|开始|开市起|复牌起)?")),
 ("date_then_stock_abbrev",re.compile(DATE+r"(?:起|开始|开市起|复牌起)[^。；]{0,80}?(?:股票简称|证券简称)[^。；]{0,50}?(?:变更|改为|恢复)")),
]
TARGET={"actual_implementation_candidate","actual_cancel_candidate"}

def iso(groups):
    y,m,d=map(int,groups); return f"{y:04d}-{m:02d}-{d:02d}"

def directed(text):
    compact=re.sub(r"\s+","",text or "")
    hits=[]
    for name,pat in PATTERNS:
        for m in pat.finditer(compact):
            gs=m.groups()
            nums=[g for g in gs if isinstance(g,str) and re.fullmatch(r"20\d{2}|\d{1,2}",g or "")]
            # Find the first explicit YYYY年MM月DD日 inside this exact match to avoid group-order assumptions.
            dm=re.search(DATE,m.group(0))
            if not dm: continue
            date=iso(dm.groups())
            snippet=m.group(0)
            hits.append({"pattern":name,"date":date,"snippet_sha256":hashlib.sha256(snippet.encode()).hexdigest()})
    dedup={(h["pattern"],h["date"],h["snippet_sha256"]):h for h in hits}
    return list(dedup.values())

def main():
    session=requests.Session(); corpus=s.build_corpus(session)
    candidates=[]
    for row in corpus:
        klass=s.inventory.classify(row.get("title") or "")
        if klass in TARGET: candidates.append({**row,"transition_title_class":klass})
    candidates.sort(key=lambda x:(x["transition_title_class"],str(x.get("date") or ""),str(x.get("security_code") or ""),str(x.get("url") or "")))
    records=[]
    for idx,row in enumerate(candidates,1):
        rec={"ordinal":idx,"security_code":row.get("security_code"),"date":row.get("date"),"title":row.get("title"),"url":row.get("url"),"class":row["transition_title_class"],"attempts":[]}
        raw=None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                response,meta=s.fetch_pdf(session,url)
                rec["attempts"].append({"url":url,"status":"PASS","meta":meta})
                if response.content.startswith(b"%PDF"):
                    raw=response.content; rec["pdf_url"]=url; rec["pdf_sha256"]=hashlib.sha256(raw).hexdigest(); break
            except Exception as exc:
                rec["attempts"].append({"url":url,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"})
        if raw is None:
            rec["status"]="DOWNLOAD_NOT_VERIFIED"; records.append(rec); continue
        try: text,pages=s.extract_text(raw)
        except Exception as exc:
            rec["status"]="TEXT_NOT_VERIFIED"; rec["error"]=f"{type(exc).__name__}: {exc}"; records.append(rec); continue
        hits=directed(text); dates=sorted({h["date"] for h in hits})
        rec.update({"pages":pages,"text_sha256":hashlib.sha256(text.encode()).hexdigest(),"directed_hits":hits,"directed_dates":dates})
        if len(dates)==1: rec["status"]="UNIQUE_DIRECTED_DATE"
        elif len(dates)==0: rec["status"]="NO_DIRECTED_DATE"
        else: rec["status"]="MULTI_DIRECTED_DATE"
        records.append(rec)

    counts=Counter(x["status"] for x in records)
    by_class={}
    for klass in sorted(TARGET):
        subset=[x for x in records if x["class"]==klass]
        by_class[klass]={
          "selected":len(subset),
          "unique_directed_date":sum(x["status"]=="UNIQUE_DIRECTED_DATE" for x in subset),
          "multi_directed_date":sum(x["status"]=="MULTI_DIRECTED_DATE" for x in subset),
          "no_directed_date":sum(x["status"]=="NO_DIRECTED_DATE" for x in subset),
          "download_not_verified":sum(x["status"]=="DOWNLOAD_NOT_VERIFIED" for x in subset),
        }
    selected=len(records); unique=counts["UNIQUE_DIRECTED_DATE"]
    report={
      "schema":"stock-sse-directed-transition-dates-v1",
      "selected":selected,"status_counts":dict(sorted(counts.items())),"by_class":by_class,"records":records,
      "adjudication":{
        "directed_transition_date_coverage":"SUPPORTED" if selected and unique==selected else "NOT VERIFIED",
        "primary_document_semantics_complete":"NOT VERIFIED",
        "effective_state_reconstruction":"NOT VERIFIED",
        "shanghai_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Directed grammar reduces unrelated dates by requiring date/transition or date/stock-abbreviation semantics in the same clause. Any no-date or multi-date row remains fail-closed and must be manually or structurally adjudicated; this diagnostic does not itself establish PIT state."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"selected":selected,"status_counts":report["status_counts"],"by_class":by_class,"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if selected and unique==selected else 2

if __name__=="__main__": raise SystemExit(main())
