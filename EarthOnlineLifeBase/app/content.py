from __future__ import annotations
from pathlib import Path
import re, sys

CHUNK_GLOB="v2_corpus_pages_*.txt"
STRUCTURE_MARKERS=[
    "本章要获得的能力",
    "1. 核心模型",
    "2. 深度讲解",
    "3. 现实应用",
    "4. 常见误区",
    "本章工具卡",
    "5. 练习",
    "参考答案与评分标准",
]

def content_root()->Path:
    meipass=getattr(sys,"_MEIPASS",None)
    if meipass:
        return Path(meipass)/"content"
    return Path(__file__).resolve().parents[1]/"content"

def corpus_files()->list[Path]:
    return sorted(content_root().glob(CHUNK_GLOB))

def load_corpus()->str:
    files=corpus_files()
    if not files:
        raise FileNotFoundError("Earth Online v2.0 corpus chunks are missing")
    return "\n".join(p.read_text(encoding="utf-8") for p in files)

def corpus_metrics()->dict:
    text=load_corpus()
    chapters=[int(x) for x in re.findall(r"(?m)^第\s*(\d+)\s*章",text)]
    cases=[int(x) for x in re.findall(r"(?m)^案例\s*(\d+)\b",text)]
    days=[int(x) for x in re.findall(r"(?m)^(\d+)\s+阶段\s+[IVX]+\b",text)]
    unique_days=sorted(set(days))
    marker_counts={m:text.count(m) for m in STRUCTURE_MARKERS}
    return {
        "chunk_count":len(corpus_files()),
        "char_count":len(text),
        "chapter_count":len(set(chapters)),
        "chapter_min":min(chapters) if chapters else None,
        "chapter_max":max(chapters) if chapters else None,
        "case_count":len(set(cases)),
        "case_min":min(cases) if cases else None,
        "case_max":max(cases) if cases else None,
        "training_day_count":len(unique_days),
        "training_day_min":min(unique_days) if unique_days else None,
        "training_day_max":max(unique_days) if unique_days else None,
        "structure_marker_counts":marker_counts,
        "has_case_rule":"案例库的使用规则" in text and "不能自动推广到所有场景" in text,
        "has_training_gates":all(x in text for x in ("Day 30","Day 90","Day 180","Day 270","Day 365")),
        "has_traditional_boundary":"黄帝内经" in text and "术数辨析" in text and "现代证据" in text,
        "has_political_boundary":"政治立场" in text or ("历史语境" in text and "独立" in text),
        "has_templates":all(x in text for x in ("附录 A","附录 B","附录 C","5 Why","逆转验证")),
        "has_outcome_boundary":"更新得快" in text and "错误会更早暴露" in text,
    }

def content_import_status()->str:
    m=corpus_metrics()
    structure=all(v>=21 for v in m["structure_marker_counts"].values())
    ok=(
        m["chunk_count"]==8
        and m["chapter_count"]==21 and m["chapter_min"]==1 and m["chapter_max"]==21
        and structure
        and m["case_count"]>=43 and m["case_min"]==1 and m["case_max"]>=43
        and m["training_day_count"]==365 and m["training_day_min"]==1 and m["training_day_max"]==365
        and m["has_case_rule"] and m["has_training_gates"]
        and m["has_traditional_boundary"] and m["has_political_boundary"]
        and m["has_templates"] and m["has_outcome_boundary"]
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
            lo=max(0,i-180); hi=min(len(text),i+len(q)+260)
            hits.append({"file":p.name,"query":q,"snippet":text[lo:hi].replace("\n"," ")})
            start=i+len(q)
        if len(hits)>=limit:
            break
    return hits
