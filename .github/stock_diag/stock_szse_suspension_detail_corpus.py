from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "stock_szse_suspension_static_archive.py"
OUT = Path("stock_szse_suspension_detail_corpus.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
MAX_WORKERS = 8
MAX_ATTEMPTS = 3


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def same_szse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "szse.cn" or host.endswith(".szse.cn")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_response(r: requests.Response) -> str:
    """Strictly decode first-party HTML. Never trust heuristic Cyrillic detection.

    Some valid UTF-8 SZSE pages with missing Content-Type charset were
    previously decoded via chardet as windows-1251, losing all Chinese topic
    terms while HTTP/response SHA remained valid. Retain raw-byte evidence.
    Non-UTF8 bytes require an explicit GB-family source charset declaration.
    """
    raw = r.content
    if not raw:
        raise RuntimeError("empty official source bytes")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as original:
        header = str(r.encoding or "").lower().replace("_", "-").strip()
        match = re.search(rb"charset\\s*=\\s*['\\\"]?([a-zA-Z0-9_\\-]+)", raw[:4096], flags=re.I)
        declared = match.group(1).decode("ascii", errors="ignore").lower() if match else ""
        accepted_gb = {"gbk", "gb2312", "gb18030", "gb-2312", "cp936"}
        if header in accepted_gb or declared in accepted_gb:
            try:
                return raw.decode("gb18030", errors="strict")
            except UnicodeDecodeError as exc:
                raise RuntimeError("declared GB-family HTML is not valid GB18030") from exc
        raise RuntimeError("non-UTF8 official HTML without supported declared charset") from original


# Never count global navigation, footer, sidebar or arbitrary whole-page text
# as first-party announcement content. Unrecognized layouts remain NOT VERIFIED.
ARTICLE_SELECTORS = (
    # Verified 2026-06-26 first-party HTML: #desContent is nested below
    # .news-detail-con; do not accept an identically named page-chrome node.
    ".news-detail-con #desContent", ".news-detail-con .des-content",
    "article", "[itemprop='articleBody']", "#article", "#articleContent",
    ".article-content", ".articleContent", ".news-content", "#news-content",
    ".news-con", ".newsCon", ".u-content", ".m-con", ".content-article",
    ".article", ".txt-content", ".content", "#content",
)
ARTICLE_TERMS = ("停牌", "复牌", "暂停交易", "恢复交易")


def extract_primary_article(soup: BeautifulSoup) -> tuple[str, str | None]:
    for selector in ARTICLE_SELECTORS:
        for candidate in soup.select(selector):
            ancestor = candidate
            excluded = False
            while ancestor is not None:
                if getattr(ancestor, "name", None) in {"nav", "header", "footer", "aside"}:
                    excluded = True
                    break
                classes = set(ancestor.get("class", [])) if hasattr(ancestor, "get") else set()
                if classes & {"nav", "menu", "footer", "sidebar", "breadcrumb", "related"}:
                    excluded = True
                    break
                ancestor = ancestor.parent
            if excluded:
                continue
            # Work on an isolated copy: never mutate evidence used by title parsing.
            scoped = BeautifulSoup(str(candidate), "html.parser")
            for non_body in scoped.select(
                "nav, header, footer, aside, script, style, form, "
                ".breadcrumb, .breadcrumbs, .nav, .menu, .footer, "
                ".related, .sidebar, .pagination"
            ):
                non_body.decompose()
            body = re.sub(r"\s+", "", scoped.get_text("\n", strip=True))
            # A generic container and a page title alone are not primary text.
            if len(body) >= 25 and any(term in body for term in ARTICLE_TERMS):
                return body, selector
    return "", None


def fetch_one(item: dict) -> dict:
    url = str(item["url"])
    errors = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://www.szse.cn/disclosure/notice/temp/",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            meta = {
                "attempt": attempt,
                "http_status": r.status_code,
                "resolved_url": str(r.url),
                "same_official_host": same_szse(str(r.url)),
                "bytes": len(r.content),
                "sha256": sha256(r.content) if r.content else None,
            }
            if r.status_code in {403, 429} or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty detail payload")
            if not same_szse(str(r.url)):
                raise RuntimeError(f"detail redirect left official SZSE host: {r.url}")

            # Forensic snapshots from *actual* batch-success source path: preserve
            # exact first-party bytes, not a guessed article body or synthesized DOM.
            # These samples cannot promote the full-corpus or historical PIT gates.
            sample_names = {
                "t20180102_507883.html": "stock_szse_primary_sample_20180102.html",
                "t20260930_623154.html": "stock_szse_primary_sample_20260930.html",
            }
            for suffix, filename in sample_names.items():
                if url.endswith("/" + suffix):
                    Path(filename).write_bytes(r.content)
            text = decode_response(r)
            soup = BeautifulSoup(text, "html.parser")
            compact, article_source = extract_primary_article(soup)

            title_candidates = []
            for tag in ("h1", "h2", "h3", "title"):
                for node in soup.find_all(tag):
                    value = " ".join(node.get_text(" ", strip=True).split())
                    if value:
                        title_candidates.append(value)
            for attrs in (
                {"name": "ArticleTitle"},
                {"name": "title"},
                {"property": "og:title"},
            ):
                node = soup.find("meta", attrs=attrs)
                if node and node.get("content"):
                    title_candidates.append(" ".join(str(node.get("content")).split()))
            title_candidates = list(dict.fromkeys(x for x in title_candidates if x))
            title = max(title_candidates, key=len) if title_candidates else None

            # Literal six-digit security codes only; do not infer from article ID.
            codes = sorted(set(re.findall(r"(?<!\d)(?:000|001|002|003|300|301|200|201|120|123|125|126|127|128|129)\d{3}(?!\d)", compact)))
            stop_terms = sorted(set(t for t in ("临时停牌", "停牌", "暂停交易") if t in compact))
            resume_terms = sorted(set(t for t in ("复牌", "恢复交易") if t in compact))

            # Keep a bounded, hash-bound body sample around the first stop/resume term.
            positions = [compact.find(t) for t in stop_terms + resume_terms if compact.find(t) >= 0]
            if positions:
                pos = min(positions)
                lo = max(0, pos - 350)
                hi = min(len(compact), pos + 700)
                semantic_sample = compact[lo:hi]
            else:
                semantic_sample = compact[:1000]

            return {
                "archive_date": item["date"],
                "url": url,
                "archive_identity_source": item.get("identity_source"),
                "transport": {**meta, "status": "PASS", "prior_errors": errors},
                "title": title,
                "title_candidates": title_candidates[:12],
                "article_body_status": "PASS" if article_source else "NOT VERIFIED",
                "article_source": article_source,
                "body_text_chars": len(compact),
                "body_text_sha256": sha256(compact.encode("utf-8")),
                "security_codes": codes,
                "stop_terms": stop_terms,
                "resume_terms": resume_terms,
                "semantic_sample_sha256": sha256(semantic_sample.encode("utf-8")),
                "semantic_sample": semantic_sample[:1200],
                "status": "PASS",
            }
        except Exception as exc:
            errors.append({"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
            if attempt < MAX_ATTEMPTS:
                time.sleep(1.0 * (2 ** (attempt - 1)))
    return {
        "archive_date": item["date"],
        "url": url,
        "status": "NOT VERIFIED",
        "errors": errors,
    }



def retry_unverified(records, fetch_fn=None, sleep_fn=None, max_retry_items=200):
    """Bounded low-concurrency second pass; preserve both attempts and all gaps."""
    fetch_fn = fetch_fn or fetch_one
    sleep_fn = sleep_fn or time.sleep
    pending = [i for i, row in enumerate(records) if row.get("status") != "PASS"]
    result = {
        "first_pass_unverified": len(pending),
        "second_pass_attempted": 0,
        "second_pass_recovered": 0,
        "retry_cap": max_retry_items,
        "retry_cap_exceeded": len(pending) > max_retry_items,
        "cooldown_seconds": 20,
        "batch_size": 15,
        "recovery_workers": 2,
    }
    if not pending or len(pending) > max_retry_items:
        return records, result

    sleep_fn(20)
    for start in range(0, len(pending), 15):
        batch = pending[start : start + 15]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(
                    fetch_fn,
                    {
                        "date": records[i]["archive_date"],
                        "url": records[i]["url"],
                        "identity_source": records[i].get("archive_identity_source"),
                    },
                ): i
                for i in batch
            }
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                original = records[idx]
                replay = future.result()
                result["second_pass_attempted"] += 1
                # Original transport failures are audit evidence, not discarded.
                replay["first_pass"] = {
                    "status": original.get("status"),
                    "errors": original.get("errors", []),
                }
                replay["recovery_attempted"] = True
                if replay.get("status") == "PASS":
                    result["second_pass_recovered"] += 1
                records[idx] = replay
        if start + len(batch) < len(pending):
            sleep_fn(10)
    return records, result


def canonical_sha(rows) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload)


def main() -> int:
    archive = load_module("szse_archive", ARCHIVE)
    rc = archive.main()
    if rc not in (0, None):
        raise RuntimeError(f"archive rebuild failed rc={rc}")
    source = json.loads(Path("stock_szse_suspension_static_archive.json").read_text(encoding="utf-8"))
    links = source["corpus"]["events"]
    expected = int(source["corpus"]["event_rows"])
    if expected != len(links) or expected <= 0:
        raise RuntimeError(f"source link denominator mismatch: expected={expected} actual={len(links)}")

    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(fetch_one, item) for item in links]
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())

    records, network_recovery = retry_unverified(records)

    records.sort(key=lambda x: (str(x.get("archive_date") or ""), str(x.get("url") or "")))
    passed = [x for x in records if x.get("status") == "PASS"]
    failed = [x for x in records if x.get("status") != "PASS"]
    title_ok = [x for x in passed if x.get("title")]
    body_ok = [
        x for x in passed
        if x.get("article_body_status") == "PASS"
        and x.get("article_source")
        and int(x.get("body_text_chars") or 0) >= 25
    ]
    code_rows = [x for x in passed if x.get("security_codes")]
    stop_rows = [x for x in passed if x.get("stop_terms")]
    resume_rows = [x for x in passed if x.get("resume_terms")]
    semantic_rows = [x for x in passed if x.get("stop_terms") or x.get("resume_terms")]

    transport_complete = len(passed) == expected and not failed
    title_complete = len(title_ok) == expected
    body_complete = len(body_ok) == expected

    semantic_view = [
        {
            "archive_date": x.get("archive_date"),
            "url": x.get("url"),
            "title": x.get("title"),
            "security_codes": x.get("security_codes"),
            "stop_terms": x.get("stop_terms"),
            "resume_terms": x.get("resume_terms"),
            "body_text_sha256": x.get("body_text_sha256"),
            "article_body_status": x.get("article_body_status"),
            "article_source": x.get("article_source"),
        }
        for x in records
    ]

    report = {
        "schema": "stock-szse-suspension-detail-corpus-v1",
        "source_archive": {
            "event_rows": expected,
            "canonical_sha256": source["corpus"]["canonical_sha256"],
            "first_date": source["corpus"]["first_date"],
            "last_date": source["corpus"]["last_date"],
        },
        "execution": {
            "max_workers": MAX_WORKERS,
            "max_attempts": MAX_ATTEMPTS,
            "network_recovery": network_recovery,
        },
        "summary": {
            "selected_detail_pages": expected,
            "transport_pass": len(passed),
            "transport_nonpass": len(failed),
            "title_extracted": len(title_ok),
            "body_text_extracted": len(body_ok),
            "rows_with_security_code": len(code_rows),
            "rows_with_stop_terms": len(stop_rows),
            "rows_with_resume_terms": len(resume_rows),
            "rows_with_stop_or_resume_semantics": len(semantic_rows),
            "status_counts": dict(sorted(Counter(x.get("status") for x in records).items())),
            "semantic_view_sha256": canonical_sha(semantic_view),
        },
        "records": records,
        "adjudication": {
            "full_detail_page_transport": "PASS" if transport_complete else "NOT VERIFIED",
            "full_detail_body_text": "PASS" if body_complete else "NOT VERIFIED",
            "full_detail_title_semantics": "SUPPORTED" if title_complete else "NOT VERIFIED",
            "instrument_identity_extraction": "SUPPORTED_DIAGNOSTIC" if code_rows else "NOT VERIFIED",
            "suspension_resumption_semantic_corpus": "SUPPORTED_DIAGNOSTIC" if semantic_rows else "NOT VERIFIED",
            "shenzhen_historical_suspension_state": "NOT VERIFIED",
            "shenzhen_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This stage validates primary SZSE detail-page transport and extracts literal title/body/code/stop-resume "
            "semantics from a named primary announcement DOM container only; page navigation and footer "
            "do not qualify as article text. It does not infer a daily suspension interval from publication dates or URL IDs. Effective "
            "stop/resume dates and deterministic daily-state replay remain separate gates."
        ),
    }

    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_archive": report["source_archive"],
        "summary": report["summary"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    return 0 if transport_complete and body_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
