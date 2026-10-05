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
INDEX_CANDIDATES = [
    "index.html",
    "index_1.html",
    "index_2.html",
    "index_5.html",
    "index_10.html",
]
ANCHORS = [
    ("2018-08-06", "t20180806_554014.html"),
    ("2026-09-09", "t20260909_622788.html"),
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def fetch(session: requests.Session, url: str, attempts: int = 3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://www.szse.cn/",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                    "Cache-Control": "no-cache",
                },
                timeout=(8, 35),
                allow_redirects=True,
            )
            if r.status_code in {403, 429} or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.25 * (2 ** (attempt - 1)))


def same_szse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("szse.cn")


def decode_response(r: requests.Response) -> str:
    enc = r.encoding
    if not enc or enc.lower() == "iso-8859-1":
        enc = r.apparent_encoding or "utf-8"
    return r.content.decode(enc, errors="replace")


def inspect_index(r: requests.Response, meta: dict):
    text = decode_response(r)
    soup = BeautifulSoup(text, "html.parser")
    article_links = []
    for a in soup.find_all("a", href=True):
        full = urljoin(str(r.url), a.get("href"))
        if not same_szse(full):
            continue
        if re.search(r"/disclosure/notice/temp/t\d{8}_\d+\.html(?:$|[?#])", full):
            article_links.append({
                "url": full.split("#", 1)[0],
                "text": " ".join(a.get_text(" ", strip=True).split())[:500],
            })
    dedup = {}
    for item in article_links:
        dedup[item["url"]] = item
    article_links = list(dedup.values())
    dates = sorted(set(re.findall(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}日?", text)))
    return {
        "url": str(r.url),
        "http_status": r.status_code,
        "bytes": len(r.content),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "content_type": r.headers.get("content-type"),
        "fetch_attempt": meta["attempt"],
        "prior_errors": meta["prior_errors"],
        "title_contains_suspension": "停复牌" in text,
        "article_link_count": len(article_links),
        "article_link_sample": article_links[:12],
        "date_token_sample": dates[:12],
        "body_prefix_sha256": hashlib.sha256(text[:4096].encode("utf-8")).hexdigest(),
    }


def inspect_anchor(r: requests.Response, meta: dict, expected_date: str):
    text = decode_response(r)
    compact = re.sub(r"\s+", "", text)
    date_variants = {
        expected_date,
        expected_date.replace("-", "年", 1).replace("-", "月", 1) + "日",
        expected_date.replace("-", ""),
    }
    has_date = any(x in compact for x in date_variants)
    has_suspension = "停牌" in compact or "复牌" in compact
    return {
        "url": str(r.url),
        "http_status": r.status_code,
        "bytes": len(r.content),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "fetch_attempt": meta["attempt"],
        "expected_date": expected_date,
        "expected_date_present": has_date,
        "suspension_or_resumption_text_present": has_suspension,
        "title_or_body_marker_present": ("临时停牌" in compact or "停复牌" in compact),
    }


def main():
    s = requests.Session()
    index_results = []
    index_errors = []
    for rel in INDEX_CANDIDATES:
        url = urljoin(ROOT, rel)
        try:
            r, meta = fetch(s, url)
            result = inspect_index(r, meta)
            result["requested_relative"] = rel
            index_results.append(result)
        except Exception as exc:
            index_errors.append({"requested_relative": rel, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    anchor_results = []
    anchor_errors = []
    for expected_date, rel in ANCHORS:
        url = urljoin(ROOT, rel)
        try:
            r, meta = fetch(s, url)
            anchor_results.append(inspect_anchor(r, meta, expected_date))
        except Exception as exc:
            anchor_errors.append({"expected_date": expected_date, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    paginated_with_articles = [
        x for x in index_results
        if x["requested_relative"] != "index.html" and x["article_link_count"] > 0
    ]
    any_index_articles = any(x["article_link_count"] > 0 for x in index_results)
    marker_or_articles = sum(
        1 for x in index_results
        if x["title_contains_suspension"] or x["article_link_count"] > 0
    )
    anchor_pass = (
        len(anchor_results) == len(ANCHORS)
        and all(x["expected_date_present"] and x["suspension_or_resumption_text_present"] for x in anchor_results)
    )
    sample_surface_supported = bool(
        any_index_articles
        and paginated_with_articles
        and marker_or_articles >= 2
        and anchor_pass
    )

    report = {
        "schema": "stock-szse-static-suspension-archive-probe-v1",
        "authoritative_product_head": "7f270b9ab58e11fd8129053a65e000c90ff9d8c1",
        "scope": "bounded official static archive surface probe only; not an exhaustive historical replay",
        "index_candidates": INDEX_CANDIDATES,
        "index_results": index_results,
        "index_errors": index_errors,
        "anchor_results": anchor_results,
        "anchor_errors": anchor_errors,
        "summary": {
            "index_success_count": len(index_results),
            "index_error_count": len(index_errors),
            "paginated_page_with_article_count": len(paginated_with_articles),
            "marker_or_articles_page_count": marker_or_articles,
            "anchor_success_count": len(anchor_results),
            "anchor_expected_count": len(ANCHORS),
        },
        "adjudication": {
            "official_static_archive_sample_surface": "SUPPORTED" if sample_surface_supported else "NOT VERIFIED",
            "static_pagination_contract": "SUPPORTED_SAMPLE_ONLY" if paginated_with_articles else "NOT VERIFIED",
            "historical_anchor_span_2018_to_2026": "SUPPORTED_SAMPLE_ONLY" if anchor_pass else "NOT VERIFIED",
            "exhaustive_historical_archive": "NOT VERIFIED",
            "shenzhen_historical_suspension_state": "NOT VERIFIED",
            "shenzhen_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "A sample PASS only authorizes a later exhaustive official-static-archive pagination validator. "
            "It does not establish complete announcement coverage, interval semantics, daily suspension state, "
            "historical ST/PIT, Advanced Business, repository independence, production Release or Final."
        ),
    }
    Path("stock_szse_static_suspension_archive_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "official_static_archive_sample_surface": report["adjudication"]["official_static_archive_sample_surface"],
        "static_pagination_contract": report["adjudication"]["static_pagination_contract"],
        "historical_anchor_span_2018_to_2026": report["adjudication"]["historical_anchor_span_2018_to_2026"],
        "index_success_count": len(index_results),
        "paginated_page_with_article_count": len(paginated_with_articles),
        "anchor_success_count": len(anchor_results),
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    return 0 if sample_surface_supported else 2


if __name__ == "__main__":
    raise SystemExit(main())
