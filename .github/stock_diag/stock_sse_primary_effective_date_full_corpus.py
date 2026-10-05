from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "stock_sse_primary_transition_semantics_sample.py"
spec = importlib.util.spec_from_file_location("samplemod", SAMPLE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load sample diagnostic module")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

OUT = Path("stock_sse_primary_effective_date_full_corpus.json")
TARGET_CLASSES = {"actual_implementation_candidate", "actual_cancel_candidate"}

DATE_CH = r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
DATE_ISO = r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"
DATE_ANY = rf"(?:{DATE_CH}|{DATE_ISO})"

IMPLEMENT_ACTION = r"(?:被)?实施(?:退市|其他)?风险警示|(?:退市|其他)?风险警示(?:正式)?实施"
CANCEL_ACTION = r"(?:撤销|取消|终止实施)(?:退市|其他)?风险警示"
PROSPECTIVE = ("拟", "申请", "计划", "可能", "预计", "拟于", "拟自", "尚需", "提请")

PATTERNS = {
    "actual_implementation_candidate": [
        re.compile(rf"(?:自|于)(?P<date>{DATE_ANY})(?:开市|交易)?起.{{0,80}}?(?P<action>{IMPLEMENT_ACTION})"),
        re.compile(rf"(?P<action>{IMPLEMENT_ACTION}).{{0,80}}?(?:自|于)(?P<date>{DATE_ANY})(?:开市|交易)?起"),
    ],
    "actual_cancel_candidate": [
        re.compile(rf"(?:自|于)(?P<date>{DATE_ANY})(?:开市|交易)?起.{{0,80}}?(?P<action>{CANCEL_ACTION})"),
        re.compile(rf"(?P<action>{CANCEL_ACTION}).{{0,80}}?(?:自|于)(?P<date>{DATE_ANY})(?:开市|交易)?起"),
    ],
}


def norm_date(text: str) -> str | None:
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if len(nums) < 3:
        return None
    y, m, d = nums[:3]
    try:
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except Exception:
        return None


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def sentence_spans(text: str) -> list[str]:
    compact = compact_text(text)
    parts = re.split(r"(?<=[。；;！!?])", compact)
    return [x for x in parts if x]


def strong_effective_matches(text: str, title_class: str) -> list[dict]:
    pats = PATTERNS[title_class]
    out = []
    for sentence in sentence_spans(text):
        for pidx, pat in enumerate(pats):
            for match in pat.finditer(sentence):
                date = norm_date(match.group("date"))
                if not date:
                    continue
                start = max(0, match.start() - 24)
                end = min(len(sentence), match.end() + 24)
                snippet = sentence[start:end]
                before = sentence[max(0, match.start() - 16):match.start()]
                prospective = any(tok in before for tok in PROSPECTIVE)
                if prospective:
                    continue
                out.append({
                    "date": date,
                    "action": match.group("action"),
                    "pattern_index": pidx,
                    "sentence_sha256": hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
                    "snippet_sha256": hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                })
    dedup = {}
    for item in out:
        key = (item["date"], item["action"], item["sentence_sha256"], item["pattern_index"])
        dedup[key] = item
    return [dedup[k] for k in sorted(dedup)]


def main() -> int:
    session = requests.Session()
    corpus = s.build_corpus(session)

    candidates = []
    for row in corpus:
        klass = s.inventory.classify(row.get("title") or "")
        if klass in TARGET_CLASSES:
            candidates.append({**row, "transition_title_class": klass})
    candidates.sort(key=lambda x: (
        str(x.get("transition_title_class") or ""),
        str(x.get("date") or ""),
        str(x.get("security_code") or ""),
        str(x.get("url") or ""),
    ))

    records = []
    for ordinal, row in enumerate(candidates, 1):
        rec = {
            "ordinal": ordinal,
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "publication_date": row.get("date"),
            "title": row.get("title"),
            "url": row.get("url"),
            "transition_title_class": row.get("transition_title_class"),
            "attempts": [],
            "status": "NOT VERIFIED",
        }
        raw = None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                response, meta = s.fetch_pdf(session, url)
                attempt = {"url": url, "status": "PASS", "meta": meta}
                if not response.content.startswith(b"%PDF"):
                    attempt["status"] = "NOT_PDF"
                    rec["attempts"].append(attempt)
                    continue
                rec["attempts"].append(attempt)
                raw = response.content
                rec["pdf_url"] = url
                rec["pdf_sha256"] = hashlib.sha256(raw).hexdigest()
                rec["pdf_bytes"] = len(raw)
                break
            except Exception as exc:
                rec["attempts"].append({"url": url, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

        if raw is None:
            rec["status"] = "DOWNLOAD_NOT_VERIFIED"
            records.append(rec)
            continue

        try:
            text, pages = s.extract_text(raw)
        except Exception as exc:
            rec["status"] = "TEXT_NOT_VERIFIED"
            rec["extract_error"] = f"{type(exc).__name__}: {exc}"
            records.append(rec)
            continue

        matches = strong_effective_matches(text, rec["transition_title_class"])
        dates = sorted({x["date"] for x in matches})
        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["strong_effective_matches"] = matches
        rec["strong_effective_dates"] = dates
        rec["strong_effective_date_count"] = len(dates)

        pub = rec.get("publication_date")
        if pub and len(pub) >= 10 and dates:
            try:
                pubd = datetime.strptime(pub[:10], "%Y-%m-%d")
                rec["publication_to_effective_days"] = {
                    d: (datetime.strptime(d, "%Y-%m-%d") - pubd).days for d in dates
                }
            except Exception:
                pass

        if not dates:
            rec["status"] = "NO_STRONG_EFFECTIVE_DATE"
        elif len(dates) == 1:
            rec["status"] = "UNIQUE_STRONG_EFFECTIVE_DATE"
            rec["effective_date_candidate"] = dates[0]
        else:
            rec["status"] = "MULTI_STRONG_EFFECTIVE_DATE_AMBIGUOUS"
        records.append(rec)

    selected = len(records)
    downloaded = sum(1 for x in records if x.get("pdf_sha256"))
    text_ok = sum(1 for x in records if x.get("text_sha256"))
    unique = sum(1 for x in records if x.get("status") == "UNIQUE_STRONG_EFFECTIVE_DATE")
    ambiguous = sum(1 for x in records if x.get("status") == "MULTI_STRONG_EFFECTIVE_DATE_AMBIGUOUS")
    no_strong = sum(1 for x in records if x.get("status") == "NO_STRONG_EFFECTIVE_DATE")
    status_counts = dict(sorted(Counter(x["status"] for x in records).items()))

    by_class = {}
    for klass in sorted(TARGET_CLASSES):
        subset = [x for x in records if x["transition_title_class"] == klass]
        by_class[klass] = {
            "selected": len(subset),
            "pdf_downloaded": sum(1 for x in subset if x.get("pdf_sha256")),
            "text_extractable": sum(1 for x in subset if x.get("text_sha256")),
            "unique_strong_effective_date": sum(1 for x in subset if x.get("status") == "UNIQUE_STRONG_EFFECTIVE_DATE"),
            "multi_strong_effective_date_ambiguous": sum(1 for x in subset if x.get("status") == "MULTI_STRONG_EFFECTIVE_DATE_AMBIGUOUS"),
            "no_strong_effective_date": sum(1 for x in subset if x.get("status") == "NO_STRONG_EFFECTIVE_DATE"),
        }

    transport_complete = selected > 0 and downloaded == selected and text_ok == selected
    strong_complete = selected > 0 and unique == selected

    mapping = [
        {
            "security_code": x["security_code"],
            "publication_date": x["publication_date"],
            "title": x["title"],
            "transition_title_class": x["transition_title_class"],
            "effective_date_candidate": x.get("effective_date_candidate"),
            "status": x["status"],
        }
        for x in records
    ]
    mapping_sha = hashlib.sha256(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    report = {
        "schema": "stock-sse-primary-effective-date-full-corpus-v1",
        "source_window": {"begin": s.market.BEGIN, "end": s.market.END},
        "source_event_corpus": {
            "unique_a_share_event_rows": len(corpus),
            "canonical_sha256": s.market.canonical_sha(corpus),
        },
        "effective_date_parser": {
            "rule": "explicit 自/于 DATE 起 + actual implementation/cancellation action; prospective wording excluded",
            "mapping_sha256": mapping_sha,
        },
        "full_candidate_corpus": {
            "selected_documents": selected,
            "pdf_downloaded": downloaded,
            "text_extractable": text_ok,
            "unique_strong_effective_date": unique,
            "multi_strong_effective_date_ambiguous": ambiguous,
            "no_strong_effective_date": no_strong,
            "status_counts": status_counts,
            "by_class": by_class,
        },
        "records": records,
        "adjudication": {
            "full_primary_pdf_transport_and_text": "PASS" if transport_complete else "NOT VERIFIED",
            "strong_effective_date_semantics_complete": "SUPPORTED" if strong_complete else "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This parser accepts only explicit effective-date/action constructions and rejects prospective wording. "
            "It never substitutes nearest-date heuristics. Any document with zero or multiple strong effective dates "
            "remains NOT VERIFIED. Even complete transition-date mapping would still require chronological state replay, "
            "conflict checks and independent validation before Shanghai historical ST/PIT can pass."
        ),
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "effective_date_parser": report["effective_date_parser"],
        "full_candidate_corpus": report["full_candidate_corpus"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    # Execution success is transport/text completion. Business semantics remain
    # encoded independently and must not be promoted by process exit status.
    return 0 if transport_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
