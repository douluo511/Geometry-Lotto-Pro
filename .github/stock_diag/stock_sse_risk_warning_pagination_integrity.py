from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import requests

ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
BEGIN = "2018-01-01"
END = "2026-10-06"
KEYWORD = "风险警示"
PAGE_SIZE = 100
MAX_PAGES = 40


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


def get(session, page_no: int, attempts: int = 4):
    params = {
        "isPagination": "true",
        "productId": "",
        "keyWord": KEYWORD,
        "securityType": "0101,120100,020100,020200,120200",
        "reportType2": "",
        "reportType": "ALL",
        "beginDate": BEGIN,
        "endDate": END,
        "pageHelp.pageSize": str(PAGE_SIZE),
        "pageHelp.pageNo": str(page_no),
        "pageHelp.beginPage": str(max(1, page_no - 2)),
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": str(page_no + 2),
        "jsonCallBack": "jsonpCallback",
    }
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
            time.sleep(1.0 * (2 ** (attempt - 1)))


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
    for n in names:
        v = row.get(n) if isinstance(row, dict) else None
        if v not in (None, ""):
            return str(v)
    return ""


def identity(row):
    return (
        pick(row, "SECURITY_CODE", "securityCode"),
        pick(row, "SSEDATE", "SSE_DATE", "publishDate", "END_DATE"),
        pick(row, "URL", "url"),
        pick(row, "BULLETIN_TITLE", "bulletinTitle", "TITLE", "title"),
    )


def main():
    s = requests.Session()
    pages = []
    total = None
    page_count = None
    expected_page_count = None
    all_ids = []
    page_sets = {}

    # Fetch page 1 first to establish server-declared denominator.
    first_obj, first_fetch = get(s, 1)
    first_rows = rows_from(first_obj)
    first_meta = page_meta(first_obj)
    total = int(first_meta.get("total")) if first_meta.get("total") is not None else None
    page_count = int(first_meta.get("pageCount")) if first_meta.get("pageCount") is not None else None
    expected_page_count = math.ceil(total / PAGE_SIZE) if total is not None else None

    target_pages = page_count if page_count is not None else expected_page_count
    if target_pages is None:
        raise RuntimeError("server did not expose total/pageCount")
    if target_pages > MAX_PAGES:
        raise RuntimeError(f"page count too large for bounded diagnostic: {target_pages}")

    def record(page_no, obj, fetch):
        rows = rows_from(obj)
        ids = [identity(r) for r in rows]
        ids_nonempty = [x for x in ids if any(x)]
        pset = set(ids_nonempty)
        page_sets[page_no] = pset
        all_ids.extend(ids_nonempty)
        pages.append({
            "page": page_no,
            "row_count": len(rows),
            "unique_identity_count": len(pset),
            "payload_sha256": fetch["payload_sha256"],
            "page_meta": page_meta(obj),
            "first_identity": ids_nonempty[0] if ids_nonempty else None,
            "last_identity": ids_nonempty[-1] if ids_nonempty else None,
        })

    record(1, first_obj, first_fetch)
    for page_no in range(2, target_pages + 1):
        obj, fetch = get(s, page_no)
        record(page_no, obj, fetch)
        time.sleep(0.12)

    # One beyond declared range is a boundary probe, not counted in canonical denominator.
    beyond_obj, beyond_fetch = get(s, target_pages + 1)
    beyond_rows = rows_from(beyond_obj)
    beyond_ids = set(identity(r) for r in beyond_rows if any(identity(r)))

    counts = Counter(all_ids)
    duplicated_identities = {k: v for k, v in counts.items() if v > 1}
    pair_overlaps = []
    for left in sorted(page_sets):
        for right in sorted(page_sets):
            if right <= left:
                continue
            overlap = page_sets[left] & page_sets[right]
            if overlap:
                pair_overlaps.append({
                    "left": left,
                    "right": right,
                    "count": len(overlap),
                    "sample": list(sorted(overlap))[:3],
                })

    canonical_unique = set(all_ids)
    expected_last_rows = None
    if total is not None and target_pages is not None:
        expected_last_rows = total - PAGE_SIZE * (target_pages - 1)
        if expected_last_rows == 0:
            expected_last_rows = PAGE_SIZE

    payload_hashes = [p["payload_sha256"] for p in pages]
    page_meta_consistent = all(
        int(p["page_meta"].get("total", -1)) == total
        and int(p["page_meta"].get("pageCount", -1)) == page_count
        for p in pages
    )
    page_no_echo_matches = all(
        int(p["page_meta"].get("pageNo", -1)) == p["page"] for p in pages
    )

    full_unique_matches_total = total is not None and len(canonical_unique) == total
    last_page_matches_remainder = (
        expected_last_rows is not None and pages[-1]["row_count"] == expected_last_rows
    )
    no_cross_page_overlap = not pair_overlaps
    payloads_unique = len(payload_hashes) == len(set(payload_hashes))
    beyond_empty = len(beyond_rows) == 0

    integrity_pass = all([
        page_meta_consistent,
        page_no_echo_matches,
        full_unique_matches_total,
        last_page_matches_remainder,
        no_cross_page_overlap,
        payloads_unique,
        beyond_empty,
    ])

    report = {
        "schema": "stock-sse-risk-warning-pagination-integrity-v1",
        "endpoint": ENDPOINT,
        "window": {"begin": BEGIN, "end": END},
        "keyword": KEYWORD,
        "server": {
            "total": total,
            "page_count": page_count,
            "expected_page_count": expected_page_count,
            "page_size": PAGE_SIZE,
            "expected_last_rows": expected_last_rows,
        },
        "observed": {
            "pages_fetched": len(pages),
            "raw_identity_rows": len(all_ids),
            "unique_identity_rows": len(canonical_unique),
            "duplicate_identity_count": len(duplicated_identities),
            "cross_page_overlap_pairs": len(pair_overlaps),
            "last_page_rows": pages[-1]["row_count"] if pages else None,
            "beyond_page": target_pages + 1,
            "beyond_page_rows": len(beyond_rows),
            "beyond_page_unique_identities": len(beyond_ids),
            "page_meta_consistent": page_meta_consistent,
            "page_no_echo_matches": page_no_echo_matches,
            "payloads_unique": payloads_unique,
            "full_unique_matches_total": full_unique_matches_total,
            "last_page_matches_remainder": last_page_matches_remainder,
            "no_cross_page_overlap": no_cross_page_overlap,
            "beyond_empty": beyond_empty,
        },
        "pages": pages,
        "overlaps": pair_overlaps[:100],
        "duplicate_samples": [
            {"identity": list(k), "count": v}
            for k, v in list(sorted(duplicated_identities.items(), key=lambda kv: (-kv[1], kv[0])))[:50]
        ],
        "beyond": {
            "fetch": beyond_fetch,
            "sample": [list(x) for x in list(sorted(beyond_ids))[:10]],
        },
        "adjudication": {
            "pagination_integrity": "PASS" if integrity_pass else "FAIL",
            "global_risk_warning_bulletin_corpus_complete": "SUPPORTED" if integrity_pass else "NOT VERIFIED",
            "event_semantics_complete": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_risk_warning_pagination_integrity.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    # This diagnostic intentionally exits nonzero if integrity is disproven.
    return 0 if integrity_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
