from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
TYPE_ENDPOINT = "https://www.bse.cn/disclosureInfoController/disclosure_type.do"
OUT = Path("stock_bse_exhaustive_risk_warning_corpus.json")
CANONICAL_OUT = Path("stock_bse_exhaustive_risk_warning_corpus.canonical.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE exhaustive corpus validator"
START = "2018-01-01"
END = "2026-09-30"
KEYWORDS = ["风险警示", "退市风险警示", "撤销风险警示"]
MAX_PAGES = 500
RETRIES = 3
NEED_FIELDS = [
    "companyCd",
    "companyName",
    "disclosureTitle",
    "disclosurePostTitle",
    "destFilePath",
    "publishDate",
    "xxfcbj",
    "fileExt",
    "xxzrlx",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def parse_jsonp(payload: str):
    text = payload.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not m:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(m.group(1))


def find_records(obj):
    records = []

    def walk(x):
        if isinstance(x, dict):
            keys = set(x)
            if {"companyCd", "publishDate"} <= keys and (
                "disclosureTitle" in keys or "destFilePath" in keys
            ):
                records.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    unique = {}
    for r in records:
        key = (
            str(r.get("companyCd") or "").strip(),
            str(r.get("publishDate") or "").strip(),
            str(r.get("disclosureTitle") or "").strip(),
            str(r.get("disclosurePostTitle") or "").strip(),
            str(r.get("destFilePath") or "").strip(),
        )
        unique[key] = r
    return [unique[k] for k in sorted(unique)]


def page_meta(obj):
    found = {}

    def walk(x):
        nonlocal found
        if found:
            return
        if isinstance(x, dict):
            keys = {"number", "numberOfElements", "size", "totalElements", "totalPages"}
            if keys <= set(x):
                found = {k: x.get(k) for k in sorted(keys)}
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return found


def request_json(session: requests.Session, url: str, *, params=None):
    attempts = []
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(
                url,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/javascript,application/json,text/plain,*/*",
                    "Referer": "https://www.bse.cn/disclosure/announcement.html",
                },
                timeout=(10, 30),
                allow_redirects=True,
            )
            meta = {
                "attempt": attempt,
                "status": r.status_code,
                "resolved_url": r.url,
                "content_type": r.headers.get("content-type"),
                "bytes": len(r.content),
                "sha256": sha256(r.content),
                "same_official_host": same_bse(r.url),
            }
            if r.status_code == 200 and r.content and same_bse(r.url):
                try:
                    obj = parse_jsonp(r.content.decode(r.encoding or "utf-8", errors="strict"))
                    meta["parse"] = "PASS"
                    attempts.append(meta)
                    return obj, {"attempts": attempts, "selected_attempt": attempt}
                except Exception as exc:
                    meta["parse"] = "FAIL"
                    meta["parse_error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(meta)
        except Exception as exc:
            attempts.append({"attempt": attempt, "exception": f"{type(exc).__name__}: {exc}"})
        if attempt < RETRIES:
            time.sleep(1.0 * attempt)
    return None, {"attempts": attempts, "selected_attempt": None}


def request_page(session: requests.Session, keyword: str, page: int):
    base = {
        "callback": "stockAiBseExhaustiveCb",
        "disclosureSubtype": "",
        "page": page,
        "companyCd": "",
        "isNewThree": 1,
        "startTime": START,
        "endTime": END,
        "keyword": keyword,
        "hyType": "",
    }
    pairs = list(base.items())
    pairs += [("disclosureType[]", "5"), ("xxfcbj[]", "2")]
    pairs += [("needFields[]", field) for field in NEED_FIELDS]

    attempts = []
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.post(
                ENDPOINT,
                data=pairs,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/javascript,application/json,text/plain,*/*",
                    "Referer": "https://www.bse.cn/disclosure/announcement.html",
                },
                timeout=(10, 30),
                allow_redirects=True,
            )
            meta = {
                "attempt": attempt,
                "page_requested": page,
                "status": r.status_code,
                "resolved_url": r.url,
                "content_type": r.headers.get("content-type"),
                "bytes": len(r.content),
                "sha256": sha256(r.content),
                "same_official_host": same_bse(r.url),
            }
            if r.status_code == 200 and r.content and same_bse(r.url):
                try:
                    obj = parse_jsonp(r.content.decode(r.encoding or "utf-8", errors="strict"))
                    meta["parse"] = "PASS"
                    attempts.append(meta)
                    return obj, {"attempts": attempts, "selected_attempt": attempt}
                except Exception as exc:
                    meta["parse"] = "FAIL"
                    meta["parse_error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(meta)
        except Exception as exc:
            attempts.append({"attempt": attempt, "page_requested": page, "exception": f"{type(exc).__name__}: {exc}"})
        if attempt < RETRIES:
            time.sleep(1.0 * attempt)
    return None, {"attempts": attempts, "selected_attempt": None}


def collect_type_values(obj):
    vals = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"distype", "dvalue", "disclosureType", "value"}:
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        vals.append(str(v).strip())
                    elif isinstance(v, list):
                        vals.extend(str(z).strip() for z in v if str(z).strip())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return list(dict.fromkeys(vals))


def canonical_record(r):
    return {
        "companyCd": str(r.get("companyCd") or "").strip(),
        "companyName": str(r.get("companyName") or "").strip(),
        "disclosureTitle": str(r.get("disclosureTitle") or "").strip(),
        "disclosurePostTitle": str(r.get("disclosurePostTitle") or "").strip(),
        "publishDate": str(r.get("publishDate") or "").strip(),
        "destFilePath": str(r.get("destFilePath") or "").strip(),
        "xxfcbj": str(r.get("xxfcbj") or "").strip(),
        "fileExt": str(r.get("fileExt") or "").strip(),
        "xxzrlx": str(r.get("xxzrlx") or "").strip(),
    }


def record_key(r):
    return (
        r["companyCd"],
        r["publishDate"],
        r["disclosureTitle"],
        r["disclosurePostTitle"],
        r["destFilePath"],
    )


def validate_transport(meta):
    attempt = meta.get("selected_attempt")
    if not attempt:
        return False
    selected = next((x for x in meta.get("attempts", []) if x.get("attempt") == attempt), {})
    return (
        selected.get("status") == 200
        and selected.get("same_official_host") is True
        and selected.get("parse") == "PASS"
    )


def replay_keyword(session: requests.Session, keyword: str):
    obj0, transport0 = request_page(session, keyword, 0)
    meta0 = page_meta(obj0) if obj0 is not None else {}
    base_ok = (
        validate_transport(transport0)
        and isinstance(meta0.get("number"), int)
        and meta0.get("number") == 0
        and isinstance(meta0.get("totalPages"), int)
        and isinstance(meta0.get("totalElements"), int)
        and meta0.get("totalPages") >= 0
        and meta0.get("totalElements") >= 0
    )
    total_pages = int(meta0.get("totalPages") or 0) if base_ok else 0
    total_elements = int(meta0.get("totalElements") or 0) if base_ok else 0
    bounded = total_pages <= MAX_PAGES

    pages = []
    all_records = []
    page_numbers = []
    consistent_denominator = base_ok and bounded
    no_page_transport_failures = base_ok and bounded

    if base_ok and bounded:
        for page in range(total_pages):
            if page == 0:
                obj, transport = obj0, transport0
            else:
                obj, transport = request_page(session, keyword, page)
            meta = page_meta(obj) if obj is not None else {}
            records = find_records(obj) if obj is not None else []
            transport_ok = validate_transport(transport)
            page_ok = (
                transport_ok
                and meta.get("number") == page
                and meta.get("totalPages") == total_pages
                and meta.get("totalElements") == total_elements
            )
            no_page_transport_failures = no_page_transport_failures and transport_ok
            consistent_denominator = consistent_denominator and page_ok
            page_numbers.append(meta.get("number"))
            canon = [canonical_record(r) for r in records]
            all_records.extend(canon)
            pages.append({
                "page": page,
                "status": "PASS" if page_ok else "NOT VERIFIED",
                "transport": transport,
                "page_meta": meta,
                "record_count": len(canon),
                "record_sha256": sha256(
                    (json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                ),
            })

    unique = {}
    duplicates = 0
    for r in all_records:
        k = record_key(r)
        if k in unique:
            duplicates += 1
        unique[k] = r
    canonical_records = [unique[k] for k in sorted(unique)]

    obj_n1, transport_n1 = request_page(session, keyword, total_pages) if base_ok and bounded else (None, {"attempts": [], "selected_attempt": None})
    n1_records = find_records(obj_n1) if obj_n1 is not None else []
    n1_empty = validate_transport(transport_n1) and len(n1_records) == 0 if base_ok and bounded else False

    contiguous_pages = page_numbers == list(range(total_pages)) if base_ok and bounded else False
    count_matches = len(canonical_records) == total_elements if base_ok and bounded else False
    no_cross_page_duplicates = duplicates == 0
    complete = (
        base_ok
        and bounded
        and no_page_transport_failures
        and consistent_denominator
        and contiguous_pages
        and count_matches
        and no_cross_page_duplicates
        and n1_empty
    )

    title_exact_hits = 0
    for r in canonical_records:
        title = r["disclosureTitle"] + r["disclosurePostTitle"]
        if keyword in title:
            title_exact_hits += 1

    return {
        "keyword": keyword,
        "status": "PASS" if complete else "NOT VERIFIED",
        "total_pages": total_pages if base_ok else None,
        "total_elements": total_elements if base_ok else None,
        "max_pages_guard": MAX_PAGES,
        "bounded": bounded if base_ok else False,
        "retrieved_page_count": len(pages),
        "retrieved_record_count": len(all_records),
        "canonical_unique_record_count": len(canonical_records),
        "duplicate_record_count": duplicates,
        "title_exact_hit_count": title_exact_hits,
        "page_numbers_contiguous": contiguous_pages,
        "consistent_server_denominator": consistent_denominator,
        "count_matches_total_elements": count_matches,
        "n_plus_one_empty": n1_empty,
        "page_summaries": pages,
        "n_plus_one_transport": transport_n1,
        "canonical_records": canonical_records,
    }


def main() -> int:
    session = requests.Session()

    type_obj, type_transport = request_json(session, TYPE_ENDPOINT, params={"type": 6})
    type_values = collect_type_values(type_obj) if type_obj is not None else []
    official_type_5 = "5" in type_values and validate_transport(type_transport)

    results = [replay_keyword(session, keyword) for keyword in KEYWORDS]
    all_complete = official_type_5 and all(r["status"] == "PASS" for r in results)

    union = {}
    keyword_membership = {}
    for result in results:
        keyword = result["keyword"]
        for r in result["canonical_records"]:
            k = record_key(r)
            union[k] = r
            keyword_membership.setdefault(k, []).append(keyword)

    union_records = []
    for k in sorted(union):
        item = dict(union[k])
        item["matched_keywords"] = sorted(set(keyword_membership[k]))
        union_records.append(item)

    canonical_payload = {
        "schema": "stock-bse-risk-warning-corpus-canonical-v1",
        "window": {"start": START, "end": END},
        "keywords": KEYWORDS,
        "records": union_records,
    }
    canonical_bytes = (
        json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    CANONICAL_OUT.write_bytes(canonical_bytes)

    adjudication = {
        "bse_marketwide_pagination_contract": "PASS" if all_complete else "NOT VERIFIED",
        "exhaustive_bse_keyword_event_corpus": "PASS" if all_complete else "NOT VERIFIED",
        "bse_historical_st_effective_date_reconstruction": "NOT VERIFIED",
        "bse_historical_st_pit": "NOT VERIFIED",
        "bse_historical_suspension_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "product_bytes_changed": False,
        "final_gate": "FAIL",
    }

    report = {
        "schema": "stock-bse-exhaustive-risk-warning-corpus-v1",
        "endpoint": ENDPOINT,
        "window": {"start": START, "end": END},
        "keywords": KEYWORDS,
        "official_type_contract": {
            "endpoint": TYPE_ENDPOINT,
            "transport": type_transport,
            "type_5_present": official_type_5,
            "candidate_values": type_values,
        },
        "results": [
            {k: v for k, v in r.items() if k != "canonical_records"}
            for r in results
        ],
        "canonical_union": {
            "unique_record_count": len(union_records),
            "sha256": sha256(canonical_bytes),
            "file": str(CANONICAL_OUT),
        },
        "adjudication": adjudication,
        "boundary": (
            "PASS proves exhaustive retrieval only for the frozen BSE disclosure type 5 and the three "
            "frozen risk-warning keyword queries, using the server-provided pagination denominator. "
            "It does not establish announcement effective dates, daily ST identity, suspension state, "
            "full Beijing historical ST/PIT, full A-share HISTORICAL_ST_PIT, Advanced Business, or Final."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "schema": report["schema"],
        "official_type_5": official_type_5,
        "keyword_statuses": {r["keyword"]: r["status"] for r in results},
        "keyword_total_pages": {r["keyword"]: r["total_pages"] for r in results},
        "keyword_total_elements": {r["keyword"]: r["total_elements"] for r in results},
        "canonical_union_count": len(union_records),
        "canonical_union_sha256": sha256(canonical_bytes),
        "adjudication": adjudication,
    }, ensure_ascii=True, sort_keys=True))

    return 0 if all_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
