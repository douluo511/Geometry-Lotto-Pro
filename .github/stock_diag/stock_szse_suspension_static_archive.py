from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = "https://www.szse.cn/disclosure/notice/temp/"
START = "20180101"
END = "20260930"
MAX_PAGES = 500
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
ARTICLE_RE = re.compile(r"(?:^|/)t(20\d{6})_[A-Za-z0-9]+\.html(?:$|[?#])", re.I)


def same_szse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "szse.cn" or host.endswith(".szse.cn")


def fetch(session: requests.Session, url: str, attempts: int = 3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": ROOT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code in {403, 429} or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            if r.status_code == 404:
                return r, {"attempt": attempt, "prior_errors": errors, "not_found": True}
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            if not same_szse(r.url):
                raise RuntimeError(f"redirect left official SZSE host: {r.url}")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def page_url(index: int) -> str:
    return urljoin(ROOT, "index.html" if index == 0 else f"index_{index}.html")


def decode_response(response: requests.Response) -> str:
    enc = response.encoding
    if not enc or str(enc).lower() in {"iso-8859-1", "latin-1"}:
        enc = response.apparent_encoding or "utf-8"
    return response.content.decode(enc, errors="replace")


def parse_page(response: requests.Response):
    text = decode_response(response)
    final_url = str(response.url)
    raw = response.content
    soup = BeautifulSoup(text, "html.parser")
    rows = {}

    # Preferred path: literal anchor hrefs, if present.
    for a in soup.find_all("a", href=True):
        full = urljoin(final_url, a.get("href"))
        if not same_szse(full):
            continue
        m = ARTICLE_RE.search(full)
        if not m:
            continue
        d = m.group(1)
        title = " ".join(a.get_text(" ", strip=True).split()) or str(a.get("title") or "").strip()
        key = (d, full.split("#", 1)[0])
        rows[key] = {
            "date": d,
            "title": title or None,
            "url": key[1],
            "identity_source": "anchor_href",
        }

    # Observed SZSE static pages can carry article targets in template data rather
    # than literal <a href>. Recover only literal first-party tYYYYMMDD_N.html
    # identifiers from the delivered HTML; never invent an ID from a date.
    for match in re.finditer(r"(?:https?://(?:www\.)?szse\.cn)?(?:/disclosure/notice/temp/)?(t(20\d{6})_\d+\.html)", text, flags=re.I):
        rel = match.group(1)
        d = match.group(2)
        full = urljoin(final_url, rel).split("#", 1)[0]
        if not same_szse(full):
            continue
        key = (d, full)
        if key not in rows:
            lo = max(0, match.start() - 350)
            hi = min(len(text), match.end() + 350)
            context = text[lo:hi]
            context_text = " ".join(BeautifulSoup(context, "html.parser").get_text(" ", strip=True).split())
            rows[key] = {
                "date": d,
                "title": None,
                "url": full,
                "identity_source": "literal_template_identifier",
                "context_sha256": hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest(),
                "context_text_sample": context_text[:500],
            }

    result = [rows[k] for k in sorted(rows, reverse=True)]
    diagnostics = {
        "literal_article_identifier_count": len(rows),
        "literal_article_identifier_sha256": canonical_sha([
            {"date": x["date"], "url": x["url"]} for x in result
        ]) if result else None,
        "date_token_count": len(re.findall(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}日?", text)),
    }
    return result, hashlib.sha256(raw).hexdigest(), diagnostics


def canonical_sha(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    s = requests.Session()
    pages = []
    all_rows = {}
    prior_page_min = None
    boundary_page = None
    next_page_receipt = None

    for idx in range(MAX_PAGES):
        url = page_url(idx)
        r, meta = fetch(s, url)
        if r.status_code == 404:
            next_page_receipt = {
                "page_index": idx,
                "url": url,
                "http_status": 404,
                "attempt": meta["attempt"],
            }
            break

        rows, raw_sha, page_diag = parse_page(r)
        if not rows:
            next_page_receipt = {
                "page_index": idx,
                "url": str(r.url),
                "http_status": r.status_code,
                "sha256": raw_sha,
                "row_count": 0,
                "attempt": meta["attempt"],
            }
            break

        dates = [x["date"] for x in rows]
        page_max = max(dates)
        page_min = min(dates)

        # Archive pages must move backward in time. Same-day boundaries are allowed,
        # but a later date reappearing after an older page would invalidate completeness.
        if prior_page_min is not None and page_max > prior_page_min:
            raise RuntimeError(
                f"page chronology reversal: page={idx} max={page_max} prior_min={prior_page_min}"
            )

        identities = {(x["date"], x["url"]) for x in rows}
        overlap = identities & set(all_rows)
        if overlap:
            raise RuntimeError(f"cross-page duplicate article identities: page={idx} count={len(overlap)}")
        for x in rows:
            all_rows[(x["date"], x["url"])] = x

        pages.append({
            "page_index": idx,
            "url": str(r.url),
            "http_status": r.status_code,
            "sha256": raw_sha,
            "row_count": len(rows),
            "max_date": page_max,
            "min_date": page_min,
            "attempt": meta["attempt"],
            "parse_diagnostics": page_diag,
        })

        prior_page_min = page_min

        # Once an entire page is older than the frozen start, every later page should
        # also be older under the chronology invariant. Fetch one additional page to
        # validate the continuation boundary, then stop.
        if page_max < START:
            boundary_page = idx
            extra_idx = idx + 1
            extra_url = page_url(extra_idx)
            er, emeta = fetch(s, extra_url)
            if er.status_code == 404:
                next_page_receipt = {
                    "page_index": extra_idx,
                    "url": extra_url,
                    "http_status": 404,
                    "attempt": emeta["attempt"],
                    "parse_diagnostics": ediag,
                }
            else:
                erows, esha, ediag = parse_page(er)
                if erows and max(x["date"] for x in erows) > page_min:
                    raise RuntimeError(
                        f"post-boundary chronology reversal: page={extra_idx}"
                    )
                next_page_receipt = {
                    "page_index": extra_idx,
                    "url": str(er.url),
                    "http_status": er.status_code,
                    "sha256": esha,
                    "row_count": len(erows),
                    "max_date": max((x["date"] for x in erows), default=None),
                    "min_date": min((x["date"] for x in erows), default=None),
                    "attempt": emeta["attempt"],
                }
            break

        time.sleep(0.05)
    else:
        raise RuntimeError(f"archive did not cross frozen start within MAX_PAGES={MAX_PAGES}")

    corpus = [
        row for _, row in sorted(all_rows.items())
        if START <= row["date"] <= END
    ]
    if not corpus:
        raise RuntimeError("no SZSE suspension archive rows in frozen window")

    dates = [x["date"] for x in corpus]
    title_missing = sum(1 for x in corpus if x["title"] == "TITLE_NOT_EXTRACTED")
    article_links_unique = len({x["url"] for x in corpus}) == len(corpus)

    link_archive_complete = (
        boundary_page is not None
        and min(dates) >= START
        and max(dates) <= END
        and article_links_unique
        and len(pages) >= 2
        and pages[0]["sha256"] != pages[1]["sha256"]
    )
    title_semantics_complete = title_missing == 0

    report = {
        "schema": "stock-szse-suspension-static-archive-v1",
        "official_archive_root": ROOT,
        "frozen_window": {"start": START, "end": END},
        "archive_pages": pages,
        "boundary_page_index": boundary_page,
        "post_boundary_receipt": next_page_receipt,
        "corpus": {
            "event_rows": len(corpus),
            "unique_article_links": len({x["url"] for x in corpus}),
            "unique_dates": len(set(dates)),
            "first_date": min(dates),
            "last_date": max(dates),
            "missing_title_rows": title_missing,
            "canonical_sha256": canonical_sha(corpus),
            "events": corpus,
        },
        "adjudication": {
            "official_static_archive_pagination": "PASS" if link_archive_complete else "NOT VERIFIED",
            "frozen_window_suspension_notice_link_archive": "SUPPORTED" if link_archive_complete else "NOT VERIFIED",
            "archive_title_semantics": "SUPPORTED" if title_semantics_complete else "NOT VERIFIED",
            "shenzhen_historical_suspension_state": "NOT VERIFIED",
            "shenzhen_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This exhausts literal first-party SZSE suspension-notice article identifiers backward "
            "across the frozen start boundary. A link/date corpus can pass independently of title/body "
            "semantics; missing title semantics remain NOT VERIFIED. Instrument identity and effective "
            "suspension/resumption daily state require separate primary-document validation before "
            "Shenzhen historical suspension PIT can pass."
        ),
    }

    Path("stock_szse_suspension_static_archive.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "pages_fetched": len(pages),
        "boundary_page_index": boundary_page,
        "event_rows": len(corpus),
        "unique_dates": len(set(dates)),
        "first_date": min(dates),
        "last_date": max(dates),
        "canonical_sha256": report["corpus"]["canonical_sha256"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if link_archive_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
