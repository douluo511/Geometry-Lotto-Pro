from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
HEADERS = {
    "Referer": "https://www.bse.cn/nq/listedcompany.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
BASE_FORM = [
    ("typejb", "T"),
    ("xxfcbj[]", "2"),
    ("xxzqdm", ""),
    ("sortfield", "xxzqdm"),
    ("sorttype", "asc"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def parse_json_or_jsonp(raw: bytes):
    text = raw.decode("utf-8-sig", errors="strict").strip()
    try:
        return json.loads(text), "JSON"
    except Exception:
        pass
    match = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not match:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(match.group(1)), "JSONP"


def fetch_page(page: int) -> tuple[bytes, dict]:
    form = [("page", str(page)), *BASE_FORM]
    attempts = []
    last_error = None
    session = requests.Session()
    for attempt in range(1, 4):
        try:
            r = session.post(
                ENDPOINT,
                data=form,
                headers=HEADERS,
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
            if not official_host(r.url):
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
                    "page": page,
                    "form": form,
                    "request_url": r.request.url,
                    "resolved_url": r.url,
                    "status": int(r.status_code),
                    "content_type": str(r.headers.get("Content-Type") or ""),
                    "bytes": len(r.content),
                    "sha256": sha256_bytes(r.content),
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
    raise RuntimeError(
        f"BSE transport failed for page {page}; last_error={last_error!r}; attempts={attempts}"
    )


def page_payload(obj) -> dict:
    if not isinstance(obj, list) or len(obj) != 1 or not isinstance(obj[0], dict):
        raise ValueError("expected one-element top-level list containing page object")
    page = obj[0]
    required = {"content", "number", "numberOfElements", "size", "totalElements", "totalPages"}
    missing = sorted(required - set(page))
    if missing:
        raise ValueError(f"page object missing fields: {missing}")
    if not isinstance(page["content"], list):
        raise ValueError("page content is not a list")
    return page


def parse_yyyymmdd(value: object, field: str, code: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError(f"{code}: {field} is not YYYYMMDD: {text!r}")
    datetime.strptime(text, "%Y%m%d")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--canonical", required=True, type=Path)
    args = parser.parse_args()

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.canonical.parent.mkdir(parents=True, exist_ok=True)

    first_raw, first_transport = fetch_page(0)
    first_obj, first_mode = parse_json_or_jsonp(first_raw)
    first_page = page_payload(first_obj)

    total_pages = int(first_page["totalPages"])
    total_elements = int(first_page["totalElements"])
    page_size = int(first_page["size"])

    if total_pages <= 0 or total_elements <= 0 or page_size <= 0:
        raise RuntimeError(
            f"invalid BSE pagination denominator: pages={total_pages}, total={total_elements}, size={page_size}"
        )
    if total_pages > 200:
        raise RuntimeError(f"implausible BSE page count: {total_pages}")

    rows: list[dict] = []
    seen_codes: set[str] = set()
    transports = []
    raw_hashes = []
    parse_modes = []

    for page_no in range(total_pages):
        if page_no == 0:
            raw, transport, obj, mode = first_raw, first_transport, first_obj, first_mode
        else:
            raw, transport = fetch_page(page_no)
            obj, mode = parse_json_or_jsonp(raw)
        page = page_payload(obj)

        number = int(page["number"])
        number_of_elements = int(page["numberOfElements"])
        size = int(page["size"])
        page_total = int(page["totalElements"])
        pages_total = int(page["totalPages"])
        content = page["content"]

        if number != page_no:
            raise RuntimeError(f"page number mismatch: requested={page_no}, returned={number}")
        if page_total != total_elements or pages_total != total_pages or size != page_size:
            raise RuntimeError(
                f"pagination denominator drift on page {page_no}: "
                f"total={page_total}/{total_elements}, pages={pages_total}/{total_pages}, size={size}/{page_size}"
            )
        if number_of_elements != len(content):
            raise RuntimeError(
                f"numberOfElements mismatch on page {page_no}: {number_of_elements} != {len(content)}"
            )
        if len(content) > page_size:
            raise RuntimeError(f"page {page_no} exceeds page size")
        if page_no < total_pages - 1 and len(content) != page_size:
            raise RuntimeError(
                f"non-final page {page_no} is short: {len(content)} != {page_size}"
            )

        raw_path = args.raw_dir / f"page_{page_no:03d}.raw"
        raw_path.write_bytes(raw)
        transports.append(transport)
        raw_hashes.append({
            "page": page_no,
            "path": raw_path.as_posix(),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
        })
        parse_modes.append(mode)

        for index, row in enumerate(content):
            if not isinstance(row, dict):
                raise RuntimeError(f"page {page_no} row {index} is not an object")
            required_row = {"xxzqdm", "xxzqjc", "xxgprq", "fxssrq"}
            missing = sorted(required_row - set(row))
            if missing:
                raise RuntimeError(f"page {page_no} row {index} missing fields: {missing}")

            code = str(row["xxzqdm"] or "").strip()
            name = str(row["xxzqjc"] or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                raise RuntimeError(f"invalid BSE security code: {code!r}")
            if not name:
                raise RuntimeError(f"{code}: empty native short name")
            if code in seen_codes:
                raise RuntimeError(f"duplicate BSE security code across pages: {code}")

            list_date = parse_yyyymmdd(row["xxgprq"], "xxgprq", code)
            issue_list_date = parse_yyyymmdd(row["fxssrq"], "fxssrq", code)
            if list_date != issue_list_date:
                raise RuntimeError(
                    f"{code}: native date fields disagree: xxgprq={list_date}, fxssrq={issue_list_date}"
                )

            seen_codes.add(code)
            rows.append({
                "code": code,
                "native_short_name": name,
                "native_listing_date_xxgprq": list_date,
                "native_listing_date_fxssrq": issue_list_date,
            })

    if len(rows) != total_elements:
        raise RuntimeError(
            f"exhaustive row count mismatch: canonical={len(rows)}, totalElements={total_elements}"
        )

    codes = [row["code"] for row in rows]
    if codes != sorted(codes):
        raise RuntimeError("BSE page traversal is not globally sorted by xxzqdm")

    canonical_rows = sorted(rows, key=lambda row: row["code"])
    canonical_bytes = (
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in canonical_rows
        )
        + "\n"
    ).encode("utf-8")
    args.canonical.write_bytes(canonical_bytes)

    report = {
        "schema": "stock-bse-current-listed-universe-pagination-v1",
        "status": "PASS",
        "scope": "BSE first-party current listed-securities endpoint exhaustive pagination only",
        "product_bytes_changed": False,
        "endpoint": ENDPOINT,
        "base_form": BASE_FORM,
        "pagination": {
            "total_pages": total_pages,
            "total_elements": total_elements,
            "page_size": page_size,
            "fetched_pages": len(transports),
            "canonical_rows": len(canonical_rows),
            "unique_codes": len(seen_codes),
        },
        "parse_modes": sorted(set(parse_modes)),
        "raw_pages": raw_hashes,
        "canonical_path": args.canonical.as_posix(),
        "canonical_sha256": sha256_bytes(canonical_bytes),
        "transport_manifest_sha256": sha256_bytes(
            (
                json.dumps(transports, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
        ),
        "adjudication": {
            "bse_machine_surface": "PASS",
            "bse_current_listed_universe_pagination": "PASS",
            "bse_current_code_and_native_listing_date_projection": "PASS",
            "bse_current_lifecycle_authority": "NOT VERIFIED",
            "bse_delisting_removal_lifecycle": "NOT VERIFIED",
            "bse_historical_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_pit_availability": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "This PASS proves exhaustive pagination of the observed first-party current-securities "
            "endpoint and a deterministic projection of native security codes plus matching native "
            "date fields. It does not prove delisted-security coverage, complete lifecycle authority, "
            "historical replay, point-in-time availability, full historical ST/PIT, Advanced Business "
            "or Final."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
