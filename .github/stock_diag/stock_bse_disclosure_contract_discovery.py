from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

PAGES = [
    "https://www.bse.cn/disclosure/announcement.html",
    "https://www.bse.cn/disclosure/tradepublic.html",
]
OUT = Path("stock_bse_disclosure_contract_discovery.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI first-party contract discovery"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,application/javascript,*/*;q=0.8"},
        timeout=(10, 30),
        allow_redirects=True,
    )
    r.raise_for_status()
    if not r.content:
        raise RuntimeError(f"empty payload: {url}")
    return r


def same_official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def main() -> int:
    s = requests.Session()
    pages = []
    script_urls = set()
    for url in PAGES:
        r = get(s, url)
        text = r.content.decode(r.encoding or "utf-8", errors="replace")
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
        resolved = []
        for src in scripts:
            full = urljoin(r.url, src)
            if same_official_host(full):
                script_urls.add(full)
                resolved.append(full)
        pages.append({
            "url": url,
            "resolved_url": r.url,
            "status": r.status_code,
            "bytes": len(r.content),
            "sha256": sha256(r.content),
            "same_official_host": same_official_host(r.url),
            "script_count": len(resolved),
            "scripts": sorted(resolved),
            "contains_company_query_ui": any(
                token in text for token in ("公司简称", "公司代码", "companyCode", "关键字", "查询")
            ),
        })

    scripts = []
    candidate_urls = set()
    candidate_fragments = []
    for url in sorted(script_urls):
        try:
            r = get(s, url)
        except Exception as exc:
            scripts.append({"url": url, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            continue
        text = r.content.decode(r.encoding or "utf-8", errors="replace")
        # Preserve candidate API/query strings without executing them.
        for raw in re.findall(r'(?:(?:https?:)?//[^"\'\s]+|/[A-Za-z0-9_./?=&%-]{8,})', text):
            full = urljoin(r.url, raw)
            low = full.lower()
            if same_official_host(full) and any(
                token in low for token in (
                    "api", "query", "disclosure", "announcement", "company",
                    "info", "search", "ajax", "tradepublic"
                )
            ):
                candidate_urls.add(full)
        for m in re.finditer(
            r'.{0,120}(?:companyCode|announcement|disclosure|tradepublic|ajax|query|api).{0,180}',
            text, flags=re.I | re.S
        ):
            frag = " ".join(m.group(0).split())
            if frag and frag not in candidate_fragments:
                candidate_fragments.append(frag[:500])
        scripts.append({
            "url": url,
            "resolved_url": r.url,
            "status": "PASS",
            "http_status": r.status_code,
            "bytes": len(r.content),
            "sha256": sha256(r.content),
        })

    report = {
        "schema": "stock-bse-disclosure-contract-discovery-v1",
        "official_host_only": True,
        "pages": pages,
        "scripts": scripts,
        "candidate_query_urls": sorted(candidate_urls),
        "candidate_script_fragments": candidate_fragments[:120],
        "adjudication": {
            "official_query_surface_reachable": all(p["status"] == 200 and p["same_official_host"] for p in pages),
            "machine_query_contract": "CANDIDATE_ONLY" if candidate_urls else "NOT VERIFIED",
            "bse_historical_st_pit": "NOT VERIFIED",
            "bse_historical_suspension_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "Discovery only. Candidate URLs/fragments are not a validated data contract and do not "
            "prove complete historical BSE ST/suspension point-in-time coverage."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "page_count": len(pages),
        "script_count": len(scripts),
        "candidate_url_count": len(candidate_urls),
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
