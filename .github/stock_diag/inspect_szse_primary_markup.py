"""Read-only primary DOM forensic probe. Never turns body or PIT evidence PASS."""
from __future__ import annotations
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

URL = "https://www.szse.cn/disclosure/notice/temp/t20260626_621274.html"
OUT = Path("stock_szse_dom_probe.json")
RAW = Path("stock_szse_dom_probe_primary.html")
TERMS = ("停牌", "复牌", "恢复交易", "暂停交易")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36",
    "Referer": "https://www.szse.cn/disclosure/notice/temp/",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def label(node: Tag) -> dict:
    return {
        "tag": node.name,
        "id": str(node.get("id") or "")[:100],
        "classes": list(node.get("class") or [])[:12],
        "text_chars": len(node.get_text(" ", strip=True)),
    }

def main():
    result = {
        "schema": "stock-szse-first-party-dom-forensic-v1",
        "url": URL,
        "primary_body_qualified": "NOT VERIFIED",
        "historical_st_pit": "NOT VERIFIED",
        "final_gate": "FAIL",
        "transport": "NOT VERIFIED",
        "diagnostic_only": True,
    }
    try:
        errors = []
        for attempt in range(1, 6):
            try:
                r = requests.get(URL, headers=HEADERS, timeout=(8, 30), allow_redirects=True)
                break
            except requests.RequestException as exc:
                errors.append({"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
                if attempt == 5:
                    result["transport_attempt_errors"] = errors
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
        result["transport_attempt_errors"] = errors
        result["http_status"] = r.status_code
        result["resolved_url"] = r.url
        result["content_type"] = r.headers.get("Content-Type")
        result["raw_bytes"] = len(r.content)
        result["raw_sha256"] = hashlib.sha256(r.content).hexdigest()
        if urlparse(r.url).hostname not in ("szse.cn", "www.szse.cn"):
            raise RuntimeError("unexpected host or redirect")
        r.raise_for_status()
        if not r.content:
            raise RuntimeError("empty primary payload")
        RAW.write_bytes(r.content)
        enc = r.encoding if r.encoding and r.encoding.lower() not in ("iso-8859-1", "latin-1") else (r.apparent_encoding or "utf-8")
        soup = BeautifulSoup(r.content.decode(enc, errors="replace"), "html.parser")
        result["transport"] = "PASS"
        result["encoding"] = enc
        result["page_title"] = (soup.title.get_text(" ", strip=True) if soup.title else None)
        result["top_level"] = [label(x) for x in list(soup.body.children) if isinstance(x, Tag)][:20] if soup.body else []
        result["candidate_nodes"] = []
        # Structural diagnostics, not a valid extraction selector or semantic proof.
        candidates = []
        for node in soup.find_all(True):
            if node.name not in ("div", "section", "article", "main", "p", "td", "span"):
                continue
            if node.find_parent(["header", "nav", "footer", "aside"]):
                continue
            content = " ".join(node.get_text(" ", strip=True).split())
            if len(content) < 35 or not any(term in content for term in TERMS):
                continue
            child_hit = sum(any(t in x.get_text(" ", strip=True) for t in TERMS) for x in node.find_all(["p", "div"], recursive=False))
            if len(content) > 12000:
                continue
            candidates.append((len(content), node, content[:250], child_hit))
        candidates.sort(key=lambda x: x[0])
        for n, node, sample, child_count in candidates[:30]:
            lineage = []
            parent = node
            for _ in range(5):
                if not isinstance(parent, Tag):
                    break
                lineage.append(label(parent))
                parent = parent.parent
            result["candidate_nodes"].append({
                "lineage_inner_to_outer": lineage,
                "sample": sample,
                "direct_child_semantic_hits": child_count,
            })
        result["candidate_count"] = len(candidates)
        result["body_text_chars"] = len(soup.body.get_text(" ", strip=True)) if soup.body else 0
        result["raw_body_term_presence"] = {term: term in (soup.body.get_text(" ", strip=True) if soup.body else "") for term in TERMS}
        result["existing_selector_matches"] = {}
        for selector in ("article", "[itemprop='articleBody']", "#article", "#articleContent", ".article-content", ".news-content", ".news-con", ".content", "#content"):
            result["existing_selector_matches"][selector] = len(soup.select(selector))
    except Exception as exc:
        result["exception"] = f"{type(exc).__name__}: {exc}"
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)[:8500])
    return 0 if result["transport"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
