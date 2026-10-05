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

    # Extract bounded endpoint-construction hints from the live official page/scripts.
    # Discovery remains read-only: a literal or config key is only a candidate
    # until a separate request-validation step proves endpoint semantics.
    target_key = "bond_14526_js_suspension_stock"
    endpoint_hints = []
    source_texts = [(PAGE, html)]
    for row in scanned:
        source_url = row.get("url")
        if row.get("status") == "FAIL" or not source_url:
            continue
        try:
            rr, _ = fetch(s, source_url, attempts=2)
            source_text = rr.content.decode(rr.encoding or "utf-8", errors="replace")
            source_texts.append((source_url, source_text))
        except Exception:
            continue

    for source_url, source_text in source_texts:
        relevant = (
            target_key in source_text
            or "suspension" in source_text.lower()
            or "sseQueryURL" in source_text
            or "commonQuery.do" in source_text
        )
        if not relevant:
            continue
        do_literals = sorted(set(
            re.findall(r'["\\\']([^"\\\']*?\\.do(?:\\?[^"\\\']*)?)["\\\']', source_text)
        ))
        sql_ids = sorted(set(
            re.findall(r'sqlId\\s*[:=]\\s*["\\\']([^"\\\']+)["\\\']', source_text, flags=re.I)
        ))
        target_contexts = [
            " ".join(x.split())[:6000]
            for x in snippets(source_text, target_key, radius=3200)[:4]
        ]
        query_contexts = []
        for kw in ("sseQueryURL", "commonQuery.do", "commonSoaQuery.do", "sqlId", "tableData", "tableFun"):
            for x in snippets(source_text, kw, radius=2200)[:3]:
                query_contexts.append({
                    "keyword": kw,
                    "context": " ".join(x.split())[:5000],
                })
        if do_literals or sql_ids or target_contexts or query_contexts:
            endpoint_hints.append({
                "source": source_url,
                "do_literals": do_literals[:40],
                "sql_ids": sql_ids[:80],
                "target_key_contexts": target_contexts,
                "query_contexts": query_contexts[:24],
            })
        if len(endpoint_hints) >= 24:
            break

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
        "endpoint_hints": endpoint_hints,
        "discovery_status": "CANDIDATE_FOUND" if hits or page_matches or endpoint_hints else "NOT FOUND",
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
    targeted_context = []
    target_key = "bond_14526_js_suspension_stock"
    for hit in hits:
        if "table_config.js" not in hit["script"]["url"]:
            continue
        # Re-fetch the already identified public config script and emit a bounded
        # context around the exact suspension-stock table key.
        rr, _ = fetch(s, hit["script"]["url"], attempts=2)
        tt = rr.content.decode(rr.encoding or "utf-8", errors="replace")
        pos = tt.find(target_key)
        if pos >= 0:
            targeted_context.append({
                "source": hit["script"]["url"],
                "key": target_key,
                "context": " ".join(tt[max(0, pos-250): min(len(tt), pos+5000)].split()),
            })
    page_query_context = []
    for kw in ("query.sse.com.cn", "commonQuery.do", "sqlId"):
        for item in snippets(html, kw, radius=1200)[:3]:
            page_query_context.append({
                "keyword": kw,
                "context": " ".join(item.split())[:3000],
            })

    loader_context = []
    loader_keywords = (
        target_key, "sseQueryURL", "commonQuery.do", "commonQuery", "sqlId",
        "$.ajax", "ajax(", "queryUrl", "queryURL", "tableData", "tableFun",
    )
    for row in scanned:
        url = row.get("url")
        if row.get("status") == "FAIL" or not url:
            continue
        try:
            rr, _ = fetch(s, url, attempts=2)
            tt = rr.content.decode(rr.encoding or "utf-8", errors="replace")
        except Exception:
            continue
        matched_any = []
        for kw in loader_keywords:
            ss = snippets(tt, kw, radius=1600)
            if ss:
                matched_any.append({
                    "keyword": kw,
                    "contexts": [" ".join(x.split())[:3500] for x in ss[:4]],
                })
        if matched_any:
            loader_context.append({
                "source": url,
                "matches": matched_any,
            })
        if len(loader_context) >= 20:
            break

    common_table_context = []
    for url in urls:
        if "common_table.js" not in url:
            continue
        rr, _ = fetch(s, url, attempts=2)
        tt = rr.content.decode(rr.encoding or "utf-8", errors="replace")
        for kw in (
            "sseQueryURL", "commonQuery.do", "commonQuery", "sqlId",
            "queryParams", "tableData", "tableFun", "ajax", ".do",
        ):
            for item in snippets(tt, kw, radius=2600)[:6]:
                common_table_context.append({
                    "source": url,
                    "keyword": kw,
                    "context": " ".join(item.split())[:5500],
                })
                if len(common_table_context) >= 36:
                    break
            if len(common_table_context) >= 36:
                break

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
        "script_urls": urls,
        "discovery_status": report["discovery_status"],
        "hit_scripts": [x["script"]["url"] for x in hits],
        "page_keywords": sorted(page_matches),
        "public_candidates": public_candidates,
        "endpoint_hints": endpoint_hints,
        "targeted_context": targeted_context,
        "page_query_context": page_query_context,
        "loader_context": loader_context,
        "common_table_context": common_table_context,
        "boundary": report["boundary"],
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
