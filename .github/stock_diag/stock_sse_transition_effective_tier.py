from __future__ import annotations
import hashlib, importlib.util, json, re
from collections import Counter
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
BASE=HERE/"stock_sse_transition_date_role_parser.py"
spec=importlib.util.spec_from_file_location("rolemod",BASE)
if spec is None or spec.loader is None: raise RuntimeError("cannot load role parser")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s=m.s
OUT=Path("stock_sse_transition_effective_tier.json")
D=r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
RULES=[
 ("resume_then_transition",100,re.compile(r"将于"+D+r"[^。；]{0,100}(?:停牌|暂停交易)[^。；]{0,180}?(?:并于|于)"+D+r"[^。；]{0,100}(?:开市起|复牌)[^。；]{0,120}(?:实施|撤销|取消|解除)(?:退市风险警示|其他风险警示|风险警示)"),"second"),
 ("from_open_transition",98,re.compile(r"(?:自|于|从)"+D+r"(?:开市|复牌|交易)?起[^。；]{0,120}(?:实施|撤销|取消|解除)(?:退市风险警示|其他风险警示|风险警示)"),"first"),
 ("transition_from_open",96,re.compile(r"(?:实施|撤销|取消|解除)(?:退市风险警示|其他风险警示|风险警示)[^。；]{0,120}(?:自|于|从)"+D+r"(?:开市|复牌|交易)?起"),"first"),
 ("name_change_from",92,re.compile(r"(?:证券简称|股票简称)[^。；]{0,80}(?:自|于|从)"+D+r"(?:起|开市起)?[^。；]{0,100}(?:变更为|由[^。；]{0,40}变更为)"),"first"),
 ("date_open_transition",90,re.compile(D+r"(?:开市起|复牌后|恢复交易后)[^。；]{0,120}(?:实施|撤销|取消|解除)(?:退市风险警示|其他风险警示|风险警示)"),"first"),
]

def iso(g):
 y,mo,d=map(int,g); return f"{y:04d}-{mo:02d}-{d:02d}"

def strong_hits(text):
 t=re.sub(r"\s+","",text or ""); out=[]
 for name,score,pat,which in RULES:
  for mt in pat.finditer(t):
   gs=mt.groups()
   if which=="second":
    dg=gs[-3:]
   else:
    dg=gs[:3]
   ctx=t[max(0,mt.start()-80):min(len(t),mt.end()+120)]
   out.append({"rule":name,"score":score,"date":iso(dg),"context_sha256":hashlib.sha256(ctx.encode()).hexdigest()})
 dedup={(x["rule"],x["date"],x["context_sha256"]):x for x in out}
 return [dedup[k] for k in sorted(dedup)]

def main():
 session=requests.Session(); candidates=m.build_candidates(session); rows=[]
 for i,row in enumerate(candidates,1):
  rec={"ordinal":i,"security_code":row.get("security_code"),"date":row.get("date"),"title":row.get("title"),"url":row.get("url"),"class":row["transition_title_class"],"status":"NOT VERIFIED"}
  raw=None
  for url in s.candidate_urls(str(row.get("url") or "")):
   try:
    resp,meta=s.fetch_pdf(session,url)
    if resp.content.startswith(b"%PDF"): raw=resp.content; rec["pdf_url"]=url; rec["pdf_sha256"]=hashlib.sha256(raw).hexdigest(); break
   except Exception as exc: rec.setdefault("download_errors",[]).append(f"{type(exc).__name__}: {exc}")
  if raw is None: rec["status"]="DOWNLOAD_NOT_VERIFIED"; rows.append(rec); continue
  try: text,pages=s.extract_text(raw)
  except Exception as exc: rec["status"]="TEXT_NOT_VERIFIED"; rec["error"]=f"{type(exc).__name__}: {exc}"; rows.append(rec); continue
  hits=strong_hits(text); rec["strong_hits"]=hits; rec["pages"]=pages; rec["text_sha256"]=hashlib.sha256(text.encode()).hexdigest()
  if not hits: rec["status"]="NO_STRONG_EFFECTIVE_ROLE"; rows.append(rec); continue
  mx=max(x["score"] for x in hits); top=sorted({x["date"] for x in hits if x["score"]==mx})
  rec["top_score"]=mx; rec["top_dates"]=top
  if len(top)==1: rec["status"]="UNIQUE_TOP_EFFECTIVE_DATE"; rec["effective_date_candidate"]=top[0]
  else: rec["status"]="MULTI_TOP_EFFECTIVE_DATE"
  rows.append(rec)
 counts=dict(sorted(Counter(x["status"] for x in rows).items()))
 by_class={}
 for k in sorted(m.TARGET_CLASSES):
  q=[x for x in rows if x["class"]==k]
  by_class[k]={"selected":len(q),"unique_top":sum(x["status"]=="UNIQUE_TOP_EFFECTIVE_DATE" for x in q),"multi_top":sum(x["status"]=="MULTI_TOP_EFFECTIVE_DATE" for x in q),"no_strong":sum(x["status"]=="NO_STRONG_EFFECTIVE_ROLE" for x in q)}
 report={"schema":"stock-sse-transition-effective-tier-v1","selected":len(rows),"status_counts":counts,"by_class":by_class,"records":rows,
  "adjudication":{"strong_effective_role_mapping":"SUPPORTED_DIAGNOSTIC","unique_effective_date_mapping":"NOT VERIFIED","primary_document_semantics_complete":"NOT VERIFIED","effective_state_reconstruction":"NOT VERIFIED","shanghai_historical_st_pit":"NOT VERIFIED","full_historical_st_pit":"NOT VERIFIED","advanced_business":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"},
  "boundary":"Highest-tier explicit implementation/cancellation language is diagnostic evidence only. Any no-strong or multi-top row keeps market-wide effective-date mapping and PIT non-PASS until resolved and replay independently cross-checked."}
 OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"schema":report["schema"],"selected":len(rows),"status_counts":counts,"by_class":by_class,"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
 return 0
if __name__=="__main__": raise SystemExit(main())
