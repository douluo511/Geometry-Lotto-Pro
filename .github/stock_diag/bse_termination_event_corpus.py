from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
TYPE_ENDPOINT = "https://www.bse.cn/disclosureInfoController/disclosure_type.do"
START = "2018-01-01"
END = "2026-09-30"
KEYWORDS = ["终止上市", "退市整理期", "摘牌"]
NEED_FIELDS = [
    "companyCd", "companyName", "disclosureTitle", "disclosurePostTitle",
    "destFilePath", "publishDate", "xxfcbj", "fileExt", "xxzrlx",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE termination corpus"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_bse(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def parse_json_or_jsonp(raw: bytes):
    text = raw.decode("utf-8-sig", errors="strict").strip()
    try:
        return json.loads(text), "JSON"
    except Exception:
        pass
    m = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not m:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(m.group(1)), "JSONP"


def request(
    session: requests.Session,
    *,
    method: str,
    url: str,
    data=None,
    params=None,
) -> tuple[bytes, dict]:
    attempts = []
    last_error = None
    for attempt in range(1, 4):
        try:
            kwargs = dict(
                headers={
                    "User-Agent": UA,
                    "Accept": "application/javascript,application/json,text/plain,*/*",
                    "Referer": "https://www.bse.cn/disclosure/announcement.html",
                },
                timeout=(15, 35),
                allow_redirects=True,
            )
            if method == "GET":
                r = session.get(url, params=params, **kwargs)
            else:
                r = session.post(url, data=data, **kwargs)
            rec = {
                "attempt": attempt,
                "status": int(r.status_code),
                "resolved_url": r.url,
                "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
            }
            attempts.append(rec)
            if not same_bse(r.url):
                raise RuntimeError(f"non-BSE redirect: {r.url}")
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise RuntimeError(f"retryable BSE HTTP {r.status_code}")
            elif r.status_code != 200:
                raise RuntimeError(f"non-retryable BSE HTTP {r.status_code}")
            elif not r.content:
                raise RuntimeError("empty BSE response")
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
            attempts.append({
                "attempt": attempt,
                "transport_error": f"{type(exc).__name__}: {exc}",
            })
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    raise RuntimeError(f"BSE request failed; url={url}; last_error={last_error!r}; attempts={attempts}")


def walk_records(obj) -> list[dict]:
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
    return records


def page_meta(obj) -> dict:
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


def row_id(row: dict) -> tuple[str, ...]:
    return (
        str(row.get("companyCd") or "").strip(),
        str(row.get("publishDate") or "").strip(),
        str(row.get("disclosureTitle") or ""),
        str(row.get("disclosurePostTitle") or ""),
        str(row.get("destFilePath") or ""),
    )


def row_view(row: dict, keyword: str) -> dict:
    title = str(row.get("disclosureTitle") or "") + str(row.get("disclosurePostTitle") or "")
    return {
        "keyword": keyword,
        "companyCd": str(row.get("companyCd") or "").strip(),
        "companyName": row.get("companyName"),
        "publishDate": row.get("publishDate"),
        "title": title,
        "destFilePath": row.get("destFilePath"),
        "fileExt": row.get("fileExt"),
        "xxzrlx": row.get("xxzrlx"),
        "xxfcbj": row.get("xxfcbj"),
        "exact_keyword_in_title": keyword in title,
    }


def fetch_type_contract(session: requests.Session) -> dict:
    raw, transport = request(
        session,
        method="GET",
        url=TYPE_ENDPOINT,
        params={"type": 6},
    )
    obj, mode = parse_json_or_jsonp(raw)
    values = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"distype", "dvalue", "disclosureType", "value"}:
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        values.append(str(v).strip())
                    elif isinstance(v, list):
                        values.extend(str(z).strip() for z in v if str(z).strip())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return {
        "transport": transport,
        "parse_mode": mode,
        "values": list(dict.fromkeys(values)),
        "type_5_present": "5" in values,
        "raw_sha256": sha256_bytes(raw),
    }


def fetch_page(session: requests.Session, keyword: str, page: int) -> tuple[bytes, dict, object, str]:
    base = [
        ("callback", "stockAiBseTerminationCb"),
        ("disclosureSubtype", ""),
        ("page", str(page)),
        ("companyCd", ""),
        ("isNewThree", "1"),
        ("startTime", START),
        ("endTime", END),
        ("keyword", keyword),
        ("hyType", ""),
        ("disclosureType[]", "5"),
        ("xxfcbj[]", "2"),
    ]
    base.extend(("needFields[]", field) for field in NEED_FIELDS)
    raw, transport = request(session, method="POST", url=ENDPOINT, data=base)
    obj, mode = parse_json_or_jsonp(raw)
    return raw, transport, obj, mode


def canonical_sha(rows: list[dict]) -> str:
    blob = (
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return sha256_bytes(blob)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--canonical", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.canonical.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    type_contract = fetch_type_contract(session)
    if not type_contract["type_5_present"]:
        raise RuntimeError("official disclosure type contract no longer exposes type 5")

    keyword_reports = []
    combined = {}

    for keyword_index, keyword in enumerate(KEYWORDS):
        raw0, transport0, obj0, mode0 = fetch_page(session, keyword, 0)
        meta0 = page_meta(obj0)
        required = {"number", "numberOfElements", "size", "totalElements", "totalPages"}
        if required - set(meta0):
            raise RuntimeError(f"{keyword}: page0 missing pagination fields: {sorted(required-set(meta0))}")
        if int(meta0["number"]) != 0:
            raise RuntimeError(f"{keyword}: page0 returned number={meta0['number']}")
        total_pages = int(meta0["totalPages"])
        total_elements = int(meta0["totalElements"])
        page_size = int(meta0["size"])
        if total_pages < 0 or total_pages > 1000 or total_elements < 0 or page_size <= 0:
            raise RuntimeError(
                f"{keyword}: unsafe denominator pages={total_pages}, total={total_elements}, size={page_size}"
            )

        unique = {}
        receipts = []
        modes = set()
        for page_no in range(total_pages):
            if page_no == 0:
                raw, transport, obj, mode = raw0, transport0, obj0, mode0
            else:
                raw, transport, obj, mode = fetch_page(session, keyword, page_no)
            meta = page_meta(obj)
            if int(meta.get("number", -1)) != page_no:
                raise RuntimeError(f"{keyword}: requested page {page_no}, got {meta}")
            if int(meta.get("totalPages", -1)) != total_pages:
                raise RuntimeError(f"{keyword}: totalPages drift on page {page_no}")
            if int(meta.get("totalElements", -1)) != total_elements:
                raise RuntimeError(f"{keyword}: totalElements drift on page {page_no}")
            if int(meta.get("size", -1)) != page_size:
                raise RuntimeError(f"{keyword}: page size drift on page {page_no}")
            records = walk_records(obj)
            if int(meta.get("numberOfElements", -1)) != len(records):
                raise RuntimeError(
                    f"{keyword}: numberOfElements mismatch page {page_no}: "
                    f"{meta.get('numberOfElements')} != {len(records)}"
                )
            if page_no < total_pages - 1 and len(records) != page_size:
                raise RuntimeError(
                    f"{keyword}: short non-final page {page_no}: {len(records)} != {page_size}"
                )
            raw_path = args.raw_dir / f"k{keyword_index:02d}_p{page_no:04d}.raw"
            raw_path.write_bytes(raw)
            receipts.append({
                "page": page_no,
                "path": raw_path.as_posix(),
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "transport": transport,
            })
            modes.add(mode)
            for row in records:
                unique[row_id(row)] = row

        # Fail-closed N+1 check against the server's own page denominator.
        raw_n, transport_n, obj_n, mode_n = fetch_page(session, keyword, total_pages)
        records_n = walk_records(obj_n)
        n_plus_one_empty = len(records_n) == 0
        n_path = args.raw_dir / f"k{keyword_index:02d}_nplus1.raw"
        n_path.write_bytes(raw_n)
        if not n_plus_one_empty:
            raise RuntimeError(f"{keyword}: server-denominated N+1 page is not empty")

        if len(unique) != total_elements:
            raise RuntimeError(
                f"{keyword}: unique row denominator mismatch: {len(unique)} != {total_elements}"
            )

        rows = [row_view(unique[k], keyword) for k in sorted(unique)]
        exact_rows = [r for r in rows if r["exact_keyword_in_title"]]
        for row in exact_rows:
            key = (
                row["companyCd"],
                str(row["publishDate"]),
                row["title"],
                str(row["destFilePath"]),
            )
            combined[key] = row

        keyword_reports.append({
            "keyword": keyword,
            "status": "PASS",
            "total_pages": total_pages,
            "total_elements": total_elements,
            "page_size": page_size,
            "unique_rows": len(rows),
            "exact_title_event_count": len(exact_rows),
            "all_rows_sha256": canonical_sha(rows),
            "exact_title_rows_sha256": canonical_sha(exact_rows),
            "parse_modes": sorted(modes | {mode_n}),
            "n_plus_one_empty": n_plus_one_empty,
            "n_plus_one_transport": transport_n,
            "page_receipts": receipts,
            "exact_title_event_sample": exact_rows[:20],
        })

    combined_rows = [combined[k] for k in sorted(combined)]
    canonical_blob = (
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in combined_rows
        )
        + ("\n" if combined_rows else "")
    ).encode("utf-8")
    args.canonical.write_bytes(canonical_blob)

    report = {
        "schema": "stock-bse-termination-phrase-event-corpus-v1",
        "status": "PASS",
        "scope": "BSE first-party disclosureType=5 exact phrase-bounded market-wide event corpus",
        "product_bytes_changed": False,
        "window": {"start": START, "end": END},
        "endpoint": ENDPOINT,
        "official_type_contract": type_contract,
        "keywords": KEYWORDS,
        "per_keyword": keyword_reports,
        "combined_unique_exact_title_event_count": len(combined_rows),
        "combined_canonical_sha256": sha256_bytes(canonical_blob),
        "canonical_path": args.canonical.as_posix(),
        "combined_event_sample": combined_rows[:40],
        "adjudication": {
            "bse_disclosure_type_5_contract": "PASS",
            "bse_termination_phrase_query_pagination": "PASS",
            "bse_termination_phrase_event_corpus": "SUPPORTED",
            "bse_delisting_event_vocabulary_complete": "NOT VERIFIED",
            "bse_delisting_removal_lifecycle": "NOT VERIFIED",
            "bse_current_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_pit_availability": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "PASS is exhaustive only relative to the exact first-party endpoint, disclosureType=5, "
            "frozen date window, xxfcbj=2 page contract, and the three literal query phrases. "
            "No claim is made that these phrases enumerate every delisting/removal event or every "
            "historical BSE security. Event publication dates are not substituted for effective dates."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "keyword_denominators": {
            row["keyword"]: {
                "pages": row["total_pages"],
                "elements": row["total_elements"],
                "exact_title_events": row["exact_title_event_count"],
            }
            for row in keyword_reports
        },
        "combined_unique_exact_title_event_count": len(combined_rows),
        "combined_canonical_sha256": report["combined_canonical_sha256"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
