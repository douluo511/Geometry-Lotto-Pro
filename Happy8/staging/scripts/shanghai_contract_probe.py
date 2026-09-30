from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient

PAGE_URL = "https://www.swlc.net.cn/lottery/kl8.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8ShanghaiContractProbe/0.1",
    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.5",
    "Referer": "https://www.swlc.net.cn/",
}
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _same_official_host(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and parsed.hostname == "www.swlc.net.cn"


def _keywords(text: str) -> list[str]:
    compact = text.replace("\r", "\n")
    rows = []
    for line in compact.split("\n"):
        if re.search(r"(?i)(?:fetch|ajax|xhr|url\s*:|endpoint|api|history|lottery|issue|start_issue|end_issue|query|previous)", line):
            row = re.sub(r"\s+", " ", line).strip()
            if row and row not in rows:
                rows.append(row[:1200])
            if len(rows) >= 120:
                break
    return rows


def inspect() -> dict:
    params = {
        "view": "previous",
        "limit": "100",
        "start_issue": "2021001",
        "end_issue": "2021099",
    }
    response = NET.get(PAGE_URL, params=params, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or PAGE_URL)
    report = {
        "schema": "happy8-shanghai-frontend-contract-probe-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "page": {
            "requested_url": PAGE_URL,
            "final_url": final_url,
            "http_status": int(response.status_code),
            "content_type": str(response.headers.get("Content-Type", "")),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "official_https_host": _same_official_host(final_url),
            "attempts": list(getattr(response, "happy8_attempts", ())),
        },
        "scripts": [],
        "note": "Diagnostic only: discovers current official frontend data contract; it does not relax the production full-history gate.",
    }
    if int(response.status_code) != 200 or not report["page"]["official_https_host"]:
        report["status"] = "FAIL"
        return report

    markup = _decode(raw)
    script_srcs = [
        html.unescape(x).strip()
        for x in re.findall(r"(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
    ]
    report["page"]["script_srcs"] = script_srcs
    report["page"]["form_tags"] = [
        re.sub(r"\s+", " ", x)[:600]
        for x in re.findall(r"(?is)<form\b[^>]*>", markup)[:20]
    ]
    report["page"]["input_tags"] = [
        re.sub(r"\s+", " ", x)[:600]
        for x in re.findall(r"(?is)<input\b[^>]*>", markup)[:40]
    ]

    seen = set()
    for src in script_srcs:
        url = urljoin(final_url, src)
        if url in seen or not _same_official_host(url):
            continue
        seen.add(url)
        if not re.search(r"(?i)(?:lottery|history|kl8|draw|navigation)", url):
            continue
        record = {"src": src, "url": url}
        try:
            js_response = NET.get(url, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
            body = bytes(js_response.content)
            js_url = str(getattr(js_response, "url", "") or url)
            record.update({
                "http_status": int(js_response.status_code),
                "final_url": js_url,
                "content_type": str(js_response.headers.get("Content-Type", "")),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "official_https_host": _same_official_host(js_url),
                "attempts": list(getattr(js_response, "happy8_attempts", ())),
            })
            text = _decode(body)
            record["keyword_lines"] = _keywords(text)
            urls = []
            for token in re.findall(r"""(?is)(?:https?://[^'"\s<>]+|/[A-Za-z0-9_./?=&%{}$:-]{3,})""", text):
                token = html.unescape(token)[:600]
                if re.search(r"(?i)(?:api|lottery|history|draw|issue|query|kl8|previous)", token) and token not in urls:
                    urls.append(token)
                if len(urls) >= 120:
                    break
            record["url_hints"] = urls
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        report["scripts"].append(record)

    if any(x.get("keyword_lines") or x.get("url_hints") for x in report["scripts"]):
        report["contract_discovery"] = "FRONTEND_CONTRACT_HINTS_FOUND"
    else:
        report["contract_discovery"] = "NO_FRONTEND_CONTRACT_HINTS"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = inspect()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
