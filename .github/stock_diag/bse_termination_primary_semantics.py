from __future__ import annotations

import argparse
from datetime import date
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
CORPUS_PATH = HERE / "bse_termination_event_corpus.py"
EXPECTED_CORPUS_SHA256 = "6c2e2a6cda9f857ef0ec88f961164cc98cf57309032f940d075a5177b19ed86c"
BSE_ROOT = "https://www.bse.cn/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE primary semantics"

DATE = r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
PATTERNS = [
    (
        "TERMINATION_DATE_LABEL",
        re.compile(
            r"(?:终止上市(?:日期|日|时间|之日)|摘牌(?:日期|日|时间))"
            r"\s*[：:]?\s*" + DATE
        ),
        "terminal",
    ),
    (
        "DATE_TO_TERMINATION",
        re.compile(
            r"(?:自|于|从)\s*" + DATE +
            r"\s*(?:起|开市起|交易起)?[^。；\n]{0,140}(?:终止上市|摘牌)"
        ),
        "terminal",
    ),
    (
        "DATE_THEN_TERMINATION",
        re.compile(
            DATE +
            r"[^。；\n]{0,120}(?:起|开市起|交易起)?[^。；\n]{0,100}(?:终止上市|摘牌)"
        ),
        "terminal",
    ),
    (
        "DELISTING_PERIOD_START_LABEL",
        re.compile(
            r"(?:退市整理期(?:交易)?(?:起始日|开始日|首个交易日)"
            r"|进入退市整理期交易(?:的)?(?:起始日|首个交易日))"
            r"\s*[：:]?\s*" + DATE
        ),
        "period_start",
    ),
    (
        "DATE_TO_DELISTING_PERIOD",
        re.compile(
            r"(?:自|于|从)\s*" + DATE +
            r"\s*(?:起|开市起|交易起)?[^。；\n]{0,140}(?:进入|开始)(?:股票)?退市整理期"
        ),
        "period_start",
    ),
    (
        "DELISTING_PERIOD_END_LABEL",
        re.compile(
            r"(?:退市整理期(?:交易)?(?:最后交易日|结束日|截止日)"
            r"|退市整理期交易的最后交易日)"
            r"\s*[：:]?\s*" + DATE
        ),
        "period_end",
    ),
    (
        "DATE_AS_LAST_DELISTING_PERIOD_DAY",
        re.compile(
            DATE +
            r"[^。；\n]{0,120}(?:为|是)[^。；\n]{0,80}退市整理期(?:交易)?(?:最后交易日|结束日)"
        ),
        "period_end",
    ),
]

# Dates of disclosures, notices, decisions, hearings or other historical
# documents are not terminal-listing effective dates merely because the
# surrounding title/text mentions termination. Direct date->terminal rules
# must reject those non-effective contexts. Explicit terminal-date labels
# remain independently admissible.
TERMINAL_NON_EFFECTIVE_CONTEXT_RE = re.compile(
    r"(?:披露|发布|刊登|风险提示|收到|获悉|作出|审议|决定)"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def iso_date(groups: tuple[str, str, str]) -> str:
    y, m, d = (int(x) for x in groups)
    return date(y, m, d).isoformat()


def extract_semantic_hits(text: str) -> list[dict]:
    hits = []
    for rule, pattern, role in PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()[-3:]
            try:
                dt = iso_date(groups)
            except Exception:
                continue
            matched = re.sub(r"\s+", " ", match.group(0)).strip()
            if role == "terminal" and rule in {"DATE_TO_TERMINATION", "DATE_THEN_TERMINATION"}:
                term_positions = [
                    pos for pos in (matched.find("终止上市"), matched.find("摘牌"))
                    if pos >= 0
                ]
                if term_positions:
                    before_terminal = matched[:min(term_positions)]
                    if TERMINAL_NON_EFFECTIVE_CONTEXT_RE.search(before_terminal):
                        continue
            left = max(0, match.start() - 180)
            right = min(len(text), match.end() + 260)
            context = re.sub(r"\s+", " ", text[left:right]).strip()
            hits.append({
                "rule": rule,
                "role": role,
                "date": dt,
                "context_sha256": sha256_bytes(context.encode("utf-8")),
            })
    dedup = {}
    for hit in hits:
        key = (hit["rule"], hit["role"], hit["date"], hit["context_sha256"])
        dedup[key] = hit
    return [dedup[k] for k in sorted(dedup)]


def corpus_rows(corpus) -> list[dict]:
    session = requests.Session()
    type_contract = corpus.fetch_type_contract(session)
    if not type_contract.get("type_5_present"):
        raise RuntimeError("official disclosure type 5 prerequisite failed")

    combined = {}
    for keyword in corpus.KEYWORDS:
        raw0, transport0, obj0, mode0 = corpus.fetch_page(session, keyword, 0)
        meta0 = corpus.page_meta(obj0)
        total_pages = int(meta0["totalPages"])
        total_elements = int(meta0["totalElements"])
        page_size = int(meta0["size"])
        unique = {}

        for page_no in range(total_pages):
            if page_no == 0:
                obj = obj0
            else:
                _raw, _transport, obj, _mode = corpus.fetch_page(session, keyword, page_no)
            meta = corpus.page_meta(obj)
            if int(meta.get("number", -1)) != page_no:
                raise RuntimeError(f"{keyword}: page number mismatch")
            if int(meta.get("totalPages", -1)) != total_pages:
                raise RuntimeError(f"{keyword}: totalPages drift")
            if int(meta.get("totalElements", -1)) != total_elements:
                raise RuntimeError(f"{keyword}: totalElements drift")
            if int(meta.get("size", -1)) != page_size:
                raise RuntimeError(f"{keyword}: page size drift")
            records = corpus.walk_records(obj)
            if int(meta.get("numberOfElements", -1)) != len(records):
                raise RuntimeError(f"{keyword}: numberOfElements mismatch")
            for row in records:
                unique[corpus.row_id(row)] = row

        if len(unique) != total_elements:
            raise RuntimeError(f"{keyword}: unique row denominator mismatch")

        for row in (corpus.row_view(unique[k], keyword) for k in sorted(unique)):
            if not row["exact_keyword_in_title"]:
                continue
            key = (
                row["companyCd"],
                str(row["publishDate"]),
                row["title"],
                str(row["destFilePath"]),
            )
            combined[key] = row

    rows = [combined[k] for k in sorted(combined)]
    canonical = (
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in rows
        )
        + ("\n" if rows else "")
    ).encode("utf-8")
    actual = sha256_bytes(canonical)
    if actual != EXPECTED_CORPUS_SHA256:
        raise RuntimeError(
            f"event corpus drift: expected={EXPECTED_CORPUS_SHA256}, actual={actual}"
        )
    return rows


def fetch_doc(session: requests.Session, url: str) -> tuple[bytes, dict]:
    attempts = []
    last_error = None
    for attempt in range(1, 4):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/pdf,text/html,text/plain,*/*",
                    "Referer": "https://www.bse.cn/disclosure/announcement.html",
                },
                timeout=(15, 45),
                allow_redirects=True,
            )
            rec = {
                "attempt": attempt,
                "status": int(r.status_code),
                "resolved_url": r.url,
                "content_type": str(r.headers.get("Content-Type") or ""),
                "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
            }
            attempts.append(rec)
            if (
                same_bse(r.url)
                and r.status_code == 200
                and r.content
            ):
                return r.content, {**rec, "attempt_count": attempt, "attempts": attempts}
            # Preserve inaccessible primary documents as transport evidence.
            # BSE is rate-limit sensitive: a short retry loop after 403/429
            # deterministically reproduces the block. Use the same bounded
            # cooldown proven by the 85/85 suspension-primary diagnostic.
            if r.status_code in {403, 429} and attempt < 3:
                time.sleep(75.0)
                continue
        except requests.RequestException as exc:
            last_error = exc
            attempts.append({
                "attempt": attempt,
                "transport_error": f"{type(exc).__name__}: {exc}",
            })
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    return None, {
        "attempt_count": len(attempts),
        "attempts": attempts,
        "selected_attempt": None,
        "last_error": repr(last_error) if last_error is not None else None,
    }


def text_from_document(raw: bytes, content_type: str) -> tuple[str, dict]:
    if raw.startswith(b"%PDF") or "pdf" in content_type.lower():
        reader = PdfReader(io.BytesIO(raw))
        chunks = []
        nonempty = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                nonempty += 1
            chunks.append(text)
        joined = "\n".join(chunks)
        if not joined.strip():
            raise RuntimeError("PDF has no extractable text; OCR is not substituted")
        return joined, {
            "mode": "PDF_TEXT",
            "page_count": len(reader.pages),
            "nonempty_text_pages": nonempty,
        }

    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError("non-PDF document is not decodable text")

    # Plain, deterministic tag stripping; this is not used as semantic proof by itself.
    stripped = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    stripped = re.sub(r"(?is)<style\b.*?</style>", " ", stripped)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    stripped = re.sub(r"&nbsp;|&#160;", " ", stripped)
    if not stripped.strip():
        raise RuntimeError("non-PDF document has no extractable text")
    return stripped, {"mode": "TEXT_OR_HTML"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    corpus = load_module("bse_termination_corpus", CORPUS_PATH)
    events = corpus_rows(corpus)
    if len(events) != 56:
        raise RuntimeError(f"expected frozen 56-event corpus, got {len(events)}")

    unique_docs = {}
    for event in events:
        path = str(event.get("destFilePath") or "").strip()
        if not path:
            raise RuntimeError(f"event missing destFilePath: {event}")
        url = path if path.startswith("http") else urljoin(BSE_ROOT, path.lstrip("/"))
        if not same_bse(url):
            raise RuntimeError(f"event points off BSE: {url}")
        unique_docs.setdefault(url, []).append(event)

    session = requests.Session()
    documents = []
    fetch_pass = 0
    parse_pass = 0
    terminal_supported = 0
    terminal_ambiguous = 0
    role_counts = {"terminal": 0, "period_start": 0, "period_end": 0}

    for index, url in enumerate(sorted(unique_docs)):
        # Proven BSE transport hygiene from the suspension-primary corpus:
        # reset the session and cool down before the next 20-document batch.
        # This changes only acquisition pacing, never semantic acceptance.
        if index > 0 and index % 20 == 0:
            session.close()
            time.sleep(75.0)
            session = requests.Session()

        events_for_doc = unique_docs[url]
        raw, transport = fetch_doc(session, url)
        rec = {
            "url": url,
            "event_count": len(events_for_doc),
            "events": events_for_doc,
            "raw_path": None,
            "transport": transport,
            "parse_status": "NOT VERIFIED",
            "semantic_hits": [],
            "terminal_date_status": "NOT VERIFIED",
            "terminal_dates": [],
            "period_start_dates": [],
            "period_end_dates": [],
        }
        if raw is None:
            rec["fetch_status"] = "FAIL"
            documents.append(rec)
            continue

        suffix = ".pdf" if raw.startswith(b"%PDF") else ".raw"
        raw_path = args.raw_dir / f"{index:03d}_{sha256_bytes(url.encode())[:12]}{suffix}"
        raw_path.write_bytes(raw)
        rec["raw_path"] = raw_path.as_posix()
        rec["fetch_status"] = "PASS"
        fetch_pass += 1

        try:
            selected_transport = transport
            content_type = ""
            if isinstance(selected_transport, dict):
                content_type = str(selected_transport.get("content_type") or "")
            text, parse_meta = text_from_document(raw, content_type)
            hits = extract_semantic_hits(text)
            text_hash = sha256_bytes(text.encode("utf-8"))
            parse_pass += 1
            rec["parse_status"] = "PASS"
            rec["parse"] = {**parse_meta, "text_sha256": text_hash}
            rec["semantic_hits"] = hits

            terminal_dates = sorted({h["date"] for h in hits if h["role"] == "terminal"})
            period_start_dates = sorted({h["date"] for h in hits if h["role"] == "period_start"})
            period_end_dates = sorted({h["date"] for h in hits if h["role"] == "period_end"})
            rec["terminal_dates"] = terminal_dates
            rec["period_start_dates"] = period_start_dates
            rec["period_end_dates"] = period_end_dates

            for role in role_counts:
                role_counts[role] += sum(1 for h in hits if h["role"] == role)

            if len(terminal_dates) == 1:
                rec["terminal_date_status"] = "SUPPORTED_UNIQUE_PRIMARY_DATE"
                rec["terminal_date"] = terminal_dates[0]
                terminal_supported += 1
            elif len(terminal_dates) > 1:
                rec["terminal_date_status"] = "MULTI_DATE_AMBIGUOUS"
                terminal_ambiguous += 1
            else:
                rec["terminal_date_status"] = "NO_STRONG_TERMINAL_DATE"
        except Exception as exc:
            rec["parse_error"] = f"{type(exc).__name__}: {exc}"
        documents.append(rec)

    company_terminal_candidates = {}
    for doc in documents:
        if doc.get("terminal_date_status") != "SUPPORTED_UNIQUE_PRIMARY_DATE":
            continue
        for event in doc["events"]:
            code = str(event.get("companyCd") or "").strip()
            if not code:
                continue
            company_terminal_candidates.setdefault(code, set()).add(doc["terminal_date"])

    company_terminal_projection = []
    company_conflicts = 0
    for code in sorted(company_terminal_candidates):
        dates = sorted(company_terminal_candidates[code])
        status = "SUPPORTED_UNIQUE_PRIMARY_DATE" if len(dates) == 1 else "CONFLICT"
        if status == "CONFLICT":
            company_conflicts += 1
        company_terminal_projection.append({
            "companyCd": code,
            "dates": dates,
            "status": status,
        })

    report = {
        "schema": "stock-bse-termination-primary-semantics-v1",
        "status": "PASS" if fetch_pass == len(unique_docs) else "NOT VERIFIED",
        "scope": "primary-document semantics for frozen 56-event BSE termination phrase corpus",
        "product_bytes_changed": False,
        "event_corpus_sha256": EXPECTED_CORPUS_SHA256,
        "event_count": len(events),
        "unique_document_count": len(unique_docs),
        "document_fetch_pass_count": fetch_pass,
        "document_parse_pass_count": parse_pass,
        "document_unique_terminal_date_count": terminal_supported,
        "document_multi_terminal_date_count": terminal_ambiguous,
        "semantic_hit_role_counts": role_counts,
        "company_terminal_projection_count": len(company_terminal_projection),
        "company_terminal_conflict_count": company_conflicts,
        "company_terminal_projection": company_terminal_projection,
        "documents": documents,
        "adjudication": {
            "frozen_56_event_corpus_identity": "PASS",
            "primary_document_fetch": "PASS" if fetch_pass == len(unique_docs) else "NOT VERIFIED",
            "primary_document_text_parse": (
                "PASS" if parse_pass == len(unique_docs) else "PARTIAL"
            ),
            "strong_terminal_date_semantics": (
                "SUPPORTED" if terminal_supported > 0 else "NOT VERIFIED"
            ),
            "bse_terminal_company_projection": (
                "SUPPORTED" if company_terminal_projection and company_conflicts == 0
                else "NOT VERIFIED"
            ),
            "bse_delisting_event_vocabulary_complete": "NOT VERIFIED",
            "bse_delisting_removal_lifecycle_complete": "NOT VERIFIED",
            "bse_historical_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_pit_availability": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "Only explicit semantic dates in primary BSE documents are promoted. Publication dates "
            "are never substituted. A unique date is supported only within that document and frozen "
            "56-event phrase corpus. Phrase vocabulary completeness, all historical BSE securities, "
            "daily PIT state and Final remain non-PASS."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "event_count": report["event_count"],
        "unique_document_count": report["unique_document_count"],
        "document_fetch_pass_count": fetch_pass,
        "document_parse_pass_count": parse_pass,
        "document_unique_terminal_date_count": terminal_supported,
        "document_multi_terminal_date_count": terminal_ambiguous,
        "semantic_hit_role_counts": role_counts,
        "company_terminal_projection_count": len(company_terminal_projection),
        "company_terminal_conflict_count": company_conflicts,
        "company_terminal_projection": company_terminal_projection,
        "fetch_failures": [
            {
                "url": doc["url"],
                "attempts": doc.get("transport", {}).get("attempts"),
            }
            for doc in documents
            if doc.get("fetch_status") != "PASS"
        ],
        "parse_failures": [
            {
                "url": doc["url"],
                "error": doc.get("parse_error"),
            }
            for doc in documents
            if doc.get("fetch_status") == "PASS" and doc.get("parse_status") != "PASS"
        ],
        "adjudication": report["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if fetch_pass == len(unique_docs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
