from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
KEYWORDS = (
    "commonQuery.do", "query.sse.com.cn", "sqlId", "suspension",
    "停牌起始日", "停牌终止日", "停复牌", "SEC_CODE",
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def fetch(session, url, *, attempts=3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={"User-Agent": UA, "Referer": PAGE, "Accept": "*/*"},
                timeout=(8, 25),
                allow_redirects=True,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def snippets(text, keyword, radius=220):
    out = []
    lower = text.lower()
    k = keyword.lower()
    start = 0
    while len(out) < 8:
        pos = lower.find(k, start)
        if pos < 0:
            break
        out.append(text[max(0, pos-radius): min(len(text), pos+len(keyword)+radius)])
        start = pos + len(keyword)
    return out


def main():
    s = requests.Session()
    page, page_meta = fetch(s, PAGE)
    html = page.content.decode(page.encoding or "utf-8", errors="replace")
    srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I)
    urls = []
    for src in srcs:
        url = urljoin(PAGE, src)
        host = urlparse(url).hostname or ""
        if host.endswith("sse.com.cn") and url not in urls:
            urls.append(url)

    scanned = []
    hits = []
    for url in urls[:60]:
        try:
            r, meta = fetch(s, url, attempts=2)
            raw = r.content
            text = raw.decode(r.encoding or "utf-8", errors="replace")
            row = {
                "url": url,
                "status": r.status_code,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "attempt": meta["attempt"],
            }
            scanned.append(row)
            matched = {}
            for kw in KEYWORDS:
                ss = snippets(text, kw)
                if ss:
                    matched[kw] = ss
            if matched:
                hits.append({"script": row, "matches": matched})
        except Exception as exc:
            scanned.append({"url": url, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

    page_matches = {}
    for kw in KEYWORDS:
        ss = snippets(html, kw)
        if ss:
            page_matches[kw] = ss

    report = {
        "schema": "stock-sse-suspension-endpoint-discovery-v1",
        "status": "PASS",
        "page": PAGE,
        "page_http_status": page.status_code,
        "page_sha256": hashlib.sha256(page.content).hexdigest(),
        "page_bytes": len(page.content),
        "page_fetch_attempt": page_meta["attempt"],
        "script_refs_found": len(srcs),
        "same_origin_scripts_scanned": len(scanned),
        "page_matches": page_matches,
        "script_hits": hits,
        "discovery_status": "CANDIDATE_FOUND" if hits or page_matches else "NOT FOUND",
        "boundary": {
            "historical_sse_suspension_endpoint_verified": False,
            "historical_suspension_daily_state": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_suspension_endpoint_discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    public_candidates = []
    for hit in hits:
        for keyword, items in hit["matches"].items():
            for item in items[:3]:
                public_candidates.append({
                    "script": hit["script"]["url"],
                    "keyword": keyword,
                    "snippet": " ".join(item.split())[:700],
                })
                if len(public_candidates) >= 24:
                    break
            if len(public_candidates) >= 24:
                break
        if len(public_candidates) >= 24:
            break
    print(json.dumps({
        "status": report["status"],
        "page_http_status": report["page_http_status"],
        "script_refs_found": report["script_refs_found"],
        "same_origin_scripts_scanned": report["same_origin_scripts_scanned"],
        "discovery_status": report["discovery_status"],
        "hit_scripts": [x["script"]["url"] for x in hits],
        "page_keywords": sorted(page_matches),
        "public_candidates": public_candidates,
        "boundary": report["boundary"],
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
