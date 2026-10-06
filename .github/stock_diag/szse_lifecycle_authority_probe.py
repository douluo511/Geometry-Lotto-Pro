from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.szse.cn/api/report/ShowReport/data"
HEADERS = {
    "Referer": "https://www.szse.cn/market/product/stock/list/index.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
TARGETS = {
    "current": {
        "catalogid": "1110",
        "tabkey": "tab1",
        "code_field": "agdm",
        "list_field": "agssrq",
        "delist_field": None,
        "source_state": "currently_listed",
        "random": "0.1618033988749895",
    },
    "terminated": {
        "catalogid": "1793_ssgs",
        "tabkey": "tab2",
        "code_field": "zqdm",
        "list_field": "ssrq",
        "delist_field": "zzrq",
        "source_state": "terminated_listing",
        "random": "0.1414213562373095",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm_code(value: object) -> str:
    s = str(value or "").strip()
    if not s.isdigit():
        raise ValueError(f"invalid SZSE security code {s!r}")
    s = s.zfill(6)
    if len(s) != 6:
        raise ValueError(f"invalid SZSE six-digit security code {s!r}")
    return s


def norm_date(value: object, *, allow_blank: bool) -> str | None:
    s = str(value or "").strip()
    if not s or s in {"-", "None", "nan", "NaT"}:
        if allow_blank:
            return None
        raise ValueError("required SZSE lifecycle date missing")
    s = s.replace("/", "-").replace(".", "-")
    compact = s.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8])).isoformat()
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except Exception as exc:
        raise ValueError(f"invalid SZSE lifecycle date {value!r}") from exc


def fetch_page(session: requests.Session, target: dict, page_no: int) -> tuple[bytes, dict]:
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": target["catalogid"],
        "TABKEY": target["tabkey"],
        "PAGENO": str(page_no),
        "random": target["random"],
    }
    attempts = []
    last_error = None
    for attempt in range(1, 4):
        try:
            r = session.get(
                ENDPOINT,
                params=params,
                headers=HEADERS,
                timeout=(15, 35),
                allow_redirects=True,
            )
            host = (urlparse(r.url).hostname or "").lower()
            rec = {
                "attempt": attempt,
                "status": int(r.status_code),
                "url": r.url,
                "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
            }
            attempts.append(rec)
            if host != "www.szse.cn" and not host.endswith(".szse.cn"):
                raise RuntimeError(f"non-SZSE redirect: {r.url}")
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise RuntimeError(f"retryable SZSE HTTP {r.status_code}")
            elif r.status_code != 200:
                raise RuntimeError(f"non-retryable SZSE HTTP {r.status_code}")
            else:
                return r.content, {
                    "request_url": r.request.url,
                    "resolved_url": r.url,
                    "http_status": int(r.status_code),
                    "content_type": str(r.headers.get("Content-Type") or ""),
                    "attempt_count": attempt,
                    "attempts": attempts,
                }
        except requests.RequestException as exc:
            last_error = exc
            attempts.append({"attempt": attempt, "transport_error": f"{type(exc).__name__}: {exc}"})
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    raise RuntimeError(
        f"SZSE page transport failed target={target['tabkey']} page={page_no}; "
        f"last_error={last_error!r}; attempts={attempts}"
    )


def select_tab(raw: bytes, target: dict, page_no: int) -> tuple[list[dict], dict]:
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj, list):
        raise RuntimeError("SZSE ShowReport response is not a list")
    matches = []
    for section in obj:
        if not isinstance(section, dict):
            continue
        meta = section.get("metadata")
        if not isinstance(meta, dict):
            continue
        if str(meta.get("catalogid") or "") == target["catalogid"] and str(meta.get("tabkey") or "") == target["tabkey"]:
            matches.append(section)
    if len(matches) != 1:
        raise RuntimeError(
            f"SZSE target section not unique: catalog={target['catalogid']} "
            f"tab={target['tabkey']} matches={len(matches)}"
        )
    section = matches[0]
    meta = section["metadata"]
    data = section.get("data")
    if not isinstance(data, list):
        raise RuntimeError("SZSE target data is not a list")
    try:
        observed_page = int(meta.get("pageno"))
        page_count = int(meta.get("pagecount"))
        record_count = int(meta.get("recordcount"))
        page_size = int(meta.get("pagesize"))
    except Exception as exc:
        raise RuntimeError("SZSE pagination metadata invalid") from exc
    if observed_page != page_no:
        raise RuntimeError(f"SZSE page echo mismatch requested={page_no} observed={observed_page}")
    if page_count < 1 or record_count < 1 or page_size < 1:
        raise RuntimeError(
            f"SZSE invalid denominator pageCount={page_count} recordCount={record_count} pageSize={page_size}"
        )
    expected_rows = page_size if page_no < page_count else record_count - page_size * (page_count - 1)
    if expected_rows <= 0 or len(data) != expected_rows:
        raise RuntimeError(
            f"SZSE row denominator mismatch page={page_no}/{page_count}: "
            f"expected={expected_rows} observed={len(data)} total={record_count}"
        )
    return data, {
        "catalogid": target["catalogid"],
        "tabkey": target["tabkey"],
        "pageno": observed_page,
        "pagecount": page_count,
        "recordcount": record_count,
        "pagesize": page_size,
        "rows": len(data),
        "expected_rows": expected_rows,
        "subname": str(meta.get("subname") or "").strip(),
        "cols": meta.get("cols"),
    }


def crawl_target(session: requests.Session, raw_dir: Path, name: str, target: dict) -> tuple[list[dict], dict]:
    first_raw, first_transport = fetch_page(session, target, 1)
    first_rows, first_meta = select_tab(first_raw, target, 1)
    page_count = first_meta["pagecount"]
    record_count = first_meta["recordcount"]
    page_size = first_meta["pagesize"]

    rows = []
    receipts = []
    seen_codes = set()

    for page_no in range(1, page_count + 1):
        if page_no == 1:
            raw, transport, page_rows, meta = first_raw, first_transport, first_rows, first_meta
        else:
            raw, transport = fetch_page(session, target, page_no)
            page_rows, meta = select_tab(raw, target, page_no)
        if (
            meta["pagecount"] != page_count
            or meta["recordcount"] != record_count
            or meta["pagesize"] != page_size
        ):
            raise RuntimeError(
                f"SZSE denominator drift {name} page={page_no}: "
                f"pageCount {meta['pagecount']}!={page_count}, "
                f"recordCount {meta['recordcount']}!={record_count}, "
                f"pageSize {meta['pagesize']}!={page_size}"
            )
        raw_path = raw_dir / f"szse_{name}_page_{page_no:04d}.json"
        raw_path.write_bytes(raw)
        receipts.append({
            "page": page_no,
            "rows": len(page_rows),
            "raw_path": raw_path.as_posix(),
            "raw_sha256": sha256_bytes(raw),
            "transport": transport,
            "meta": meta,
        })
        for item in page_rows:
            if not isinstance(item, dict):
                raise RuntimeError(f"SZSE {name} page {page_no} contains non-object row")
            code = norm_code(item.get(target["code_field"]))
            if code in seen_codes:
                raise RuntimeError(f"SZSE {name} duplicate code across pages: {code}")
            seen_codes.add(code)
            listed = norm_date(item.get(target["list_field"]), allow_blank=False)
            delisted = (
                norm_date(item.get(target["delist_field"]), allow_blank=False)
                if target["delist_field"]
                else None
            )
            if delisted is not None and delisted <= listed:
                raise RuntimeError(f"SZSE {code} delisting date is not after listing date")
            rows.append({
                "market": "SZSE",
                "code": code,
                "listing_date": listed,
                "delisting_date": delisted,
                "source_state": target["source_state"],
            })
        if page_no < page_count:
            time.sleep(0.08)

    if len(rows) != record_count or len(seen_codes) != record_count:
        raise RuntimeError(
            f"SZSE {name} exhaustive denominator failed: rows={len(rows)} "
            f"unique={len(seen_codes)} server={record_count}"
        )
    return rows, {
        "catalogid": target["catalogid"],
        "tabkey": target["tabkey"],
        "page_count": page_count,
        "page_size": page_size,
        "server_record_count": record_count,
        "observed_row_count": len(rows),
        "unique_code_count": len(seen_codes),
        "pagination_complete": True,
        "first_page_subname": first_meta.get("subname"),
        "page_receipts": receipts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    current, current_meta = crawl_target(session, args.raw_dir, "current", TARGETS["current"])
    terminated, terminated_meta = crawl_target(session, args.raw_dir, "terminated", TARGETS["terminated"])

    lifecycle: dict[str, dict] = {}
    conflicts = []
    for row in current + terminated:
        code = row["code"]
        previous = lifecycle.get(code)
        if previous is None:
            lifecycle[code] = row
        elif previous != row:
            conflicts.append({"code": code, "first": previous, "second": row})
    if conflicts:
        raise RuntimeError(f"conflicting SZSE lifecycle rows: {conflicts[:5]}")

    ordered = [lifecycle[k] for k in sorted(lifecycle)]
    payload = "".join(
        f"{r['code']}|{r['listing_date']}|{r['delisting_date'] or ''}\n"
        for r in ordered
    ).encode("utf-8")
    projection_path = args.raw_dir / "szse_lifecycle_projection.txt"
    projection_path.write_bytes(payload)

    source_identity_pass = (
        current_meta["pagination_complete"] is True
        and terminated_meta["pagination_complete"] is True
        and current_meta["observed_row_count"] == current_meta["server_record_count"]
        and terminated_meta["observed_row_count"] == terminated_meta["server_record_count"]
        and len(ordered) == len(current) + len(terminated)
    )

    evidence = {
        "schema": "stock-szse-native-lifecycle-authority-diagnostic-v2",
        "status": "PASS" if source_identity_pass else "NOT VERIFIED",
        "product_bytes_changed": False,
        "scope": "SZSE native lifecycle authority diagnostic only; not full three-market PIT completeness",
        "authority": {
            "provider": "Shenzhen Stock Exchange",
            "endpoint": ENDPOINT,
            "current_a_share": current_meta,
            "terminated_listings": terminated_meta,
            "native_raw_bytes_preserved": True,
        },
        "lifecycle": {
            "current_count": len(current),
            "terminated_count": len(terminated),
            "union_unique_security_count": len(ordered),
            "conflict_count": len(conflicts),
            "projection_path": projection_path.as_posix(),
            "projection_sha256": sha256_bytes(payload),
            "normalization": "server-denominated ShowReport JSON current A-share union terminated-listing projection",
        },
        "adjudication": {
            "szse_source_identity": "PASS" if source_identity_pass else "NOT VERIFIED",
            "szse_native_raw_binding": "PASS" if source_identity_pass else "NOT VERIFIED",
            "szse_lifecycle_projection": "SUPPORTED" if source_identity_pass else "NOT VERIFIED",
            "szse_historical_pit_availability": "NOT VERIFIED",
            "bse_native_lifecycle_authority": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "PASS proves exhaustive current first-party SZSE ShowReport JSON pagination for the current A-share "
            "and terminated-listing tables, with stable server denominators, exact terminal-page row counts, "
            "cross-page code uniqueness, preserved raw bytes and deterministic lifecycle projection. It does not "
            "prove historical point-in-time availability of those fields, does not establish BSE authority, "
            "and cannot promote full historical ST/PIT or Advanced Business."
        ),
    }
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": evidence["schema"],
        "status": evidence["status"],
        "current_count": len(current),
        "current_pages": current_meta["page_count"],
        "terminated_count": len(terminated),
        "terminated_pages": terminated_meta["page_count"],
        "union_unique_security_count": len(ordered),
        "conflict_count": len(conflicts),
        "projection_sha256": evidence["lifecycle"]["projection_sha256"],
        "adjudication": evidence["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
