"""Read-only source-native SSE suspension discovery; never qualifies product PIT."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import socket
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
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

MODULE = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
MODULE_SHA = "32fc98ea41e599f457609247ba68defb82e6d855aa2551da6923dbf7e44153a7"
WINDOWS = [("2018-11-19", "2018-11-20"), ("2025-01-06", "2025-01-07"), ("2026-09-29", "2026-09-30")]
BOND_BUSINESS = {"CP": "convertible_bond", "GP": "convertible_bond", "CB": "conversion", "GB": "conversion", "CR": "repurchase", "GR": "repurchase"}
INTRADAY = {"930": "09:30-10:30", "AM": "morning", "PM": "afternoon"}

def day(value, compact=False):
    pattern = r"[0-9]{8}" if compact else r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("noncanonical_native_day")
    if compact:
        value = value[:4]+"-"+value[4:6]+"-"+value[6:]
    return date.fromisoformat(value)

def integer(value):
    if isinstance(value, bool):
        raise ValueError("boolean_pagination")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise ValueError("invalid_pagination_integer")

def parse_page(raw, page_number, page_size, prior=None):
    text = raw.decode("utf-8-sig")
    # Parse JSON as data only. No callback or remote JS execution.
    obj = json.loads(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("result"), list) or not isinstance(obj.get("pageHelp"), dict):
        raise ValueError("missing_result_or_native_pagination")
    meta = obj["pageHelp"]
    counts = {key: integer(meta[key]) for key in ("pageNo", "pageSize", "pageCount", "total")}
    if counts["pageNo"] != page_number or counts["pageSize"] != page_size:
        raise ValueError("wrong_native_page_identity")
    expected_pages = (counts["total"]+page_size-1)//page_size
    if counts["pageCount"] not in ({0, 1} if counts["total"] == 0 else {expected_pages}):
        raise ValueError("native_page_count_disagrees_with_total")
    if prior is not None and any(counts[key] != prior[key] for key in ("pageSize", "pageCount", "total")):
        raise ValueError("native_page_denominator_drift")
    expected_rows = max(0, min(page_size, counts["total"]-(page_number-1)*page_size))
    if len(obj["result"]) != expected_rows:
        raise ValueError("missing_or_extra_native_page_rows")
    if any(not isinstance(row, dict) for row in obj["result"]):
        raise ValueError("native_row_not_object")
    return obj["result"], counts

def complete_pages(pages, expected):
    if len(pages) != max(1, expected["pageCount"]):
        raise ValueError("missing_native_page")
    rows = [row for page in pages for row in page]
    if len(rows) != expected["total"]:
        raise ValueError("full_native_row_denominator_mismatch")
    digests = [sha(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) for row in rows]
    if len(digests) != len(set(digests)):
        raise ValueError("duplicate_native_row_across_pages")
    return rows

def event_candidate(row, flavor, begin, end):
    if flavor == "legacy":
        code = row.get("PRODUCT_CODE")
        name = row.get("PRODUCT_NAME")
        native_start = row.get("STOP_DATE")
        native_end = None
        # Historical source may expose a native date-time; only its explicit date is parsed.
        parsed_start = day(native_start[:10]) if isinstance(native_start, str) else None
        business = row.get("CONTROLTYPE")
        duration = row.get("STOP_TIME")
        reason = row.get("STOP_REASON")
    else:
        code = row.get("productCode")
        name = row.get("productName")
        native_start = row.get("startStopDate")
        native_end = row.get("endStopDate")
        parsed_start = day(native_start, compact=True) if native_start else None
        if native_end:
            day(native_end, compact=True)
        business = row.get("controlType")
        duration = row.get("stopTime")
        reason = row.get("stopReason")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("native_security_code_missing_or_nonASCII")
    if parsed_start is None:
        raise ValueError("native_effective_start_missing")
    if parsed_start > day(end):
        raise ValueError("native_effective_date_after_requested_window")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("native_security_name_missing")
    business_scope = BOND_BUSINESS.get(business, "UNRESOLVED_NATIVE_BUSINESS_TYPE")
    if business in BOND_BUSINESS:
        identity = "EXCLUDED_BOND_BUSINESS"
    elif code.startswith(("600", "601", "603", "605", "688")):
        identity = "EQUITY_CODE_CANDIDATE_ONLY"
    else:
        identity = "UNRESOLVED_SECURITY_CLASS"
    duration_scope = "REPORTED_FULL_DAY_ONLY" if duration == "WH" else ("REPORTED_INTRADAY_ONLY" if duration in INTRADAY else "UNRESOLVED_NATIVE_DURATION")
    return {
        "native_security_code": code, "native_security_name": name,
        "native_business_type": business, "business_scope": business_scope,
        "identity_status": identity, "asof_issuer_authority": "NOT VERIFIED",
        "native_effective_start": native_start, "native_effective_end": native_end,
        "explicit_start_day": parsed_start.isoformat(), "native_duration": duration,
        "duration_scope": duration_scope, "native_reason": reason,
        "native_record_type": row.get("type"),
        "source_query_window": [begin, end], "publication_time": "NOT VERIFIED",
        "actual_observed_resume": "NOT VERIFIED", "daily_ST": "NOT VERIFIED",
        "qualified_daily_suspension": "NOT VERIFIED",
        "raw_row_sha256": sha(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
    }

def historical_self_test():
    def fails(function):
        try:
            function()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return
        raise AssertionError("FALSE SOURCE PASS: malformed or incomplete native evidence accepted")
    def payload(rows, **updates):
        meta = {"pageNo": 1, "pageSize": 2, "pageCount": 1, "total": len(rows)}
        meta.update(updates)
        return json.dumps({"result": rows, "pageHelp": meta}).encode()
    sample = {"productCode": "600000", "productName": "TEST ONLY", "startStopDate": "20260930", "endStopDate": "", "controlType": "", "stopTime": "WH", "stopReason": "test"}
    parsed, counts = parse_page(payload([sample]), 1, 2)
    assert complete_pages([parsed], counts) == [sample]
    bad = [b"[]", b'{"result":[]}', payload([sample], pageNo=2), payload([sample], pageSize=3), payload([sample], pageCount=2), payload([sample], total=2)]
    for item in bad:
        fails(lambda item=item: parse_page(item, 1, 2))
    fails(lambda: complete_pages([], counts))
    fails(lambda: complete_pages([[sample], [sample]], {"total": 2, "pageCount": 2}))
    fails(lambda: parse_page(payload([sample], total=1), 1, 2, {"total": 2, "pageCount": 1, "pageSize": 2}))
    fails(lambda: event_candidate(dict(sample, startStopDate="20261008"), "new", "2026-09-30", "2026-09-30"))
    fails(lambda: event_candidate(dict(sample, startStopDate="20260230"), "new", "2026-09-30", "2026-09-30"))
    bond = event_candidate(dict(sample, controlType="CB"), "new", "2026-09-30", "2026-09-30")
    assert bond["identity_status"] == "EXCLUDED_BOND_BUSINESS"
    intraday = event_candidate(dict(sample, stopTime="930"), "new", "2026-09-30", "2026-09-30")
    assert intraday["duration_scope"] == "REPORTED_INTRADAY_ONLY" and intraday["qualified_daily_suspension"] == "NOT VERIFIED"
    empty, empty_counts = parse_page(payload([]), 1, 2)
    assert complete_pages([empty], empty_counts) == []
    assert event_candidate(sample, "new", "2026-09-30", "2026-09-30")["daily_ST"] == "NOT VERIFIED"
    print("SSE NATIVE PAGINATION / WRONG DATE / BOND / INTRADAY / ABSENCE CONTROLS 16/16 PASS")

def capture(source_directory, directory):
    directory.mkdir(parents=True, exist_ok=False)
    report = {"schema": "stock-sse-historical-suspension-source-capture-v1", "status": "FAIL", "scope": "three explicit two-day sample windows, native source transport/pagination ONLY", "source_product_base_sha": PRODUCT_BASE, "diagnostic_head_sha": os.environ.get("SOURCE_SHA"), "windows": WINDOWS, "queries": [], "event_candidates": [], "historical_daily_state": "NOT VERIFIED", "SSE_SZSE_BSE_qualified_historical_pit": "NOT VERIFIED", "final_gate": "FAIL"}
    try:
        discovery = json.loads((source_directory / "discovery.json").read_text(encoding="utf-8"))
        if discovery.get("diagnostic_head_sha") != os.environ.get("SOURCE_SHA") or discovery.get("status") != "PASS":
            raise ValueError("wrong_head_or_failed_source_discovery")
        module = next(item for item in discovery["receipts"] if item["url"] == MODULE)
        module_raw = (source_directory / module["raw_path"]).read_bytes()
        if sha(module_raw) != MODULE_SHA or module["sha256"] != MODULE_SHA:
            raise ValueError("official_native_query_module_drift")
        page_receipt = discovery["receipts"][0]
        html_raw = (source_directory / page_receipt["raw_path"]).read_bytes()
        if sha(html_raw) != page_receipt["sha256"]:
            raise ValueError("official_page_source_binding_mismatch")
        html = decode(html_raw, page_receipt["content_type"])[0]
        native = decode(module_raw, module["content_type"])[0]
        match = re.search(r'var\s+sseQueryURL\s*=\s*["\']([^"\']+)["\']', html)
        if match is None:
            raise ValueError("source_native_query_origin_missing")
        origin = urljoin(PAGE, match.group(1))
        if not official(origin):
            raise ValueError("source_native_query_origin_not_officialHTTPS")
        for token in ("COMMON_SSE_XXPL_JYTS_TFPXX_L", "SEARCH_DATE", "sseQuery/commonQuery.do", "GW_PL_JYTS_TFPXX", "commonSoaQuery.do", "startStopDate", "endStopDate", "pageHelp.pageCount", "pageHelp.total", "pageHelp.pageNo", "pageHelp.pageSize"):
            if token not in native:
                raise ValueError("source_native_query_contract_missing:"+token)
        report["query_source_binding"] = {"html_sha256": sha(html_raw), "module_url": MODULE, "module_sha256": sha(module_raw), "query_origin": origin, "retrieved_at_utc": module["recorded_at_utc"], "publication_time": "NOT VERIFIED"}
        index = 100
        for begin, end in WINDOWS:
            for flavor in ("legacy", "new"):
                if flavor == "legacy":
                    endpoint = urljoin(origin, "sseQuery/commonQuery.do")
                    params = {"isPagination": "true", "sqlId": "COMMON_SSE_XXPL_JYTS_TFPXX_L", "SEARCH_DATE": end, "pageHelp.pageSize": 25, "pageHelp.pageNo": 1, "pageHelp.beginPage": 1, "pageHelp.cacheSize": 1, "pageHelp.endPage": 1}
                else:
                    endpoint = urljoin(origin, "commonSoaQuery.do")
                    params = {"isPagination": "true", "sqlId": "GW_PL_JYTS_TFPXX", "pageHelp.pageSize": 25, "pageHelp.pageNo": 1, "productCode": "", "keyWords": "", "startStopDate": begin.replace("-", ""), "endStopDate": end.replace("-", "")}
                query = {"flavor": flavor, "window": [begin, end], "endpoint": endpoint, "params": dict(params), "status": "FAIL", "receipts": [], "publication_time": "NOT VERIFIED"}
                report["queries"].append(query)
                pages, expected, page_number = [], None, 1
                while True:
                    params["pageHelp.pageNo"] = page_number
                    if flavor == "legacy":
                        params["pageHelp.beginPage"] = page_number
                        params["pageHelp.endPage"] = page_number
                    index += 1
                    receipt = fetch(endpoint+"?"+urlencode(params), directory, index)
                    query["receipts"].append({k: v for k, v in receipt.items() if k != "text"})
                    if receipt["status"] != "PASS":
                        raise ValueError("native_history_transport_failed")
                    raw = (directory / receipt["raw_path"]).read_bytes()
                    rows, counts = parse_page(raw, page_number, 25, expected)
                    expected = expected or counts
                    if expected["pageCount"] > 40:
                        raise ValueError("sample_query_exceeds_bounded_page_budget")
                    pages.append(rows)
                    if page_number >= max(1, expected["pageCount"]):
                        break
                    page_number += 1
                    time.sleep(0.2)
                native_rows = complete_pages(pages, expected)
                query["native_pagination"] = expected
                query["native_row_count"] = len(native_rows)
                query["record_date_fields"] = sorted({key for row in native_rows for key in row if "date" in key.lower() or "time" in key.lower()})
                query["native_fields"] = sorted({key for row in native_rows for key in row})
                query["sample_rows"] = native_rows[:3]
                query["unresolved_native_rows"] = []
                candidates = []
                for row in native_rows:
                    try:
                        candidate = event_candidate(row, flavor, begin, end)
                        candidate["query_index"] = len(report["queries"])-1
                        candidates.append(candidate)
                    except (ValueError, TypeError) as exc:
                        query["unresolved_native_rows"].append({"raw_row": row, "error": type(exc).__name__+": "+str(exc), "qualified_daily_suspension": "NOT VERIFIED"})
                report["event_candidates"].extend(candidates)
                query["status"] = "PASS" if not query["unresolved_native_rows"] else "FAIL"
        report["status"] = "PASS" if all(query["status"] == "PASS" for query in report["queries"]) else "FAIL"
    except Exception as exc:
        report["error"] = type(exc).__name__+": "+str(exc)
    finally:
        report["qualified_record_count"] = 0
        report["candidate_count"] = len(report["event_candidates"])
        (directory / "historical-capture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--capture-from", type=Path)
    parser.add_argument("--capture-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        historical_self_test()
    elif args.capture_from and args.capture_output:
        raise SystemExit(capture(args.capture_from, args.capture_output))
    elif args.output:
        raise SystemExit(discover(args.output))
    else:
        parser.error("--self-test or --output required")
