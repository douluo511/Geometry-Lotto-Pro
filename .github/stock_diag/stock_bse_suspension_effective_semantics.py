from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

HERE=Path(__file__).resolve().parent
CORPUS_PATH=HERE/"stock_bse_suspension_marketwide_corpus.py"
OUT=Path("stock_bse_suspension_effective_semantics.json")
BSE_ROOT="https://www.bse.cn"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE suspension semantics"
DATE=r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"

STOP_PATTERNS=[
    ("stop_from_date",re.compile(rf"(?:自|于|从)?\s*{DATE}\s*(?:开市|交易)?\s*起[^。；\n]{{0,70}}?(?:停牌|暂停交易)")),
    ("stop_on_date",re.compile(rf"(?:公司股票|股票|证券)[^。；\n]{{0,80}}?(?:将于|于|自)\s*{DATE}[^。；\n]{{0,70}}?(?:停牌|暂停交易)")),
    ("stop_date_label",re.compile(rf"(?:停牌|暂停交易)(?:时间|日期|起始日|开始日)[：:\s]*{DATE}")),
]
RESUME_PATTERNS=[
    ("resume_from_date",re.compile(rf"(?:自|于|从)?\s*{DATE}\s*(?:开市|交易)?\s*起[^。；\n]{{0,70}}?(?:复牌|恢复交易)")),
    ("resume_on_date",re.compile(rf"(?:公司股票|股票|证券)[^。；\n]{{0,80}}?(?:将于|于|自)\s*{DATE}[^。；\n]{{0,70}}?(?:复牌|恢复交易)")),
    ("resume_date_label",re.compile(rf"(?:复牌|恢复交易)(?:时间|日期|起始日|开始日)[：:\s]*{DATE}")),
]
PROSPECTIVE_PREFIX=re.compile(r"(可能|拟|计划|预计)")
ACTION_TERM_RE=re.compile(r"(停牌|暂停交易|复牌|恢复交易)")

# Strict heading-bound transitions. These only accept an explicit section label
# plus a direct "stock from DATE ... suspend/resume" relation. They do not use
# publication dates, estimates, application dates, or generic nearby dates.
HEADING_STOP_RE=re.compile(
    rf"(?:停牌日期(?:及(?:预计)?复牌日期)?)[^。；\n]{{0,160}}?"
    rf"(?:本公司股票|公司股票|股票)[^。；\n]{{0,28}}?(?:自|于)\s*{DATE}\s*(?:开市)?\s*(?:起)?停牌"
)
HEADING_RESUME_RE=re.compile(
    rf"(?:复牌(?:依据及)?复牌日期)[^。；\n]{{0,180}}?"
    rf"(?:本公司股票|公司股票|股票)[^。；\n]{{0,28}}?(?:自|于)\s*{DATE}\s*(?:开市)?\s*(?:起)?复牌"
)
HEADING_PAIR_RE=re.compile(
    rf"(?:停牌日期及(?:预计)?复牌日期)[^。；\n]{{0,160}}?"
    rf"(?:本公司股票|公司股票|股票)[^。；\n]{{0,28}}?(?:自|于)\s*{DATE}\s*(?:开市)?\s*(?:起)?停牌"
    rf"[^。；\n]{{0,80}}?(?:并于|于|自)\s*{DATE}\s*(?:开市)?\s*(?:起)?复牌"
)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def same_bse(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="bse.cn" or host.endswith(".bse.cn")

def fetch_pdf(session,url,attempts=2):
    errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=session.get(url,headers={"User-Agent":UA,"Referer":"https://www.bse.cn/disclosure/announcement.html","Accept":"application/pdf,application/octet-stream,*/*"},timeout=(8,35),allow_redirects=True)
            meta={"attempt":attempt,"http_status":r.status_code,"resolved_url":r.url,"bytes":len(r.content),"sha256":hashlib.sha256(r.content).hexdigest(),"same_official_host":same_bse(r.url),"pdf_magic":r.content.startswith(b"%PDF")}
            if r.status_code in {403,429}:
                errors.append({**meta,"rate_limited":True})
                if attempt==attempts:
                    return None,{"attempts":errors,"selected_attempt":None,"rate_limit_exhausted":True}
                time.sleep(75.0)
                continue
            if r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content.startswith(b"%PDF") or not same_bse(r.url):
                raise RuntimeError("not official BSE PDF")
            return r.content,{"attempts":errors+[meta],"selected_attempt":attempt}
        except Exception as exc:
            errors.append({"attempt":attempt,"error":f"{type(exc).__name__}: {exc}"})
            if attempt==attempts:
                return None,{"attempts":errors,"selected_attempt":None}
            time.sleep(3.0*attempt)
    return None,{"attempts":errors,"selected_attempt":None}

def extract_text(raw):
    reader=PdfReader(io.BytesIO(raw))
    pages=[]
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    text="\n".join(pages)
    text=re.sub(r"[ \t\u3000]+"," ",text)
    text=re.sub(r"\r\n?","\n",text)
    return text,len(reader.pages)

def iso(groups):
    y,m,d=map(int,groups)
    return date(y,m,d).isoformat()

def strong_matches(text,patterns,action_word):
    compact=re.sub(r"\s+","",text or "")
    out=[]
    for pid,pat in patterns:
        for m in pat.finditer(compact):
            local=compact[max(0,m.start()-32):m.start()]
            matched=m.group(0)
            # Reject genuinely prospective wording near the matched relation,
            # but do not reject a definitive exchange-approved sentence merely
            # because it is preceded by “经向北京证券交易所申请”.
            if PROSPECTIVE_PREFIX.search(local[-16:] + matched):
                continue
            if "申请" in local[-16:] and "交易所申请" not in local[-24:]:
                continue
            full_dates=list(re.finditer(DATE,matched))
            # A broad clause spanning multiple complete dates cannot prove
            # which date governs the action. Keep it unresolved.
            if len(full_dates) != 1:
                continue
            date_match=full_dates[0]
            after_date=matched[date_match.end():]
            if action_word=="复牌":
                positions=[p for p in (after_date.find("复牌"),after_date.find("恢复交易")) if p>=0]
                if not positions:
                    continue
                before_action=after_date[:min(positions)]
                if "停牌" in before_action or "暂停交易" in before_action:
                    continue
            elif action_word=="停牌":
                positions=[p for p in (after_date.find("停牌"),after_date.find("暂停交易")) if p>=0]
                if not positions:
                    continue
                before_action=after_date[:min(positions)]
                if "披露" in before_action:
                    continue
            try:
                value=iso(m.groups()[:3])
            except Exception:
                continue
            lo=max(0,m.start()-120); hi=min(len(compact),m.end()+160)
            ctx=compact[lo:hi]
            out.append({"pattern_id":pid,"date":value,"matched_text":matched[:320],"context_sha256":hashlib.sha256(ctx.encode()).hexdigest()})
    dedup={}
    for x in out:
        dedup[(x["pattern_id"],x["date"],x["matched_text"])]=x
    return [dedup[k] for k in sorted(dedup)]

def heading_transition_matches(text):
    compact=re.sub(r"\s+","",text or "")
    stops=[]
    resumes=[]
    for m in HEADING_STOP_RE.finditer(compact):
        try:
            value=iso(m.groups()[:3])
        except Exception:
            continue
        matched=m.group(0)
        stops.append({
            "pattern_id":"heading_stop_date",
            "date":value,
            "matched_text":matched[:320],
            "context_sha256":hashlib.sha256(matched.encode()).hexdigest(),
        })
    for m in HEADING_RESUME_RE.finditer(compact):
        try:
            value=iso(m.groups()[:3])
        except Exception:
            continue
        matched=m.group(0)
        resumes.append({
            "pattern_id":"heading_resume_date",
            "date":value,
            "matched_text":matched[:320],
            "context_sha256":hashlib.sha256(matched.encode()).hexdigest(),
        })
    for m in HEADING_PAIR_RE.finditer(compact):
        groups=m.groups()
        try:
            stop_value=iso(groups[:3])
            resume_value=iso(groups[3:6])
        except Exception:
            continue
        matched=m.group(0)
        ctx_hash=hashlib.sha256(matched.encode()).hexdigest()
        stops.append({
            "pattern_id":"heading_stop_resume_pair_stop",
            "date":stop_value,
            "matched_text":matched[:320],
            "context_sha256":ctx_hash,
        })
        resumes.append({
            "pattern_id":"heading_stop_resume_pair_resume",
            "date":resume_value,
            "matched_text":matched[:320],
            "context_sha256":ctx_hash,
        })
    def dedupe(rows):
        out={}
        for x in rows:
            out[(x["pattern_id"],x["date"],x["matched_text"])]=x
        return [out[k] for k in sorted(out)]
    return dedupe(stops),dedupe(resumes)

def action_contexts(text,limit=48):
    compact=re.sub(r"\s+","",text or "")
    out=[]
    for m in ACTION_TERM_RE.finditer(compact):
        lo=max(0,m.start()-180); hi=min(len(compact),m.end()+220)
        snippet=compact[lo:hi]
        dates=[]
        for d in re.finditer(DATE,snippet):
            try:
                dates.append(iso(d.groups()[:3]))
            except Exception:
                pass
        out.append({
            "action":m.group(1),
            "dates":sorted(set(dates)),
            "snippet":snippet[:420],
            "snippet_sha256":hashlib.sha256(snippet.encode()).hexdigest(),
        })
        if len(out)>=limit:
            break
    return out

def main():
    corpusmod=load("bsec",CORPUS_PATH)
    rc=corpusmod.main()
    if rc not in (0,None):
        raise SystemExit(f"corpus rebuild failed rc={rc}")
    corpus=json.loads(Path("stock_bse_suspension_marketwide_corpus.json").read_text(encoding="utf-8"))
    events=corpus.get("combined_events") or []
    session=requests.Session()
    records=[]
    cooldowns=[]
    for i,event in enumerate(events,1):
        if i > 1 and (i - 1) % 20 == 0:
            session.close()
            cooldown={"after_ordinal":i-1,"seconds":75,"reason":"proactive official BSE PDF rate-limit cooldown"}
            cooldowns.append(cooldown)
            time.sleep(cooldown["seconds"])
            session=requests.Session()
        path=str(event.get("destFilePath") or "").strip()
        url=urljoin(BSE_ROOT+"/",path.lstrip("/"))
        rec={
            "ordinal":i,
            "canonical_company_code":event.get("canonical_company_code"),
            "raw_company_code":event.get("raw_company_code"),
            "publishDate":event.get("publishDate"),
            "title":event.get("title"),
            "destFilePath":path,
            "url":url,
            "transport_status":"NOT VERIFIED",
            "semantic_status":"NOT VERIFIED",
        }
        payload,transport=fetch_pdf(session,url)
        rec["transport"]=transport
        if payload is None:
            records.append(rec); continue
        rec["transport_status"]="PASS"
        rec["pdf_sha256"]=hashlib.sha256(payload).hexdigest()
        try:
            text,pages=extract_text(payload)
        except Exception as exc:
            rec["parse_error"]=f"{type(exc).__name__}: {exc}"
            records.append(rec); continue
        rec["pages"]=pages
        rec["text_chars"]=len(text)
        rec["text_sha256"]=hashlib.sha256(text.encode()).hexdigest()
        rec["action_contexts"]=action_contexts(text)
        stops=strong_matches(text,STOP_PATTERNS,"停牌")
        resumes=strong_matches(text,RESUME_PATTERNS,"复牌")
        heading_stops,heading_resumes=heading_transition_matches(text)
        stops.extend(heading_stops)
        resumes.extend(heading_resumes)
        stop_dates=sorted({x["date"] for x in stops})
        resume_dates=sorted({x["date"] for x in resumes})
        rec["stop_matches"]=stops
        rec["resume_matches"]=resumes
        rec["stop_dates"]=stop_dates
        rec["resume_dates"]=resume_dates
        rec["stop_date_count"]=len(stop_dates)
        rec["resume_date_count"]=len(resume_dates)
        if len(stop_dates)<=1 and len(resume_dates)<=1 and (stop_dates or resume_dates):
            rec["semantic_status"]="UNIQUE_TRANSITION_DATES"
        elif not stop_dates and not resume_dates:
            rec["semantic_status"]="NO_STRONG_TRANSITION_DATE"
        else:
            rec["semantic_status"]="MULTI_DATE_AMBIGUOUS"
        records.append(rec)

    total=len(records)
    transport=sum(1 for x in records if x.get("transport_status")=="PASS" and x.get("text_sha256"))
    unique=sum(1 for x in records if x.get("semantic_status")=="UNIQUE_TRANSITION_DATES")
    none=sum(1 for x in records if x.get("semantic_status")=="NO_STRONG_TRANSITION_DATE")
    multi=sum(1 for x in records if x.get("semantic_status")=="MULTI_DATE_AMBIGUOUS")
    stop_unique=sum(1 for x in records if x.get("stop_date_count")==1)
    resume_unique=sum(1 for x in records if x.get("resume_date_count")==1)
    unresolved=[{
        "code":x.get("canonical_company_code"),
        "publishDate":x.get("publishDate"),
        "title":x.get("title"),
        "semantic_status":x.get("semantic_status"),
        "stop_dates":x.get("stop_dates",[]),
        "resume_dates":x.get("resume_dates",[]),
        "action_contexts":(x.get("action_contexts") or [])[:16],
    } for x in records if x.get("semantic_status")!="UNIQUE_TRANSITION_DATES"]

    report={
      "schema":"stock-bse-suspension-effective-semantics-v1",
      "source_corpus_sha256":corpus.get("combined_canonical_sha256"),
      "source_event_count":len(events),
      "summary":{
        "selected_documents":total,
        "transport_and_text_pass":transport,
        "unique_transition_documents":unique,
        "no_strong_transition_date":none,
        "multi_date_ambiguous":multi,
        "unique_stop_date_documents":stop_unique,
        "unique_resume_date_documents":resume_unique,
        "status_counts":dict(sorted(Counter(x["semantic_status"] for x in records).items())),
        "unresolved_count":len(unresolved),
        "unresolved_sample":unresolved[:40],
      },
      "rate_limit_control":{"batch_size":20,"cooldown_seconds":75,"cooldowns":cooldowns},
      "records":records,
      "adjudication":{
        "full_primary_pdf_transport_and_text":"PASS" if total>0 and transport==total else "NOT VERIFIED",
        "bse_suspension_transition_semantics":"SUPPORTED_DIAGNOSTIC" if unique>0 else "NOT VERIFIED",
        "bse_suspension_event_semantics_complete":"SUPPORTED" if total>0 and unique==total else "NOT VERIFIED",
        "bse_effective_daily_suspension_state":"NOT VERIFIED",
        "bse_historical_suspension_pit":"NOT VERIFIED",
        "bse_historical_st_pit":"NOT VERIFIED",
        "full_historical_st_pit":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "product_bytes_changed":False,
        "final_gate":"FAIL",
      },
      "boundary":"Only explicit PDF text linking dates to stop/resume actions is accepted. Publication date is never substituted. Even complete transition semantics would still require ordered interval replay on a validated trading calendar before BSE historical suspension PIT."
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"summary":report["summary"],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if total>0 and transport==total else 2

if __name__=="__main__":
    raise SystemExit(main())
