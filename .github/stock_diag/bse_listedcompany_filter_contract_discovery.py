from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

PAGE = "https://www.bse.cn/nq/listedcompany.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE contract discovery"
TOKENS = ("xxfcbj", "nqxxCnzq", "typejb", "listedcompany", "终止", "退市", "摘牌")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def fetch(session: requests.Session, url: str) -> tuple[bytes, dict]:
    attempts = []
    last_error = None
    for attempt in range(1, 4):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/javascript,text/javascript,*/*;q=0.8",
                    "Referer": PAGE,
                },
                timeout=(15, 35),
                allow_redirects=True,
            )
            rec = {
                "attempt": attempt,
                "status": int(r.status_code),
                "resolved_url": r.url,
                "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
            }
            attempts.append(rec)
            if not is_bse(r.url):
                raise RuntimeError(f"non-BSE redirect: {r.url}")
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise RuntimeError(f"retryable HTTP {r.status_code}")
            elif r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            elif not r.content:
                raise RuntimeError("empty response")
            else:
                return r.content, {
                    **rec,
                    "request_url": r.request.url,
                    "content_type": str(r.headers.get("Content-Type") or ""),
                    "attempt_count": attempt,
                    "attempts": attempts,
                }
        except requests.RequestException as exc:
            last_error = exc
            attempts.append({"attempt": attempt, "transport_error": f"{type(exc).__name__}: {exc}"})
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    raise RuntimeError(f"BSE fetch failed for {url}; last_error={last_error!r}; attempts={attempts}")


def decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def script_urls(html: str) -> list[str]:
    out = []
    for m in re.finditer(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", html, flags=re.I):
        url = urljoin(PAGE, unescape(m.group(1).strip()))
        if is_bse(url) and url not in out:
            out.append(url)
    return out


def snippets(text: str, source: str) -> list[dict]:
    out = []
    lower = text.lower()
    seen = set()
    for token in TOKENS:
        start = 0
        token_lower = token.lower()
        while True:
            idx = lower.find(token_lower, start)
            if idx < 0:
                break
            left = max(0, idx - 500)
            right = min(len(text), idx + len(token) + 900)
            context = re.sub(r"\s+", " ", text[left:right]).strip()
            key = sha256_bytes(context.encode("utf-8"))
            if key not in seen:
                seen.add(key)
                out.append({
                    "source": source,
                    "token": token,
                    "context_sha256": key,
                    "context": context,
                })
            start = idx + len(token)
            if len(out) >= 250:
                break
        if len(out) >= 250:
            break
    return out


def extract_literal_values(snips: list[dict]) -> list[dict]:
    findings = []
    for s in snips:
        c = s["context"]
        # Preserve only literal, directly observed candidate values near xxfcbj.
        patterns = [
            r"""xxfcbj(?:\[\])?\s*[:=]\s*["']([^"']+)["']""",
            r"""name\s*=\s*["']xxfcbj(?:\[\])?["'][^>]{0,250}value\s*=\s*["']([^"']+)["']""",
            r"""value\s*=\s*["']([^"']+)["'][^>]{0,250}name\s*=\s*["']xxfcbj(?:\[\])?["']""",
        ]
        for pat in patterns:
            for m in re.finditer(pat, c, flags=re.I):
                value = m.group(1).strip()
                # A JavaScript concatenation fragment such as "+s+" is not a
                # literal enum value. Only preserve directly observed numeric
                # literals; semantic labels remain a separate proof burden.
                if not re.fullmatch(r"\\d+", value):
                    continue
                rec = {
                    "value": value,
                    "source": s["source"],
                    "context_sha256": s["context_sha256"],
                }
                if rec not in findings:
                    findings.append(rec)
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    page_raw, page_transport = fetch(session, PAGE)
    page_text, page_encoding = decode(page_raw)
    page_path = args.raw_dir / "listedcompany.html"
    page_path.write_bytes(page_raw)

    urls = script_urls(page_text)
    # Bound execution. We preserve the discovered URL denominator before limiting.
    if len(urls) > 80:
        raise RuntimeError(f"implausibly large first-party script denominator: {len(urls)}")

    receipts = [{
        "kind": "page",
        "url": PAGE,
        "path": page_path.as_posix(),
        "encoding": page_encoding,
        "transport": page_transport,
    }]
    all_snips = snippets(page_text, PAGE)

    for index, url in enumerate(urls):
        raw, meta = fetch(session, url)
        text, enc = decode(raw)
        suffix = Path(urlparse(url).path).name or f"script_{index:03d}.js"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", suffix)
        path = args.raw_dir / f"{index:03d}_{safe}"
        path.write_bytes(raw)
        receipts.append({
            "kind": "script",
            "url": url,
            "path": path.as_posix(),
            "encoding": enc,
            "transport": meta,
        })
        all_snips.extend(snippets(text, url))

    literal_values = extract_literal_values(all_snips)
    endpoint_sources = sorted({
        s["source"] for s in all_snips
        if "nqxxCnzq" in s["context"]
    })
    xxfcbj_sources = sorted({
        s["source"] for s in all_snips
        if "xxfcbj" in s["context"]
    })

    # Discovery can PASS without proving enum semantics. That separation is intentional.
    discovery_ok = bool(endpoint_sources) and bool(xxfcbj_sources)
    report = {
        "schema": "stock-bse-listedcompany-filter-contract-discovery-v1",
        "status": "PASS" if discovery_ok else "NOT VERIFIED",
        "scope": "first-party listedcompany page/script contract discovery only",
        "product_bytes_changed": False,
        "page": PAGE,
        "page_transport": page_transport,
        "discovered_script_count": len(urls),
        "discovered_script_urls": urls,
        "receipt_count": len(receipts),
        "receipts": receipts,
        "snippet_count": len(all_snips),
        "endpoint_sources": endpoint_sources,
        "xxfcbj_sources": xxfcbj_sources,
        "literal_xxfcbj_values": literal_values,
        "snippets": all_snips,
        "adjudication": {
            "bse_listedcompany_frontend_contract_discovery": "PASS" if discovery_ok else "NOT VERIFIED",
            "xxfcbj_literal_values_discovered": "SUPPORTED" if literal_values else "NOT VERIFIED",
            "xxfcbj_enum_semantics": "NOT VERIFIED",
            "bse_delisted_universe_query_contract": "NOT VERIFIED",
            "bse_current_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_lifecycle_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "A discovery PASS proves only that exact first-party HTML/JS bytes expose the listed-company "
            "endpoint/filter contract. Literal filter values are observations, not semantic labels. "
            "No unlabelled value is interpreted as delisted/terminated without a separate controlled query "
            "or explicit first-party label."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "discovered_script_count": len(urls),
        "endpoint_sources": endpoint_sources,
        "xxfcbj_sources": xxfcbj_sources,
        "literal_xxfcbj_values": literal_values,
        "xxfcbj_contexts": [
            {
                "source": s["source"],
                "context_sha256": s["context_sha256"],
                "context": s["context"],
            }
            for s in all_snips
            if "xxfcbj" in s["context"]
        ][:20],
        "adjudication": report["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if discovery_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
