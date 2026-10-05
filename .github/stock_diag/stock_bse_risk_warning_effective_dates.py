from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

CORPUS = Path("stock_bse_risk_warning_marketwide_corpus.json")
OUT = Path("stock_bse_risk_warning_effective_dates.json")
BSE_ROOT = "https://www.bse.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE effective-date validator"
RETRIES = 3

IMPLEMENTATION_MARKERS = (
    "将被实施退市风险警示",
    "被实施退市风险警示",
    "继续实施退市风险警示",
    "叠加实施退市风险警示",
)
POSSIBILITY_MARKERS = (
    "可能被实施退市风险警示",
    "可能被实施",
)

DATE_CORE = r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
STRONG_PATTERNS = [
    re.compile(
        rf"(?:自|于|从)\s*{DATE_CORE}\s*(?:开市|交易)?\s*起[^。；\n]{{0,100}}?"
        rf"(?:被|将被|继续|叠加)?\s*实施退市风险警示"
    ),
    re.compile(
        rf"(?:股票交易|公司股票|股票)[^。；\n]{{0,80}}?(?:自|于|从)\s*{DATE_CORE}\s*"
        rf"(?:开市|交易)?\s*起[^。；\n]{{0,100}}?(?:风险警示|退市风险警示)"
    ),
    re.compile(
        rf"(?:实施退市风险警示|退市风险警示)(?:的)?(?:实施|起始|开始)?"
        rf"(?:日|日期)[：:\s]*{DATE_CORE}"
    ),
    re.compile(
        rf"股票简称[^。；\n]{{0,40}}?(?:自|于|从)\s*{DATE_CORE}\s*起"
        rf"[^。；\n]{{0,80}}?\*ST"
    ),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def is_transition_title(title: str) -> bool:
    if any(marker in title for marker in POSSIBILITY_MARKERS):
        return False
    return any(marker in title for marker in IMPLEMENTATION_MARKERS)


def fetch_pdf(session: requests.Session, url: str):
    attempts = []
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/pdf,application/octet-stream,*/*",
                    "Referer": "https://www.bse.cn/disclosure/announcement.html",
                },
                timeout=(10, 40),
                allow_redirects=True,
            )
            meta = {
                "attempt": attempt,
                "status": r.status_code,
                "resolved_url": r.url,
                "content_type": r.headers.get("content-type"),
                "bytes": len(r.content),
                "sha256": sha256(r.content),
                "same_official_host": same_bse(r.url),
                "pdf_magic": r.content.startswith(b"%PDF-"),
            }
            attempts.append(meta)
            if (
                r.status_code == 200
                and r.content.startswith(b"%PDF-")
                and same_bse(r.url)
            ):
                return r.content, {"attempts": attempts, "selected_attempt": attempt}
        except Exception as exc:
            attempts.append({"attempt": attempt, "exception": f"{type(exc).__name__}: {exc}"})
        if attempt < RETRIES:
            time.sleep(float(attempt))
    return None, {"attempts": attempts, "selected_attempt": None}


def extract_pdf_text(payload: bytes):
    reader = PdfReader(io.BytesIO(payload))
    pages = []
    for page_no, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(text)
    joined = "\n".join(pages)
    normalized = re.sub(r"[ \t\u3000]+", " ", joined)
    normalized = re.sub(r"\r\n?", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip(), len(reader.pages)


def iso_date(y: str, m: str, d: str):
    value = date(int(y), int(m), int(d))
    return value.isoformat()


def context_slice(text: str, start: int, end: int, radius: int = 100):
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def extract_effective_date_candidates(text: str):
    matches = []
    for idx, pattern in enumerate(STRONG_PATTERNS):
        for m in pattern.finditer(text):
            try:
                value = iso_date(m.group(1), m.group(2), m.group(3))
            except Exception:
                continue
            matches.append({
                "date": value,
                "pattern_index": idx,
                "matched_text": re.sub(r"\s+", " ", m.group(0)).strip()[:260],
                "context": context_slice(text, m.start(), m.end())[:420],
            })

    # deterministic unique dates, preserving strongest (lowest pattern index) match
    by_date = {}
    for item in sorted(matches, key=lambda x: (x["pattern_index"], x["date"], x["matched_text"])):
        by_date.setdefault(item["date"], item)

    unique = [by_date[k] for k in sorted(by_date)]
    return unique


def main() -> int:
    if not CORPUS.exists():
        raise SystemExit("missing corpus evidence; run stock_bse_risk_warning_marketwide_corpus.py first")

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    events = corpus.get("combined_events") or []
    selected = [event for event in events if is_transition_title(str(event.get("title") or ""))]

    session = requests.Session()
    results = []
    all_pass = bool(selected)

    for event in selected:
        path = str(event.get("destFilePath") or "").strip()
        url = urljoin(BSE_ROOT + "/", path.lstrip("/"))
        payload, transport = fetch_pdf(session, url)

        result = {
            "canonical_company_code": event.get("canonical_company_code"),
            "raw_company_code": event.get("raw_company_code"),
            "publishDate": event.get("publishDate"),
            "title": event.get("title"),
            "destFilePath": path,
            "url": url,
            "transport": transport,
            "status": "NOT VERIFIED",
            "effective_date": None,
            "candidate_dates": [],
            "pdf_page_count": None,
            "pdf_text_sha256": None,
            "publish_date_order_check": "NOT VERIFIED",
        }

        if payload is None:
            all_pass = False
            results.append(result)
            continue

        try:
            text, page_count = extract_pdf_text(payload)
        except Exception as exc:
            result["pdf_parse_error"] = f"{type(exc).__name__}: {exc}"
            all_pass = False
            results.append(result)
            continue

        result["pdf_page_count"] = page_count
        result["pdf_text_sha256"] = sha256(text.encode("utf-8"))
        result["pdf_text_chars"] = len(text)
        candidates = extract_effective_date_candidates(text)
        result["candidate_dates"] = candidates

        unique_dates = sorted({x["date"] for x in candidates})
        if len(unique_dates) == 1:
            effective = unique_dates[0]
            result["effective_date"] = effective
            pub = str(event.get("publishDate") or "")[:10]
            try:
                order_ok = date.fromisoformat(effective) >= date.fromisoformat(pub)
            except Exception:
                order_ok = False
            result["publish_date_order_check"] = "PASS" if order_ok else "FAIL"
            if order_ok:
                result["status"] = "PASS"

        all_pass = all_pass and result["status"] == "PASS"
        results.append(result)

    pass_count = sum(1 for x in results if x["status"] == "PASS")
    unique_codes = sorted({str(x.get("canonical_company_code") or "") for x in results if x.get("canonical_company_code")})

    adjudication = {
        "bse_transition_announcement_denominator": "PASS" if selected else "NOT VERIFIED",
        "bse_primary_pdf_fetch_and_parse": "PASS" if results and all(
            x.get("transport", {}).get("selected_attempt") and x.get("pdf_text_sha256")
            for x in results
        ) else "NOT VERIFIED",
        "bse_implementation_effective_date_evidence": "SUPPORTED" if all_pass else "NOT VERIFIED",
        "bse_effective_state_reconstruction": "NOT VERIFIED",
        "bse_removal_event_history": "NOT VERIFIED",
        "bse_historical_st_pit": "NOT VERIFIED",
        "bse_historical_suspension_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "product_bytes_changed": False,
        "final_gate": "FAIL",
    }

    report = {
        "schema": "stock-bse-risk-warning-effective-date-pdfs-v1",
        "source_corpus_schema": corpus.get("schema"),
        "source_corpus_sha256": corpus.get("combined_canonical_sha256"),
        "source_corpus_event_count": corpus.get("combined_unique_title_event_count"),
        "transition_selection": {
            "implementation_markers": IMPLEMENTATION_MARKERS,
            "possibility_markers_excluded": POSSIBILITY_MARKERS,
            "selected_count": len(selected),
            "canonical_company_codes": unique_codes,
        },
        "results": results,
        "summary": {
            "selected_count": len(results),
            "pass_count": pass_count,
            "not_verified_count": len(results) - pass_count,
        },
        "adjudication": adjudication,
        "boundary": (
            "This diagnostic validates explicit effective-date text only for the frozen BSE risk-warning "
            "implementation/continuation announcements selected from the exhaustive keyword corpus. "
            "Publication dates are never substituted for effective dates. Missing removal-event history, "
            "daily ST identity, suspension state, and full PIT reconstruction remain NOT VERIFIED."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "schema": report["schema"],
        "source_corpus_sha256": report["source_corpus_sha256"],
        "selected_count": len(results),
        "pass_count": pass_count,
        "effective_dates": {
            str(x.get("canonical_company_code")) + "@" + str(x.get("publishDate")): x.get("effective_date")
            for x in results
        },
        "adjudication": adjudication,
    }, ensure_ascii=True, sort_keys=True))

    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
