from __future__ import annotations

import hashlib, importlib.util, json, re, time
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ARCHIVE=HERE/"stock_szse_suspension_static_archive.py"
OUT=Path("stock_szse_suspension_primary_sample.json")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36"
DATE=r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
STOP=[
 re.compile(rf"(?:自|于|从)?\s*{DATE}\s*(?:开市|交易)?\s*起[^。；\n]{{0,80}}?(?:停牌|暂停交易)"),
 re.compile(rf"(?:股票|证券)[^。；\n]{{0,80}}?(?:将于|于|自)\s*{DATE}[^。；\n]{{0,80}}?(?:停牌|暂停交易)")
]
RESUME=[
 re.compile(rf"(?:自|于|从)?\s*{DATE}\s*(?:开市|交易)?\s*起[^。；\n]{{0,80}}?(?:复牌|恢复交易)"),
 re.compile(rf"(?:股票|证券)[^。；\n]{{0,80}}?(?:将于|于|自)\s*{DATE}[^。；\n]{{0,80}}?(?:复牌|恢复交易)")
]
CODE_RE=re.compile(r"(?<!\d)(?:00\d{4}|30\d{4}|20\d{4}|12\d{4})(?!\d)")

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path)
 if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
 m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def official(url):
 host=(urlparse(url).hostname or "").lower()
 return host=="szse.cn" or host.endswith(".szse.cn")

def fetch(session,url,attempts=3):
 errs=[]
 for n in range(1,attempts+1):
  try:
   r=session.get(url,headers={"User-Agent":UA,"Referer":"https://www.szse.cn/disclosure/notice/temp/","Accept":"text/html,application/xhtml+xml,*/*;q=0.8"},timeout=(8,30),allow_redirects=True)
   meta={"attempt":n,"status":r.status_code,"url":r.url,"bytes":len(r.content),"sha256":hashlib.sha256(r.content).hexdigest()}
   if r.status_code in {403,429} or r.status_code>=500: raise RuntimeError(f"retryable HTTP {r.status_code}")
   r.raise_for_status()
   if not official(r.url): raise RuntimeError("left official SZSE host")
   return r,{"attempts":errs+[meta],"selected_attempt":n}
  except Exception as exc:
   errs.append({"attempt":n,"error":f"{type(exc).__name__}: {exc}"})
   if n==attempts: return None,{"attempts":errs,"selected_attempt":None}
   time.sleep(2*n)
 return None,{"attempts":errs,"selected_attempt":None}

def iso(g):
 y,m,d=map(int,g[:3]); return date(y,m,d).isoformat()

def strong(text,pats):
 compact=re.sub(r"\s+","",text or "")
 out=[]
 for pi,p in enumerate(pats):
  for m in p.finditer(compact):
   try: d=iso(m.groups())
   except Exception: continue
   out.append({"date":d,"pattern":pi,"match":m.group(0)[:280]})
 return sorted({(x["date"],x["pattern"],x["match"]):x for x in out}.values(),key=lambda x:(x["date"],x["pattern"],x["match"]))

def extract_title(soup):
 candidates=[]
 for sel in ["h1","h2",".title",".article-title",".tit",".news-title"]:
  for node in soup.select(sel):
   t=" ".join(node.get_text(" ",strip=True).split())
   if t: candidates.append(t)
 if soup.title:
  t=" ".join(soup.title.get_text(" ",strip=True).split())
  if t: candidates.append(t)
 candidates=[x for x in candidates if "深圳证券交易所" not in x or len(x)>12]
 return candidates[0] if candidates else None

def main():
 mod=load("archive",ARCHIVE)
 rc=mod.main()
 if rc not in (0,None): raise SystemExit(f"archive rebuild failed {rc}")
 src=json.loads(Path("stock_szse_suspension_static_archive.json").read_text(encoding="utf-8"))
 events=src["corpus"]["events"]
 buckets=defaultdict(list)
 for e in events:
  buckets[e["date"][:4]].append(e)
 selected=[]
 for y in sorted(buckets):
  vals=sorted(buckets[y],key=lambda x:(x["date"],x["url"]))
  selected.append(vals[0])
  if vals[-1]["url"]!=vals[0]["url"]: selected.append(vals[-1])
 session=requests.Session()
 rows=[]
 for i,e in enumerate(selected,1):
  r,transport=fetch(session,e["url"])
  rec={"ordinal":i,"date":e["date"],"url":e["url"],"transport":transport,"status":"NOT VERIFIED"}
  if r is None:
   rows.append(rec); continue
  text=r.content.decode(r.apparent_encoding or "utf-8",errors="replace")
  soup=BeautifulSoup(text,"html.parser")
  visible="\n".join(x.strip() for x in soup.stripped_strings)
  title=extract_title(soup)
  codes=sorted(set(CODE_RE.findall(visible)))
  stops=strong(visible,STOP); resumes=strong(visible,RESUME)
  rec.update({
    "status":"PASS","html_sha256":hashlib.sha256(r.content).hexdigest(),"title":title,
    "visible_text_sha256":hashlib.sha256(visible.encode()).hexdigest(),"visible_chars":len(visible),
    "security_codes":codes,"stop_matches":stops,"resume_matches":resumes,
    "strong_stop_dates":sorted({x["date"] for x in stops}),
    "strong_resume_dates":sorted({x["date"] for x in resumes}),
  })
  rows.append(rec)
  time.sleep(0.35)
 total=len(rows); transport=sum(1 for x in rows if x["status"]=="PASS")
 titles=sum(1 for x in rows if x.get("title"))
 codes=sum(1 for x in rows if x.get("security_codes"))
 semantics=sum(1 for x in rows if x.get("strong_stop_dates") or x.get("strong_resume_dates"))
 report={
  "schema":"stock-szse-suspension-primary-sample-v1",
  "source_archive_sha256":src["corpus"]["canonical_sha256"],
  "sample":{"strategy":"deterministic first-and-last event per year","selected":total,"transport_pass":transport,"title_present":titles,"security_code_present":codes,"strong_transition_semantics":semantics,"years":sorted(buckets),"records":rows},
  "adjudication":{
   "primary_article_transport":"PASS" if total and transport==total else "NOT VERIFIED",
   "primary_article_title_extraction":"SUPPORTED_SAMPLE_ONLY" if titles else "NOT VERIFIED",
   "primary_article_code_extraction":"SUPPORTED_SAMPLE_ONLY" if codes else "NOT VERIFIED",
   "primary_article_transition_semantics":"SUPPORTED_SAMPLE_ONLY" if semantics else "NOT VERIFIED",
   "archive_title_semantics_complete":"NOT VERIFIED",
   "shenzhen_historical_suspension_state":"NOT VERIFIED",
   "shenzhen_historical_st_pit":"NOT VERIFIED",
   "full_historical_st_pit":"NOT VERIFIED",
   "advanced_business":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"
  },
  "boundary":"Sample only. Publication dates are never substituted for effective stop/resume dates. Full archive semantics and daily replay remain non-PASS."
 }
 OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"schema":report["schema"],"sample":{k:v for k,v in report["sample"].items() if k!="records"},"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
 return 0 if total and transport==total else 2

if __name__=="__main__": raise SystemExit(main())
