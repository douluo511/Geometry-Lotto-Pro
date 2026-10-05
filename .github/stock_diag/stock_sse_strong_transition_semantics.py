from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASE = HERE / "stock_sse_primary_transition_full_corpus.py"
spec = importlib.util.spec_from_file_location("fullmod", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load full corpus diagnostic")
full = importlib.util.module_from_spec(spec)
spec.loader.exec_module(full)
s = full.s

OUT = Path("stock_sse_strong_transition_semantics.json")
DATE = r"(20\d{2})年(\d{1,2})月(\d{1,2})日"

IMPLEMENTATION_PATTERNS = [
    ("impl_from_date", re.compile(rf"(?:自|从|于)?\s*{DATE}\s*(?:开市|交易|复牌)?\s*起[^。；]{{0,80}}?(?:被|将被|开始|正式|继续|叠加)?实施(?:退市|其他)?风险警示")),
    ("impl_resume_and_apply", re.compile(rf"(?:于|自)?\s*{DATE}[^。；]{{0,50}}?(?:复牌|恢复交易)[^。；]{{0,60}}?(?:被|将被|开始|正式)?实施(?:退市|其他)?风险警示")),
    ("impl_apply_from", re.compile(rf"(?:实施(?:退市|其他)?风险警示|被实施(?:退市|其他)?风险警示)[^。；]{{0,80}}?(?:自|从|于)\s*{DATE}\s*(?:起|开始)")),
    ("impl_start_date_label", re.compile(rf"(?:实施|起始|开始)(?:退市|其他)?风险警示(?:的)?(?:起始日|开始日|实施日|日期)[：:]?\s*{DATE}")),
    ("impl_name_change_from", re.compile(rf"(?:股票简称|证券简称)[^。；]{{0,60}}?(?:自|从|于)\s*{DATE}\s*起[^。；]{{0,100}}?(?:\*ST|ST)[^。；]{{0,80}}?(?:实施|风险警示)")),
]

CANCEL_PATTERNS = [
    ("cancel_from_date", re.compile(rf"(?:自|从|于)?\s*{DATE}\s*(?:开市|交易|复牌)?\s*起[^。；]{{0,100}}?(?:撤销|取消|终止实施)(?:股票)?(?:退市|其他)?风险警示")),
    ("cancel_resume_and_remove", re.compile(rf"(?:于|自)?\s*{DATE}[^。；]{{0,50}}?(?:复牌|恢复交易)[^。；]{{0,80}}?(?:撤销|取消|终止实施)(?:股票)?(?:退市|其他)?风险警示")),
    ("cancel_action_from", re.compile(rf"(?:撤销|取消|终止实施)(?:股票)?(?:退市|其他)?风险警示[^。；]{{0,80}}?(?:自|从|于)\s*{DATE}\s*(?:起|开始)")),
    ("cancel_start_date_label", re.compile(rf"(?:撤销|取消)(?:股票)?(?:退市|其他)?风险警示(?:的)?(?:起始日|开始日|实施日|日期)[：:]?\s*{DATE}")),
    ("cancel_name_change_from", re.compile(rf"(?:股票简称|证券简称)[^。；]{{0,60}}?(?:自|从|于)\s*{DATE}\s*起[^。；]{{0,120}}?(?:由|变更为)[^。；]{{0,80}}?(?:撤销|取消|风险警示)")),
]

def iso(groups):
    y,m,d = map(int, groups)
    return f"{y:04d}-{m:02d}-{d:02d}"

def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")

def strong_matches(text: str, klass: str):
    compact = compact_text(text)
    pats = IMPLEMENTATION_PATTERNS if klass == "actual_implementation_candidate" else CANCEL_PATTERNS
    out=[]
    for pid,pat in pats:
        for m in pat.finditer(compact):
            try:
                value=iso(m.groups()[:3])
            except Exception:
                continue
            lo=max(0,m.start()-100); hi=min(len(compact),m.end()+140)
            ctx=compact[lo:hi]
            out.append({
                "pattern_id":pid,
                "date":value,
                "matched_text":m.group(0)[:320],
                "context_sha256":hashlib.sha256(ctx.encode("utf-8")).hexdigest(),
            })
    uniq={}
    for item in out:
        uniq[(item["pattern_id"],item["date"],item["matched_text"])]=item
    return [uniq[k] for k in sorted(uniq)]

def main() -> int:
    session=requests.Session()
    corpus=s.build_corpus(session)
    candidates=[]
    for row in corpus:
        klass=s.inventory.classify(row.get("title") or "")
        if klass in full.TARGET_CLASSES:
            candidates.append({**row,"transition_title_class":klass})
    candidates.sort(key=lambda x:(str(x["transition_title_class"]),str(x.get("date") or ""),str(x.get("security_code") or ""),str(x.get("url") or "")))

    records=[]
    for idx,row in enumerate(candidates,1):
        rec={
            "ordinal":idx,
            "security_code":row.get("security_code"),
            "security_name":row.get("security_name"),
            "publish_date":row.get("date"),
            "title":row.get("title"),
            "url":row.get("url"),
            "transition_title_class":row["transition_title_class"],
            "transport_status":"NOT VERIFIED",
            "semantic_status":"NOT VERIFIED",
            "attempts":[],
        }
        raw=None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                response,meta=s.fetch_pdf(session,url)
                att={"url":url,"status":"PASS","meta":meta}
                if not response.content.startswith(b"%PDF"):
                    att["status"]="NOT_PDF"; rec["attempts"].append(att); continue
                rec["attempts"].append(att)
                raw=response.content
                rec["pdf_url"]=url
                rec["pdf_sha256"]=hashlib.sha256(raw).hexdigest()
                rec["transport_status"]="PASS"
                break
            except Exception as exc:
                rec["attempts"].append({"url":url,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"})
        if raw is None:
            records.append(rec); continue
        try:
            text,pages=s.extract_text(raw)
        except Exception as exc:
            rec["extract_error"]=f"{type(exc).__name__}: {exc}"
            records.append(rec); continue
        rec["pages"]=pages
        rec["text_sha256"]=hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["text_chars"]=len(text)
        matches=strong_matches(text,row["transition_title_class"])
        dates=sorted({x["date"] for x in matches})
        rec["strong_matches"]=matches
        rec["strong_dates"]=dates
        rec["strong_date_count"]=len(dates)
        pub=str(row.get("date") or "")[:10]
        order_ok=[d for d in dates if (not pub or d >= pub)]
        rec["dates_on_or_after_publish_date"]=order_ok
        if len(dates)==1:
            rec["semantic_status"]="UNIQUE_STRONG_DATE"
            rec["effective_date_candidate"]=dates[0]
        elif len(dates)==0:
            rec["semantic_status"]="NO_STRONG_DATE"
        else:
            rec["semantic_status"]="MULTI_STRONG_DATE"
        records.append(rec)

    total=len(records)
    transport=sum(1 for x in records if x.get("transport_status")=="PASS" and x.get("text_sha256"))
    unique=sum(1 for x in records if x.get("semantic_status")=="UNIQUE_STRONG_DATE")
    none=sum(1 for x in records if x.get("semantic_status")=="NO_STRONG_DATE")
    multi=sum(1 for x in records if x.get("semantic_status")=="MULTI_STRONG_DATE")
    by_class={}
    for klass in sorted(full.TARGET_CLASSES):
        ss=[x for x in records if x["transition_title_class"]==klass]
        by_class[klass]={
            "selected":len(ss),
            "transport_and_text_pass":sum(1 for x in ss if x.get("transport_status")=="PASS" and x.get("text_sha256")),
            "unique_strong_date":sum(1 for x in ss if x.get("semantic_status")=="UNIQUE_STRONG_DATE"),
            "no_strong_date":sum(1 for x in ss if x.get("semantic_status")=="NO_STRONG_DATE"),
            "multi_strong_date":sum(1 for x in ss if x.get("semantic_status")=="MULTI_STRONG_DATE"),
        }

    unresolved=[{
        "security_code":x["security_code"],
        "publish_date":x["publish_date"],
        "title":x["title"],
        "class":x["transition_title_class"],
        "semantic_status":x["semantic_status"],
        "strong_dates":x.get("strong_dates",[]),
    } for x in records if x.get("semantic_status")!="UNIQUE_STRONG_DATE"]

    report={
        "schema":"stock-sse-strong-transition-semantics-v1",
        "source_product_base":"7f270b9ab58e11fd8129053a65e000c90ff9d8c1",
        "source_event_corpus":{"unique_a_share_event_rows":len(corpus),"canonical_sha256":s.market.canonical_sha(corpus)},
        "summary":{
            "selected_documents":total,
            "transport_and_text_pass":transport,
            "unique_strong_date":unique,
            "no_strong_date":none,
            "multi_strong_date":multi,
            "by_class":by_class,
            "status_counts":dict(sorted(Counter(x["semantic_status"] for x in records).items())),
            "unresolved_count":len(unresolved),
            "unresolved_sample":unresolved[:40],
        },
        "records":records,
        "adjudication":{
            "full_primary_pdf_transport_and_text":"PASS" if total>0 and transport==total else "NOT VERIFIED",
            "strong_transition_semantics_execution":"PASS",
            "unique_strong_effective_date_coverage":"SUPPORTED" if total>0 and unique==total else "PARTIAL_SUPPORTED",
            "primary_document_semantics_complete":"SUPPORTED" if total>0 and unique==total else "NOT VERIFIED",
            "effective_state_reconstruction":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":(
            "Only direct grammatical relations between a date and the implementation/cancellation action are accepted. "
            "No nearest-date fallback is used. Unmatched or multi-match documents remain unresolved. Even full document "
            "semantics would still require independently validated state replay before Shanghai/full historical ST PIT."
        ),
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":report["schema"],"summary":report["summary"],"adjudication":report["adjudication"]},ensure_ascii=True,sort_keys=True))
    return 0 if total>0 and transport==total else 2

if __name__=="__main__":
    raise SystemExit(main())
