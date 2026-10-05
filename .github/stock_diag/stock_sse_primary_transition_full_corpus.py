from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASE = HERE / "stock_sse_primary_transition_semantics_sample.py"
spec = importlib.util.spec_from_file_location("samplemod", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load sample diagnostic module")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

OUT = Path("stock_sse_primary_transition_full_corpus.json")
TARGET_CLASSES = {"actual_implementation_candidate", "actual_cancel_candidate"}

DATE_CORE = r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"

IMPLEMENTATION_PATTERNS = [
    re.compile(
        rf"(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
        rf"[^。；\n]{{0,140}}?(?:被|将被|继续|叠加)?\s*实施"
        rf"(?:退市风险警示|其他风险警示|风险警示)"
    ),
    re.compile(
        rf"(?:公司股票|股票交易|证券交易)[^。；\n]{{0,100}}?"
        rf"(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
        rf"[^。；\n]{{0,140}}?(?:被|将被)?\s*实施"
        rf"(?:退市风险警示|其他风险警示|风险警示)"
    ),
    re.compile(
        rf"(?:实施|被实施|将被实施)(?:退市风险警示|其他风险警示|风险警示)"
        rf"[^。；\n]{{0,100}}?(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
    ),
]

CANCELLATION_PATTERNS = [
    re.compile(
        rf"(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
        rf"[^。；\n]{{0,140}}?(?:撤销|取消|不再实施)"
        rf"(?:股票)?(?:退市风险警示|其他风险警示|风险警示)"
    ),
    re.compile(
        rf"(?:撤销|取消|不再实施)(?:股票)?(?:退市风险警示|其他风险警示|风险警示)"
        rf"[^。；\n]{{0,100}}?(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
    ),
    re.compile(
        rf"(?:公司股票|股票交易|证券交易)[^。；\n]{{0,100}}?"
        rf"(?:自|于|从)?\s*{DATE_CORE}\s*(?:开市|交易)?\s*起"
        rf"[^。；\n]{{0,140}}?(?:撤销|取消)(?:股票)?"
        rf"(?:退市风险警示|其他风险警示|风险警示)"
    ),
]


def _iso_date(y: str, m: str, d: str) -> str | None:
    try:
        yi, mi, di = int(y), int(m), int(d)
        if not (2000 <= yi <= 2099 and 1 <= mi <= 12 and 1 <= di <= 31):
            return None
        return f"{yi:04d}-{mi:02d}-{di:02d}"
    except Exception:
        return None


def strong_transition_dates(text: str, klass: str) -> list[dict]:
    normalized = re.sub(r"[ \t\u3000]+", " ", text or "")
    patterns = (
        IMPLEMENTATION_PATTERNS
        if klass == "actual_implementation_candidate"
        else CANCELLATION_PATTERNS
    )
    evidence = []
    seen = set()
    for pattern_index, pattern in enumerate(patterns):
        for match in pattern.finditer(normalized):
            value = _iso_date(match.group(1), match.group(2), match.group(3))
            if value is None:
                continue
            key = (value, pattern_index, match.group(0))
            if key in seen:
                continue
            seen.add(key)
            lo = max(0, match.start() - 120)
            hi = min(len(normalized), match.end() + 180)
            evidence.append({
                "date": value,
                "pattern_index": pattern_index,
                "matched_text": re.sub(r"\s+", " ", match.group(0)).strip()[:320],
                "context": re.sub(r"\s+", " ", normalized[lo:hi]).strip()[:520],
            })
    return evidence


def main() -> int:
    session = requests.Session()
    corpus = s.build_corpus(session)
    candidates = []
    for row in corpus:
        klass = s.inventory.classify(row.get("title") or "")
        if klass in TARGET_CLASSES:
            candidates.append({**row, "transition_title_class": klass})
    candidates.sort(
        key=lambda x: (
            str(x.get("transition_title_class") or ""),
            str(x.get("date") or ""),
            str(x.get("security_code") or ""),
            str(x.get("url") or ""),
        )
    )

    records = []
    for idx, row in enumerate(candidates, start=1):
        rec = {
            "ordinal": idx,
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "date": row.get("date"),
            "title": row.get("title"),
            "url": row.get("url"),
            "transition_title_class": row.get("transition_title_class"),
            "status": "NOT VERIFIED",
            "attempts": [],
        }
        raw = None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                response, meta = s.fetch_pdf(session, url, attempts=4)
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
                rec["attempts"].append({
                    "url": url,
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                })
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

        transitions = strong_transition_dates(text, str(row.get("transition_title_class") or ""))
        dates = sorted({item["date"] for item in transitions if item.get("date")})
        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["strong_transition_evidence"] = transitions
        rec["candidate_dates"] = dates
        rec["candidate_date_count"] = len(dates)
        if not dates:
            rec["status"] = "NO_TRANSITION_DATE"
        elif len(dates) == 1:
            rec["status"] = "UNIQUE_DATE_CANDIDATE"
        else:
            rec["status"] = "MULTI_DATE_AMBIGUOUS"
        records.append(rec)

    selected = len(records)
    downloaded = sum(1 for x in records if x.get("pdf_sha256"))
    text_ok = sum(1 for x in records if x.get("text_sha256"))
    with_dates = sum(1 for x in records if x.get("candidate_date_count", 0) >= 1)
    unique_dates = sum(1 for x in records if x.get("candidate_date_count") == 1)
    ambiguous = sum(1 for x in records if x.get("candidate_date_count", 0) > 1)
    status_counts = dict(sorted(Counter(x["status"] for x in records).items()))
    by_class = {}
    for klass in sorted(TARGET_CLASSES):
        subset = [x for x in records if x["transition_title_class"] == klass]
        by_class[klass] = {
            "selected": len(subset),
            "pdf_downloaded": sum(1 for x in subset if x.get("pdf_sha256")),
            "text_extractable": sum(1 for x in subset if x.get("text_sha256")),
            "has_transition_date_candidate": sum(1 for x in subset if x.get("candidate_date_count", 0) >= 1),
            "unique_date_candidate": sum(1 for x in subset if x.get("candidate_date_count") == 1),
            "multi_date_ambiguous": sum(1 for x in subset if x.get("candidate_date_count", 0) > 1),
        }

    transport_complete = selected > 0 and downloaded == selected and text_ok == selected
    date_candidate_complete = selected > 0 and with_dates == selected
    unique_complete = selected > 0 and unique_dates == selected

    report = {
        "schema": "stock-sse-primary-transition-full-corpus-v2",
        "source_window": {"begin": s.market.BEGIN, "end": s.market.END},
        "source_event_corpus": {
            "unique_a_share_event_rows": len(corpus),
            "canonical_sha256": s.market.canonical_sha(corpus),
        },
        "full_candidate_corpus": {
            "selected_documents": selected,
            "pdf_downloaded": downloaded,
            "text_extractable": text_ok,
            "with_transition_date_candidate": with_dates,
            "unique_date_candidate": unique_dates,
            "multi_date_ambiguous": ambiguous,
            "status_counts": status_counts,
            "by_class": by_class,
            "unresolved_examples": [
                {
                    "ordinal": x.get("ordinal"),
                    "security_code": x.get("security_code"),
                    "date": x.get("date"),
                    "title": x.get("title"),
                    "status": x.get("status"),
                    "attempts": x.get("attempts"),
                }
                for x in records
                if x.get("status") not in {"UNIQUE_DATE_CANDIDATE"}
            ][:40],
        },
        "records": records,
        "adjudication": {
            "full_primary_pdf_transport_and_text": "PASS" if transport_complete else "NOT VERIFIED",
            "strong_transition_date_coverage": "SUPPORTED" if date_candidate_complete else "NOT VERIFIED",
            "unique_strong_transition_date_mapping": "SUPPORTED" if unique_complete else "NOT VERIFIED",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This exhausts the title-derived implementation/cancellation candidate set using only strong "
            "effective-date grammar such as '自/于 YYYY年M月D日起实施/撤销风险警示'. Nearby unrelated dates "
            "are not counted. Even complete strong-pattern coverage does not by itself prove market-wide state replay. "
            "Primary-document semantics, state reconstruction, historical ST PIT, Advanced Business and Final "
            "remain NOT VERIFIED until ambiguity is resolved and state replay is independently cross-checked."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "full_candidate_corpus": report["full_candidate_corpus"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    return 0 if transport_complete and date_candidate_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
