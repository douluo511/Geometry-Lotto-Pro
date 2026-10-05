from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PAGE = "https://www.szse.cn/disclosure/notice/temp/index.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
TOKENS = ("ShowReport", "CATALOGID", "TABKEY", "停复牌", "temp", "pageSize", "pageNo")


def fetch(session, url, attempts=3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://www.szse.cn/",
                    "Accept": "text/html,application/javascript,text/javascript,*/*;q=0.8",
                },
                timeout=(8, 30),
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


def same_szse(url):
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("szse.cn")


def scan(text, url):
    endpoint_hits = sorted(set(re.findall(
        r"(?:https?://[^\"'\s]+)?/api/report/ShowReport[^\"'\s<]*",
        text,
        flags=re.I,
    )))
    catalog_ids = sorted(set(
        m.group(1) for m in re.finditer(
            r"CATALOGID[^A-Za-z0-9_\-]{0,20}([A-Za-z0-9_\-]+)",
            text,
            flags=re.I,
        )
    ))
    tabkeys = sorted(set(
        m.group(1) for m in re.finditer(
            r"TABKEY[^A-Za-z0-9_\-]{0,20}([A-Za-z0-9_\-]+)",
            text,
            flags=re.I,
        )
    ))
    snippets = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if any(t.lower() in line.lower() for t in TOKENS):
            snippets.append({"line": line_no, "text": line.strip()[:1800]})
            if len(snippets) >= 80:
                break
    return {
        "url": url,
        "endpoint_hits": endpoint_hits,
        "catalog_ids": catalog_ids,
        "tabkeys": tabkeys,
        "snippets": snippets,
    }


def main():
    s = requests.Session()
    page, meta = fetch(s, PAGE)
    raw = page.content
    text = raw.decode(page.encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    assets = set()
    for tag in soup.find_all(["script", "iframe"]):
        attr = "src"
        src = tag.get(attr)
        if src:
            full = urljoin(str(page.url), src)
            if same_szse(full):
                assets.add(full)

    page_scan = scan(text, str(page.url))
    asset_scans = []
    asset_errors = []
    for url in sorted(assets)[:120]:
        try:
            r, m = fetch(s, url, attempts=2)
            t = r.content.decode(r.encoding or "utf-8", errors="replace")
            result = scan(t, url)
            if result["endpoint_hits"] or result["catalog_ids"] or result["tabkeys"] or result["snippets"]:
                result.update({
                    "http_status": r.status_code,
                    "sha256": hashlib.sha256(r.content).hexdigest(),
                    "fetch_attempt": m["attempt"],
                })
                asset_scans.append(result)
        except Exception as exc:
            asset_errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    all_endpoints = sorted(set(page_scan["endpoint_hits"] + [
        v for x in asset_scans for v in x["endpoint_hits"]
    ]))
    all_catalogs = sorted(set(page_scan["catalog_ids"] + [
        v for x in asset_scans for v in x["catalog_ids"]
    ]))
    all_tabkeys = sorted(set(page_scan["tabkeys"] + [
        v for x in asset_scans for v in x["tabkeys"]
    ]))

    literal_contract = bool(all_endpoints and all_catalogs)
    report = {
        "schema": "stock-szse-suspension-endpoint-discovery-v1",
        "authoritative_product_head": "7f270b9ab58e11fd8129053a65e000c90ff9d8c1",
        "official_page": {
            "url": str(page.url),
            "http_status": page.status_code,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "fetch_attempt": meta["attempt"],
            "title_contains_suspension": "停复牌" in text,
            "page_scan": page_scan,
        },
        "assets_scanned": len(assets),
        "asset_evidence": asset_scans,
        "asset_errors": asset_errors,
        "contract": {
            "endpoint_hits": all_endpoints,
            "catalog_ids": all_catalogs,
            "tabkeys": all_tabkeys,
        },
        "adjudication": {
            "official_szse_suspension_surface": "SUPPORTED" if "停复牌" in text else "NOT VERIFIED",
            "machine_query_contract": "SUPPORTED" if literal_contract else "NOT VERIFIED",
            "shenzhen_historical_suspension_state": "NOT VERIFIED",
            "shenzhen_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This is endpoint discovery only. A literal ShowReport/CATALOGID contract may justify a "
            "separate historical query validator, but it cannot promote Shenzhen suspension daily "
            "state, historical ST/PIT, Advanced Business or Final."
        ),
    }
    Path("stock_szse_suspension_endpoint_discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "official_surface": report["adjudication"]["official_szse_suspension_surface"],
        "machine_query_contract": report["adjudication"]["machine_query_contract"],
        "endpoint_hits": all_endpoints,
        "catalog_ids": all_catalogs,
        "tabkeys": all_tabkeys,
        "asset_evidence_count": len(asset_scans),
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))
    return 0 if literal_contract else 2


if __name__ == "__main__":
    raise SystemExit(main())
