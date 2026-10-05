from __future__ import annotations

import hashlib
import importlib.util
import json
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

        transitions = s.near_transition_dates(text)
        dates = sorted({d for item in transitions for d in item.get("dates", [])})
        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["transition_evidence"] = transitions
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
        "schema": "stock-sse-primary-transition-full-corpus-v1",
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
        },
        "records": records,
        "adjudication": {
            "full_primary_pdf_transport_and_text": "PASS" if transport_complete else "NOT VERIFIED",
            "full_transition_date_candidate_coverage": "SUPPORTED" if date_candidate_complete else "NOT VERIFIED",
            "unique_transition_date_mapping": "SUPPORTED" if unique_complete else "NOT VERIFIED",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This exhausts the title-derived implementation/cancellation candidate set and measures official PDF "
            "transport, text extraction, and transition-date candidate coverage. Even complete date-candidate "
            "coverage does not prove that a candidate date is the unique effective transition date. "
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
