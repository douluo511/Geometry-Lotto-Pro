"""Read-only source-native SSE suspension discovery; never qualifies product PIT."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/"
PRODUCT_BASE = "895fab5d4eb4be3d0b06e2c6c82c473911f4b8d1"
LIMIT = 8 * 1024 * 1024

def sha(payload):
    return hashlib.sha256(payload).hexdigest()

def official(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and not parts.username and not parts.password and parts.port in (None, 443) and (parts.hostname == "sse.com.cn" or (parts.hostname or "").endswith(".sse.com.cn"))

class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official(newurl):
            raise ValueError("redirect outside official HTTPS SSE origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "script" and values.get("src"):
            self.urls.append(urljoin(PAGE, values["src"]))
        # SSE declares page modules on js_require_on_page, loaded via RequireJS.
        if values.get("js_files"):
            self.urls.extend(urljoin(PAGE, value.strip()) for value in values["js_files"].split(",") if value.strip())

def decode(raw, media):
    encodings = []
    match = re.search(r"charset\s*=\s*([A-Za-z0-9_-]+)", media, re.I)
    if match:
        encodings.append(match.group(1))
    encodings += ["utf-8-sig", "gb18030"]
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding), encoding
        except (UnicodeError, LookupError):
            pass
    raise ValueError("source bytes cannot be decoded with declared/UTF8/GB18030 charset")

def fetch(url, directory, index):
    if not official(url):
        return {"url": url, "status": "REJECTED", "reason": "nonofficial_or_insecure_url"}
    errors = []
    for attempt in range(1, 3):
        recorded = datetime.now(timezone.utc).isoformat()
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; read-only source research)", "Referer": PAGE, "Accept": "*/*"})
            with build_opener(Redirect()).open(req, timeout=20) as response:
                actual = response.geturl()
                if not official(actual) or response.status != 200:
                    raise ValueError("source HTTP identity/status rejected")
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT or not raw:
                    raise ValueError("empty or oversized primary source")
                media = response.headers.get("Content-Type", "")
                last_modified = response.headers.get("Last-Modified")
            text, encoding = decode(raw, media)
            if index != 0 and "<html" in text[:1000].lower():
                raise ValueError("script endpoint returned HTML challenge/error")
            path = directory / f"source-{index:03d}.raw"
            path.write_bytes(raw)
            return {"url": url, "actual_url": actual, "status": "PASS", "http_status": 200, "attempt": attempt, "recorded_at_utc": recorded, "response_last_modified": last_modified, "publication_time": "NOT VERIFIED", "sha256": sha(raw), "bytes": len(raw), "content_type": media, "encoding": encoding, "raw_path": path.name, "text": text}
        except (HTTPError, URLError, socket.timeout, TimeoutError, ValueError) as exc:
            errors.append({"attempt": attempt, "type": type(exc).__name__, "http_status": getattr(exc, "code", None)})
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                break
            if isinstance(exc, ValueError):
                break
            time.sleep(0.8)
    return {"url": url, "status": "FAIL", "errors": errors}

def candidates(receipts):
    result = []
    for receipt in receipts:
        text = receipt.get("text", "")
        # Technical query identifiers are evidence candidates ONLY; no JS is executed.
        for match in re.finditer(r"['\"]?(?:sqlId|SQLID|sqlid)['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", text):
            result.append({"sql_id": match.group(1), "source_url": receipt["url"], "source_sha256": receipt["sha256"], "offset": match.start(), "context": text[max(0, match.start()-500):match.end()+1500]})
    return result

def source_contexts(receipts):
    result = []
    for receipt in receipts:
        text = receipt.get("text", "")
        count = 0
        previous_end = -1
        for match in re.finditer(r"COMMON_SSE|sqlId|SQLID|sseQueryUrl|query\.sse|suspension|commonQuery|pageHelp|startDate|endDate|searchDate|START_DATE|END_DATE|js_files", text, re.I):
            if match.start() < previous_end:
                continue
            begin, end = max(0, match.start()-400), min(len(text), match.end()+2000)
            result.append({"source_url": receipt["url"], "source_sha256": receipt.get("sha256"), "offset": match.start(), "context": text[begin:end]})
            previous_end = end
            count += 1
            if count >= 12:
                break
    return result

def self_test():
    assert official(PAGE)
    for invalid in ("http://www.sse.com.cn/x", "https://sse.com.cn.evil.example/x", "https://evil.example/x", "https://user:pass@www.sse.com.cn/x", "https://www.sse.com.cn:8443/x"):
        assert not official(invalid), invalid
    parsed = Scripts()
    parsed.feed('<script src="./actual.js"></script><script src="//query.sse.com.cn/a.js"></script>')
    assert parsed.urls == [urljoin(PAGE, "./actual.js"), "https://query.sse.com.cn/a.js"]
    modules = Scripts()
    modules.feed('<div class="js_require_on_page" js_files="/actual/declared.js"></div>')
    assert modules.urls == ["https://www.sse.com.cn/actual/declared.js"]
    assert decode("停复牌".encode("gb18030"), "text/html; charset=gb18030")[0] == "停复牌"
    assert candidates([{"url": PAGE, "sha256": "a"*64, "text": "sqlId: 'REAL_SOURCE_ID'"}])[0]["sql_id"] == "REAL_SOURCE_ID"
    assert candidates([{"url": PAGE, "sha256": "b"*64, "text": '"sqlId": "REAL_QUOTED_ID"'}])[0]["sql_id"] == "REAL_QUOTED_ID"
    print("SSE FIRST-PARTY SOURCE DISCOVERY BOUNDARIES 11/11 PASS")

def discover(directory):
    directory.mkdir(parents=True, exist_ok=False)
    page = fetch(PAGE, directory, 0)
    receipts = [page]
    if page["status"] == "PASS":
        parser = Scripts()
        parser.feed(page["text"])
        urls = list(dict.fromkeys(parser.urls))
        if len(urls) > 60:
            raise ValueError("source page script count exceeds explicit bounded discovery")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            receipts += list(pool.map(lambda pair: fetch(pair[1], directory, pair[0]), enumerate(urls, 1)))
    found = candidates(receipts)
    report = {
        "schema": "stock-sse-official-suspension-discovery-v1",
        "source_product_base_sha": PRODUCT_BASE,
        "diagnostic_head_sha": os.environ.get("SOURCE_SHA"),
        "source_page": PAGE,
        "status": "PASS" if page["status"] == "PASS" and found else "FAIL",
        "scope": "actual official HTML/JS query-source discovery only",
        "receipts": [{k: v for k, v in receipt.items() if k != "text"} for receipt in receipts],
        "native_query_candidates": found,
        "observed_technical_source_contexts": source_contexts(receipts),
        "query_parameter_semantics": "NOT VERIFIED",
        "historical_daily_state": "NOT VERIFIED",
        "SSE_SZSE_BSE_qualified_historical_pit": "NOT VERIFIED",
        "repository_independence": "NOT VERIFIED",
        "final_gate": "FAIL",
    }
    (directory / "discovery.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.output:
        raise SystemExit(discover(args.output))
    else:
        parser.error("--self-test or --output required")
