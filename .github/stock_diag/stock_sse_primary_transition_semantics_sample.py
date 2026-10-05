from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent

def load_module(filename: str, name: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

market = load_module("stock_sse_marketwide_risk_warning_history.py", "marketwide")
inventory = load_module("stock_sse_risk_warning_transition_inventory.py", "transition_inventory")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
STATIC_BASE = "https://static.sse.com.cn"
WWW_BASE = "https://www.sse.com.cn"
BIG5_BASE = "https://big5.sse.com.cn/site/cht/www.sse.com.cn"

DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
TRANSITION_RE = re.compile(
    r"(实施退市风险警示|实施其他风险警示|撤销退市风险警示|撤销其他风险警示|"
    r"撤销股票退市风险警示|撤销股票其他风险警示|股票简称变更|证券简称变更)"
)
TARGET_CLASSES = {"actual_implementation_candidate", "actual_cancel_candidate"}

def candidate_urls(path: str) -> list[str]:
    if path.startswith("http://") or path.startswith("https://"):
        return [path]
    rel = path.lstrip("/")
    return [
        urljoin(STATIC_BASE + "/", rel),
        urljoin(WWW_BASE + "/", rel),
        urljoin(BIG5_BASE + "/", rel),
    ]

def fetch_pdf(session: requests.Session, url: str, attempts: int = 2):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={"User-Agent": UA, "Referer": REFERER, "Accept": "application/pdf,*/*;q=0.8"},
                timeout=(8, 35),
                allow_redirects=True,
            )
            if r.status_code in {403, 429} or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty body")
            return r, {
                "attempt": attempt,
                "prior_errors": errors,
                "http_status": r.status_code,
                "payload_sha256": hashlib.sha256(r.content).hexdigest(),
                "content_type": r.headers.get("Content-Type"),
                "final_url": r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.5 * attempt)
    raise RuntimeError("unreachable")

def extract_text(raw: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages), len(reader.pages)

def near_transition_dates(text: str) -> list[dict]:
    out = []
    compact = re.sub(r"\s+", "", text or "")
    for match in TRANSITION_RE.finditer(compact):
        start = max(0, match.start() - 260)
        end = min(len(compact), match.end() + 360)
        segment = compact[start:end]
        dates = []
        for d in DATE_RE.finditer(segment):
            y, mo, day = map(int, d.groups())
            dates.append(f"{y:04d}-{mo:02d}-{day:02d}")
        out.append({
            "transition": match.group(1),
            "dates": sorted(set(dates)),
            "snippet_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
        })
        if len(out) >= 20:
            break
    return out

def build_corpus(session: requests.Session):
    combined = {}
    for label, keyword in market.KEYWORDS:
        item = market.fetch_keyword(session, label, keyword)
        for row in item["records"]:
            ident = market.identity(row)
            if ident not in combined:
                combined[ident] = dict(row)
    return [combined[k] for k in sorted(combined)]

def stratified_sample(corpus: list[dict], per_class_year: int = 2):
    buckets = defaultdict(list)
    for row in corpus:
        klass = inventory.classify(row.get("title") or "")
        if klass not in TARGET_CLASSES:
            continue
        date = str(row.get("date") or "")
        year = date[:4] if len(date) >= 4 else "unknown"
        buckets[(klass, year)].append(row)
    selected = []
    bucket_counts = {}
    for key in sorted(buckets):
        values = sorted(
            buckets[key],
            key=lambda x: (
                str(x.get("date") or ""),
                str(x.get("security_code") or ""),
                str(x.get("url") or ""),
            ),
        )
        bucket_counts[f"{key[0]}|{key[1]}"] = len(values)
        if len(values) <= per_class_year:
            picks = values
        else:
            picks = [values[0], values[-1]]
        selected.extend(({**row, "transition_title_class": key[0], "year": key[1]} for row in picks))
    return selected, bucket_counts

def main() -> int:
    session = requests.Session()
    corpus = build_corpus(session)
    selected, bucket_counts = stratified_sample(corpus)

    records = []
    for row in selected:
        rec = {
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "date": row.get("date"),
            "title": row.get("title"),
            "url": row.get("url"),
            "transition_title_class": row.get("transition_title_class"),
            "year": row.get("year"),
            "status": "NOT VERIFIED",
            "attempts": [],
        }
        raw = None
        for url in candidate_urls(str(row.get("url") or "")):
            try:
                response, meta = fetch_pdf(session, url)
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
            text, pages = extract_text(raw)
        except Exception as exc:
            rec["status"] = "TEXT_NOT_VERIFIED"
            rec["extract_error"] = f"{type(exc).__name__}: {exc}"
            records.append(rec)
            continue

        transitions = near_transition_dates(text)
        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["transition_evidence"] = transitions
        rec["has_transition_term"] = bool(transitions)
        rec["has_explicit_date_near_transition"] = any(x["dates"] for x in transitions)
        rec["status"] = "PASS" if rec["has_explicit_date_near_transition"] else "TEXT_NO_EXPLICIT_TRANSITION_DATE"
        records.append(rec)

    by_class = {}
    for klass in sorted(TARGET_CLASSES):
        subset = [x for x in records if x["transition_title_class"] == klass]
        by_class[klass] = {
            "sampled": len(subset),
            "pdf_downloaded": sum(1 for x in subset if x.get("pdf_sha256")),
            "text_transition_term": sum(1 for x in subset if x.get("has_transition_term")),
            "explicit_date_near_transition": sum(1 for x in subset if x.get("has_explicit_date_near_transition")),
        }

    sampled = len(records)
    downloaded = sum(1 for x in records if x.get("pdf_sha256"))
    explicit = sum(1 for x in records if x.get("has_explicit_date_near_transition"))
    years = sorted({str(x.get("year")) for x in records})
    feasibility_supported = (
        sampled > 0
        and downloaded >= max(2, sampled // 2)
        and all(by_class[k]["pdf_downloaded"] > 0 for k in TARGET_CLASSES)
        and explicit >= 2
    )

    report = {
        "schema": "stock-sse-primary-transition-semantics-sample-v1",
        "window": {"begin": market.BEGIN, "end": market.END},
        "corpus": {
            "unique_a_share_event_rows": len(corpus),
            "canonical_sha256": market.canonical_sha(corpus),
            "candidate_bucket_counts": bucket_counts,
        },
        "sample": {
            "strategy": "deterministic first-and-last per transition-class/year bucket",
            "years": years,
            "sampled_documents": sampled,
            "pdf_downloaded": downloaded,
            "explicit_date_near_transition": explicit,
            "by_class": by_class,
            "records": records,
        },
        "adjudication": {
            "primary_document_sampling_feasibility": "SUPPORTED" if feasibility_supported else "NOT VERIFIED",
            "sample_semantics_supported": "SUPPORTED_SAMPLE_ONLY" if explicit >= 2 else "NOT VERIFIED",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This is a deterministic stratified sample of primary SSE documents for validating whether explicit "
            "implementation/cancellation dates can be extracted. It cannot promote market-wide transition semantics, "
            "historical ST point-in-time state, Advanced Business, or Final Gate."
        ),
    }
    Path("stock_sse_primary_transition_semantics_sample.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "sample": {k: v for k, v in report["sample"].items() if k != "records"},
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if feasibility_supported else 2

if __name__ == "__main__":
    raise SystemExit(main())
\n# exact-head trigger: 2026-10-06\n