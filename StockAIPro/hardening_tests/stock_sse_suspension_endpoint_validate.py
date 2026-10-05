from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
REFERER = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SQL_ID = "GW_PL_JYTS_TFPXX"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)
WINDOWS = [
    ("historical_2017", "2017-01-01", "2017-12-31"),
    ("historical_2020", "2020-01-01", "2020-12-31"),
    ("recent_2025", "2025-01-01", "2025-12-31"),
    ("recent_2026_ytd", "2026-01-01", "2026-09-30"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha256(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def parse_json_or_jsonp(raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace").strip()
    if text.startswith("{"):
        value = json.loads(text)
    else:
        match = re.match(r"^[A-Za-z_$][\w$\.]*\s*\((.*)\)\s*;?\s*$", text, flags=re.S)
        if not match:
            raise ValueError("response is neither JSON nor JSONP")
        value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("top-level response is not an object")
    return value


def params(start: str, end: str) -> dict[str, str]:
    return {
        "isPagination": "true",
        "sqlId": SQL_ID,
        "pageHelp.pageSize": "200",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "productCode": "",
        "keyWords": "",
        "startStopDate": start,
        "endStopDate": end,
    }


def bounded_request(
    session: requests.Session,
    method: str,
    start: str,
    end: str,
    *,
    attempts: int = 3,
) -> tuple[dict, dict]:
    errors: list[dict] = []
    payload = params(start, end)
    headers = {
        "User-Agent": UA,
        "Referer": REFERER,
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Origin": "https://www.sse.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }
    for attempt in range(1, attempts + 1):
        try:
            kwargs = {
                "headers": headers,
                "timeout": (8, 25),
                "allow_redirects": True,
            }
            if method == "GET":
                response = session.get(ENDPOINT, params=payload, **kwargs)
            elif method == "POST":
                response = session.post(ENDPOINT, data=payload, **kwargs)
            else:
                raise ValueError(method)
            final = urlparse(response.url)
            if final.scheme != "https" or not final.hostname or not final.hostname.endswith("sse.com.cn"):
                raise RuntimeError(f"unexpected final URL: {response.url}")
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {response.status_code}")
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if not response.content:
                raise RuntimeError("empty response")
            value = parse_json_or_jsonp(response.content)
            return value, {
                "method": method,
                "attempt": attempt,
                "prior_errors": errors,
                "status_code": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("Content-Type"),
                "raw_bytes": len(response.content),
                "raw_sha256": sha256_bytes(response.content),
            }
        except Exception as exc:
            errors.append({
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            if attempt == attempts:
                raise RuntimeError(
                    f"{method} failed after finite retries: "
                    + json.dumps(errors, ensure_ascii=False)
                ) from exc
            time.sleep(1.0 * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def query_window(session: requests.Session, label: str, start: str, end: str) -> dict:
    method_errors: dict[str, str] = {}
    selected = None
    selected_meta = None
    selected_method = None
    for method in ("GET", "POST"):
        try:
            value, meta = bounded_request(session, method, start, end)
            result = value.get("result")
            if not isinstance(result, list):
                raise ValueError("response.result is not a list")
            selected = value
            selected_meta = meta
            selected_method = method
            break
        except Exception as exc:
            method_errors[method] = f"{type(exc).__name__}: {exc}"

    if selected is None or selected_meta is None or selected_method is None:
        raise RuntimeError(
            f"no callable method for {label}: "
            + json.dumps(method_errors, ensure_ascii=False)
        )

    result = selected.get("result") or []
    page_help = selected.get("pageHelp") if isinstance(selected.get("pageHelp"), dict) else {}
    key_union = sorted({str(k) for row in result[:100] if isinstance(row, dict) for k in row})
    lowered = {k.lower() for k in key_union}
    expected_any = {
        "productcode", "productname", "startstopdate", "endstopdate",
        "stoptime", "stopreason", "endstopreason", "type",
    }
    expected_field_overlap = sorted(lowered & expected_any)

    date_values = []
    for row in result:
        if not isinstance(row, dict):
            continue
        for name in ("startStopDate", "STARTSTOPDATE", "STOP_DATE", "stopDate"):
            if row.get(name):
                date_values.append(str(row[name]))
                break

    normalized_sample = []
    for row in result[:5]:
        if not isinstance(row, dict):
            continue
        normalized_sample.append({
            key: row.get(key)
            for key in (
                "productCode", "productName", "startStopDate", "endStopDate",
                "stopTime", "stopReason", "endStopReason", "type",
            )
            if key in row
        })

    return {
        "label": label,
        "start": start,
        "end": end,
        "method": selected_method,
        "method_errors_before_success": method_errors,
        "transport": selected_meta,
        "result_count_page": len(result),
        "page_total": page_help.get("total"),
        "page_count": page_help.get("pageCount"),
        "response_keys": sorted(selected.keys()),
        "result_field_keys": key_union,
        "expected_field_overlap": expected_field_overlap,
        "date_values_sample": date_values[:20],
        "normalized_sample": normalized_sample,
        "result_sha256": canonical_json_sha256(result),
        "response_sha256": canonical_json_sha256(selected),
        "_response": selected,
    }


def main() -> int:
    session = requests.Session()
    windows: dict[str, dict] = {}
    for label, start, end in WINDOWS:
        windows[label] = query_window(session, label, start, end)

    historical_candidates = [
        windows["historical_2017"],
        windows["historical_2020"],
    ]
    recent_candidates = [
        windows["recent_2025"],
        windows["recent_2026_ytd"],
    ]
    historical_nonempty = [x for x in historical_candidates if x["result_count_page"] > 0]
    recent_nonempty = [x for x in recent_candidates if x["result_count_page"] > 0]

    # Re-query the first non-empty historical window to test reproducibility of
    # immutable past records. If both historical windows are empty, fail closed.
    repeat = None
    repeat_same_hash = False
    if historical_nonempty:
        selected = historical_nonempty[0]
        repeat = query_window(
            session,
            selected["label"] + "_repeat",
            selected["start"],
            selected["end"],
        )
        repeat_same_hash = repeat["result_sha256"] == selected["result_sha256"]

    expected_schema = all(
        len(x["expected_field_overlap"]) >= 3
        for x in [*historical_nonempty, *recent_nonempty]
    ) if historical_nonempty and recent_nonempty else False

    distinct_historical_recent = False
    if historical_nonempty and recent_nonempty:
        distinct_historical_recent = (
            historical_nonempty[0]["result_sha256"]
            != recent_nonempty[0]["result_sha256"]
        )

    endpoint_verified = bool(
        historical_nonempty
        and recent_nonempty
        and expected_schema
        and repeat_same_hash
        and distinct_historical_recent
    )

    for item in windows.values():
        item.pop("_response", None)
    if repeat is not None:
        repeat.pop("_response", None)

    report = {
        "schema": "stock-sse-suspension-endpoint-validation-v1",
        "status": "PASS" if endpoint_verified else "NOT VERIFIED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authoritative_product_head": "43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
        "product_bytes_changed": False,
        "official_candidate": {
            "endpoint": ENDPOINT,
            "sql_id": SQL_ID,
            "referer": REFERER,
            "source_lineage": (
                "Official SSE page dynamic loader search_tradeTip_2021.js "
                "discovered on exact-head PR #190"
            ),
        },
        "windows": windows,
        "historical_repeat": repeat,
        "checks": {
            "historical_nonempty": bool(historical_nonempty),
            "recent_nonempty": bool(recent_nonempty),
            "expected_schema": expected_schema,
            "historical_repeat_same_result_hash": repeat_same_hash,
            "historical_recent_distinct_result_hash": distinct_historical_recent,
        },
        "adjudication": {
            "official_sse_candidate_endpoint_callable": "PASS" if endpoint_verified else "NOT VERIFIED",
            "historical_suspension_interval_source": "SUPPORTED" if endpoint_verified else "NOT VERIFIED",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_name_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
        },
        "boundary": (
            "A callable historical suspension interval endpoint does not by itself reconstruct "
            "daily point-in-time suspension state or historical ST-name state. Those remain "
            "separate frozen business gates."
        ),
        "final_gate": "FAIL",
    }

    Path("stock_sse_suspension_endpoint_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if endpoint_verified else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        failure = {
            "schema": "stock-sse-suspension-endpoint-validation-v1",
            "status": "FAIL",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "authoritative_product_head": "43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
            "product_bytes_changed": False,
            "official_candidate": {
                "endpoint": ENDPOINT,
                "sql_id": SQL_ID,
                "referer": REFERER,
            },
            "error_type": type(exc).__name__,
            "error": str(exc),
            "adjudication": {
                "official_sse_candidate_endpoint_callable": "NOT VERIFIED",
                "historical_suspension_interval_source": "NOT VERIFIED",
                "historical_daily_suspension_state": "NOT VERIFIED",
                "shanghai_historical_st_name_state": "NOT VERIFIED",
                "shanghai_historical_st_pit": "NOT VERIFIED",
                "full_historical_st_pit": "NOT VERIFIED",
            },
            "final_gate": "FAIL",
        }
        Path("stock_sse_suspension_endpoint_validation.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=True, sort_keys=True))
        raise
