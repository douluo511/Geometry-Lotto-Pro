from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

import stock_sse_primary_transition_semantics_sample as s

OUT = Path("stock_sse_primary_transition_semantic_resolver.json")
TARGET_CLASSES = {"actual_implementation_candidate", "actual_cancel_candidate"}
DATE_TOKEN = r"(20\d{2}年\d{1,2}月\d{1,2}日)"

IMPLEMENT_PATTERNS = [
    ("impl_from_date", re.compile(rf"自{DATE_TOKEN}起.{{0,60}}?(?:实施|实行|被实施).{{0,28}}?(?:退市|其他)?风险警示")),
    ("impl_date_then_start", re.compile(rf"{DATE_TOKEN}.{{0,28}}?(?:起|开始).{{0,32}}?(?:实施|实行|被实施).{{0,28}}?(?:退市|其他)?风险警示")),
    ("impl_date_stock", re.compile(rf"(?:自|于)?{DATE_TOKEN}.{{0,60}}?股票.{{0,28}}?(?:实施|实行|被实施).{{0,28}}?(?:退市|其他)?风险警示")),
    ("impl_date_direct", re.compile(rf"(?:自|于)?{DATE_TOKEN}.{{0,40}}?(?:实施|实行|被实施).{{0,28}}?(?:退市|其他)?风险警示")),
]

CANCEL_PATTERNS = [
    ("cancel_from_date", re.compile(rf"自{DATE_TOKEN}起.{{0,60}}?撤销.{{0,28}}?(?:退市|其他)?风险警示")),
    ("cancel_date_then_start", re.compile(rf"{DATE_TOKEN}.{{0,28}}?(?:起|开始).{{0,32}}?撤销.{{0,28}}?(?:退市|其他)?风险警示")),
    ("cancel_date_stock", re.compile(rf"(?:自|于)?{DATE_TOKEN}.{{0,60}}?股票.{{0,28}}?撤销.{{0,28}}?(?:退市|其他)?风险警示")),
    ("cancel_date_direct", re.compile(rf"(?:自|于)?{DATE_TOKEN}.{{0,40}}?撤销.{{0,28}}?(?:退市|其他)?风险警示")),
]

def parse_cn_date(value: str) -> dt.date:
    y, m, d = map(int, re.findall(r"\d+", value))
    return dt.date(y, m, d)

def parse_row_date(value: object) -> dt.date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).date()
        except Exception:
            pass
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if m:
        return dt.date(*map(int, m.groups()))
    return None

def semantic_matches(text: str, klass: str, publication_date: object) -> list[dict]:
    compact = re.sub(r"\s+", "", text or "")
    patterns = IMPLEMENT_PATTERNS if klass == "actual_implementation_candidate" else CANCEL_PATTERNS
    pub = parse_row_date(publication_date)
    out = []
    seen = set()
    for pattern_id, pattern in patterns:
        for match in pattern.finditer(compact):
            raw_date = match.group(1)
            try:
                day = parse_cn_date(raw_date)
            except Exception:
                continue
            key = (pattern_id, day.isoformat(), match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            distance = (day - pub).days if pub else None
            seg_start = max(0, match.start() - 80)
            seg_end = min(len(compact), match.end() + 120)
            segment = compact[seg_start:seg_end]
            out.append({
                "pattern_id": pattern_id,
                "date": day.isoformat(),
                "publication_distance_days": distance,
                "match_start": match.start(),
                "match_end": match.end(),
                "evidence_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
            })
    out.sort(key=lambda x: (
        abs(x["publication_distance_days"]) if x["publication_distance_days"] is not None else 10**9,
        x["date"],
        x["pattern_id"],
        x["match_start"],
    ))
    return out

def build_corpus_resilient(session: requests.Session) -> tuple[list[dict], dict]:
    combined = {}
    receipts = []
    for label, keyword in s.market.KEYWORDS:
        item = None
        errors = []
        for attempt in range(1, 5):
            try:
                item = s.market.fetch_keyword(session, label, keyword)
                receipts.append({"label": label, "keyword": keyword, "attempt": attempt, "status": "PASS", "prior_errors": errors})
                break
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                errors.append(msg)
                retryable = any(token in msg for token in ("HTTP 403", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "timeout", "Timeout"))
                if not retryable or attempt == 4:
                    receipts.append({"label": label, "keyword": keyword, "attempt": attempt, "status": "FAIL", "errors": errors})
                    raise
                time.sleep(4.0 * attempt)
        if item is None:
            raise RuntimeError(f"keyword fetch unresolved: {label}/{keyword}")
        for row in item["records"]:
            ident = s.market.identity(row)
            if ident not in combined:
                combined[ident] = dict(row)
    return [combined[k] for k in sorted(combined)], {"keyword_receipts": receipts}


def write_execution_failure(exc: Exception, stage: str) -> int:
    report = {
        "schema": "stock-sse-primary-transition-semantic-resolver-v1",
        "execution_failure": {"stage": stage, "error_type": type(exc).__name__, "error": str(exc)},
        "summary": {"selected_documents": 0, "pdf_downloaded": 0, "text_extractable": 0, "strong_unique_near_publication": 0, "strong_unique_anywhere": 0, "unresolved": 0, "status_counts": {}, "by_class": {}, "resolution_canonical_sha256": None},
        "adjudication": {
            "diagnostic_transport": "FAIL",
            "class_specific_semantic_disambiguation": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "repository_independence": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": "Network or execution failure is preserved as evidence and cannot be promoted into semantic or PIT support.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 2


def main() -> int:
    session = requests.Session()
    try:
        corpus, fetch_evidence = build_corpus_resilient(session)
    except Exception as exc:
        return write_execution_failure(exc, "build_marketwide_corpus")
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
    for idx, row in enumerate(candidates, start=1):
        rec = {
            "ordinal": idx,
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "publication_date": row.get("date"),
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

        matches = semantic_matches(text, rec["transition_title_class"], rec["publication_date"])
        strong_dates = sorted({x["date"] for x in matches})
        near_matches = [
            x for x in matches
            if x["publication_distance_days"] is not None and -60 <= x["publication_distance_days"] <= 60
        ]
        near_dates = sorted({x["date"] for x in near_matches})
        fallback = s.near_transition_dates(text)
        fallback_dates = sorted({d for item in fallback for d in item.get("dates", [])})

        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["semantic_matches"] = matches[:80]
        rec["strong_dates"] = strong_dates
        rec["near_publication_strong_dates"] = near_dates
        rec["fallback_transition_dates"] = fallback_dates

        if len(near_dates) == 1:
            rec["status"] = "STRONG_UNIQUE_NEAR_PUBLICATION"
            rec["resolved_date"] = near_dates[0]
        elif len(near_dates) > 1:
            rec["status"] = "STRONG_MULTI_NEAR_PUBLICATION"
        elif len(strong_dates) == 1:
            rec["status"] = "STRONG_UNIQUE_OUTSIDE_NEAR_WINDOW"
            rec["resolved_date"] = strong_dates[0]
        elif len(strong_dates) > 1:
            rec["status"] = "STRONG_MULTI"
        elif fallback_dates:
            rec["status"] = "FALLBACK_ONLY_AMBIGUOUS"
        else:
            rec["status"] = "NO_SEMANTIC_DATE"
        records.append(rec)

    selected = len(records)
    downloaded = sum(1 for x in records if x.get("pdf_sha256"))
    text_ok = sum(1 for x in records if x.get("text_sha256"))
    unique_near = sum(1 for x in records if x["status"] == "STRONG_UNIQUE_NEAR_PUBLICATION")
    unique_any = sum(1 for x in records if str(x["status"]).startswith("STRONG_UNIQUE"))
    unresolved = selected - unique_any
    transport_complete = selected > 0 and downloaded == selected and text_ok == selected
    near_complete = selected > 0 and unique_near == selected

    by_class = {}
    for klass in sorted(TARGET_CLASSES):
        subset = [x for x in records if x["transition_title_class"] == klass]
        by_class[klass] = {
            "selected": len(subset),
            "pdf_downloaded": sum(1 for x in subset if x.get("pdf_sha256")),
            "text_extractable": sum(1 for x in subset if x.get("text_sha256")),
            "strong_unique_near_publication": sum(1 for x in subset if x["status"] == "STRONG_UNIQUE_NEAR_PUBLICATION"),
            "strong_unique_anywhere": sum(1 for x in subset if str(x["status"]).startswith("STRONG_UNIQUE")),
            "unresolved": sum(1 for x in subset if not str(x["status"]).startswith("STRONG_UNIQUE")),
        }

    status_counts = dict(sorted(Counter(x["status"] for x in records).items()))
    resolution_rows = [
        {
            "security_code": x.get("security_code"),
            "publication_date": x.get("publication_date"),
            "transition_title_class": x.get("transition_title_class"),
            "resolved_date": x.get("resolved_date"),
            "status": x.get("status"),
            "pdf_sha256": x.get("pdf_sha256"),
            "text_sha256": x.get("text_sha256"),
        }
        for x in records
    ]
    canonical = hashlib.sha256(
        json.dumps(resolution_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    report = {
        "schema": "stock-sse-primary-transition-semantic-resolver-v1",
        "source_window": {"begin": s.market.BEGIN, "end": s.market.END},
        "source_fetch_evidence": fetch_evidence,
        "method": {
            "title_classes": sorted(TARGET_CLASSES),
            "strong_pattern_count": len(IMPLEMENT_PATTERNS) + len(CANCEL_PATTERNS),
            "near_publication_window_days": 60,
            "policy": (
                "A document is diagnostically resolved only when class-specific transition wording yields one "
                "strong date candidate; the strongest class is exactly one candidate within +/-60 days of the "
                "publication date. This does not itself prove legal/effective daily state."
            ),
        },
        "summary": {
            "selected_documents": selected,
            "pdf_downloaded": downloaded,
            "text_extractable": text_ok,
            "strong_unique_near_publication": unique_near,
            "strong_unique_anywhere": unique_any,
            "unresolved": unresolved,
            "status_counts": status_counts,
            "by_class": by_class,
            "resolution_canonical_sha256": canonical,
        },
        "records": records,
        "adjudication": {
            "diagnostic_transport": "PASS" if transport_complete else "FAIL",
            "class_specific_semantic_disambiguation": "SUPPORTED_DIAGNOSTIC" if near_complete else "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "repository_independence": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "This diagnostic narrows primary-document dates with explicit class-specific wording and publication "
            "proximity. Any unresolved/multi-date document remains unresolved. Even 100% diagnostic resolution "
            "cannot promote historical ST/PIT until a deterministic daily state replay is independently cross-checked."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "summary": report["summary"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if transport_complete else 2

if __name__ == "__main__":
    raise SystemExit(main())
