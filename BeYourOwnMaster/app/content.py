from __future__ import annotations
from pathlib import Path
import re, sys

CHUNK_GLOB="v10_corpus_lines_*.txt"
STORY_START="第二部分：1200 张古今成长训练卡"
STORY_END="第三部分：主题索引与训练路线"
REAL_START="第二卷：300 个真实历史、商业、科学与治理案例"
REAL_END="第三卷：1500 条总索引与训练导航"

def content_root()->Path:
    base=getattr(sys,"_MEIPASS",None)
    if base:
        return Path(base)/"content"
    return Path(__file__).resolve().parents[1]/"content"

def corpus_files()->list[Path]:
    return sorted(content_root().glob(CHUNK_GLOB))

def load_corpus()->str:
    files=corpus_files()
    if not files:
        raise FileNotFoundError("V10 corpus chunks missing")
    return "\n".join(p.read_text(encoding="utf-8") for p in files)

def _section(text:str,start_marker:str,end_marker:str,required:str)->str:
    pos=0
    while True:
        start=text.find(start_marker,pos)
        if start<0:
            raise ValueError("section start missing: "+start_marker)
        end=text.find(end_marker,start+len(start_marker))
        if end<0:
            raise ValueError("section end missing: "+end_marker)
        section=text[start:end]
        if required in section:
            return section
        pos=start+len(start_marker)

def _ids(section:str,low:int,high:int)->set[int]:
    found=set()
    for raw in re.findall(r"(?m)^(\d{4})(?:\s+.*)?$",section):
        n=int(raw)
        if low<=n<=high:
            found.add(n)
    return found

def corpus_metrics()->dict:
    text=load_corpus()
    stories=_section(text,STORY_START,STORY_END,"0001 The Lion And The Mouse")
    real=_section(text,REAL_START,REAL_END,"1201")
    story_ids=_ids(stories,1,1200)
    real_ids=_ids(real,1201,1500)
    expected_stories=set(range(1,1201))
    expected_real=set(range(1201,1501))
    return {
        "chunk_count":len(corpus_files()),
        "char_count":len(text),
        "story_card_count":len(story_ids),
        "story_first":min(story_ids) if story_ids else None,
        "story_last":max(story_ids) if story_ids else None,
        "story_missing":sorted(expected_stories-story_ids)[:25],
        "real_case_count":len(real_ids),
        "real_case_first":min(real_ids) if real_ids else None,
        "real_case_last":max(real_ids) if real_ids else None,
        "real_case_missing":sorted(expected_real-real_ids)[:25],
        "total_training_entries":len(story_ids|real_ids),
        "fixed_eight_step":all(x in text for x in ("1. 复述","2. 利益","3. 5 Why","4. 逆转","5. 证据","6. 代价","7. 迁移","8. 行动")),
        "five_why_boundary":"5 Why 的作用是提出" in text and "不能因为问了五次就自动证明因果" in text,
        "reversal_boundary":"逆转的作用是打破单一路径" in text,
        "evidence_boundary":"有来源 ≠ 细节与因果均已独立复核" in text or "有来源”不等于" in text,
        "high_risk_boundary":"大额资金" in text and "健康" in text and "法律" in text and "专业意见" in text,
        "training_365":"第九部分：365 天训练路线" in text and "第 301-365 天" in text,
        "thirty_ninety_system":"30/90 天" in text and "90 天闭环训练" in text,
    }

def frozen_bundle_status()->str:
    m=corpus_metrics()
    ok=(
        m["chunk_count"]==28
        and m["story_card_count"]==1200 and m["story_first"]==1 and m["story_last"]==1200 and not m["story_missing"]
        and m["real_case_count"]==300 and m["real_case_first"]==1201 and m["real_case_last"]==1500 and not m["real_case_missing"]
        and m["total_training_entries"]==1500
        and m["fixed_eight_step"] and m["five_why_boundary"] and m["reversal_boundary"]
        and m["evidence_boundary"] and m["high_risk_boundary"] and m["training_365"] and m["thirty_ninety_system"]
    )
    return "PASS" if ok else "FAIL"

def search_corpus(query:str,limit:int=5)->list[dict]:
    q=(query or "").strip()
    if not q:
        return []
    hits=[]
    for p in corpus_files():
        text=p.read_text(encoding="utf-8")
        start=0
        while len(hits)<limit:
            i=text.find(q,start)
            if i<0:
                break
            lo=max(0,i-180); hi=min(len(text),i+len(q)+300)
            hits.append({"file":p.name,"query":q,"snippet":text[lo:hi].replace("\n"," ")})
            start=i+len(q)
        if len(hits)>=limit:
            break
    return hits
