from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

import requests

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
BEGIN = "2018-01-01"
END = "2026-10-06"
KEYWORD = "风险警示"
PAGE_SIZE = 100
PROBE_PAGES = (1, 2, 31, 32)


def parse(text: str):
    t = text.strip()
    try:
        return json.loads(t), "json"
    except Exception:
        pass
    m = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", t, flags=re.S)
    if m:
        return json.loads(m.group(1)), "jsonp"
    raise ValueError("response is neither JSON nor simple JSONP")


def base_params():
    return {
        "isPagination": "true",
        "productId": "",
        "keyWord": KEYWORD,
        "securityType": "0101,120100,020100,020200,120200",
        "reportType2": "",
        "reportType": "ALL",
        "beginDate": BEGIN,
        "endDate": END,
        "pageHelp.pageSize": str(PAGE_SIZE),
        "jsonCallBack": "jsonpCallback",
    }


def mode_params(mode: str, page_no: int):
    params = base_params()
    if mode == "page_no_only":
        params["pageHelp.pageNo"] = str(page_no)
    elif mode == "page_no_cache_only":
        params["pageHelp.pageNo"] = str(page_no)
        params["pageHelp.cacheSize"] = "1"
    elif mode == "fixed_navigation_window":
        params.update({
            "pageHelp.pageNo": str(page_no),
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "5",
        })
    elif mode == "exact_navigation_window":
        params.update({
            "pageHelp.pageNo": str(page_no),
            "pageHelp.beginPage": str(page_no),
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": str(page_no),
        })
    elif mode == "sliding_navigation_window":
        params.update({
            "pageHelp.pageNo": str(page_no),
            "pageHelp.beginPage": str(max(1, page_no - 2)),
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": str(page_no + 2),
        })
    else:
        raise ValueError(f"unknown pagination mode: {mode}")
    return params


def fetch(session, mode: str, page_no: int, attempts: int = 3):
    params = mode_params(mode, page_no)
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                ENDPOINT,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Referer": REFERER,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty payload")
            obj, kind = parse(r.content.decode(r.encoding or "utf-8", errors="replace"))
            return obj, {
                "attempt": attempt,
                "prior_errors": errors,
                "http_status": r.status_code,
                "payload_sha256": hashlib.sha256(r.content).hexdigest(),
                "parsed_as": kind,
                "url": r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(2 ** (attempt - 1))


def rows_from(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("result"), list):
            return obj["result"]
        ph = obj.get("pageHelp")
        if isinstance(ph, dict):
            for key in ("data", "result"):
                if isinstance(ph.get(key), list):
                    return ph[key]
    return []


def page_meta(obj):
    ph = obj.get("pageHelp") if isinstance(obj, dict) else None
    if not isinstance(ph, dict):
        return {}
    return {k: ph.get(k) for k in ("pageNo", "pageSize", "pageCount", "total", "beginPage", "endPage")}


def pick(row, *names):
    for name in names:
        value = row.get(name) if isinstance(row, dict) else None
        if value not in (None, ""):
            return str(value)
    return ""


def identity(row):
    return (
        pick(row, "SECURITY_CODE", "securityCode"),
        pick(row, "SSEDATE", "SSE_DATE", "publishDate", "END_DATE"),
        pick(row, "URL", "url"),
        pick(row, "BULLETIN_TITLE", "bulletinTitle", "TITLE", "title"),
    )


def summarize_probe(page_no, obj, meta):
    rows = rows_from(obj)
    ids = [identity(r) for r in rows]
    ids = [x for x in ids if any(x)]
    return {
        "page": page_no,
        "row_count": len(rows),
        "unique_identity_count": len(set(ids)),
        "identities": ids,
        "payload_sha256": meta["payload_sha256"],
        "page_meta": page_meta(obj),
        "fetch": meta,
        "first_identity": list(ids[0]) if ids else None,
        "last_identity": list(ids[-1]) if ids else None,
    }


def adjudicate(mode, probes):
    by_page = {p["page"]: p for p in probes}
    first = by_page[1]
    total = int(first["page_meta"].get("total") or 0)
    page_count = int(first["page_meta"].get("pageCount") or 0)
    expected_page_count = math.ceil(total / PAGE_SIZE) if total else 0
    expected_last_rows = total - PAGE_SIZE * (page_count - 1) if page_count else 0
    if expected_last_rows == 0 and total:
        expected_last_rows = PAGE_SIZE

    sets = {n: set(by_page[n]["identities"]) for n in PROBE_PAGES}
    overlaps = {}
    for left, right in ((1, 2), (1, 31), (2, 31), (31, 32)):
        overlaps[f"{left}-{right}"] = len(sets[left] & sets[right])

    metadata_denominator_consistent = all(
        int(p["page_meta"].get("total") or -1) == total
        and int(p["page_meta"].get("pageCount") or -1) == page_count
        for p in probes
    )
    page_echo_matches = all(
        int(by_page[n]["page_meta"].get("pageNo") or -1) == n
        for n in (1, 2, 31)
    )
    checks = {
        "server_total_positive": total > 0,
        "page_count_matches_total": page_count == expected_page_count == 31,
        "metadata_denominator_consistent": metadata_denominator_consistent,
        "page_echo_matches": page_echo_matches,
        "page_1_full": by_page[1]["row_count"] == PAGE_SIZE,
        "page_2_full": by_page[2]["row_count"] == PAGE_SIZE,
        "page_31_expected_remainder": by_page[31]["row_count"] == expected_last_rows == 9,
        "page_32_empty": by_page[32]["row_count"] == 0,
        "page_1_2_disjoint": overlaps["1-2"] == 0,
        "page_1_31_disjoint": overlaps["1-31"] == 0,
        "page_2_31_disjoint": overlaps["2-31"] == 0,
        "page_31_32_disjoint": overlaps["31-32"] == 0,
        "within_page_unique": all(p["row_count"] == p["unique_identity_count"] for p in probes),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "mode": mode,
        "status": status,
        "server": {
            "total": total,
            "page_count": page_count,
            "expected_page_count": expected_page_count,
            "expected_last_rows": expected_last_rows,
            "page_size": PAGE_SIZE,
        },
        "checks": checks,
        "overlaps": overlaps,
        "probes": [
            {k: v for k, v in p.items() if k != "identities"}
            for p in probes
        ],
    }


def main():
    session = requests.Session()
    modes = [
        "page_no_only",
        "page_no_cache_only",
        "fixed_navigation_window",
        "exact_navigation_window",
        "sliding_navigation_window",
    ]
    results = []
    errors = []

    for mode in modes:
        probes = []
        try:
            for page_no in PROBE_PAGES:
                obj, meta = fetch(session, mode, page_no)
                probes.append(summarize_probe(page_no, obj, meta))
                time.sleep(0.15)
            results.append(adjudicate(mode, probes))
        except Exception as exc:
            errors.append({"mode": mode, "error": f"{type(exc).__name__}: {exc}"})
            results.append({"mode": mode, "status": "ERROR", "error": errors[-1]["error"]})

    passing = [r["mode"] for r in results if r.get("status") == "PASS"]
    supported = len(passing) >= 1

    report = {
        "schema": "stock-sse-risk-warning-pagination-contract-v2",
        "endpoint": ENDPOINT,
        "window": {"begin": BEGIN, "end": END},
        "keyword": KEYWORD,
        "probe_pages": list(PROBE_PAGES),
        "modes": results,
        "errors": errors,
        "supported_modes": passing,
        "adjudication": {
            "pagination_parameter_contract": "SUPPORTED" if supported else "NOT VERIFIED",
            "global_risk_warning_bulletin_corpus_complete": "NOT VERIFIED",
            "event_semantics_complete": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This controlled four-page probe may identify a valid official SSE pagination parameter "
            "contract. It does not exhaust all pages or promote the global corpus to complete; a "
            "separate full-corpus rerun using the supported contract is required."
        ),
    }
    Path("stock_sse_risk_warning_pagination_integrity.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if supported else 2


if __name__ == "__main__":
    raise SystemExit(main())
