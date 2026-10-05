from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
START_MONTH = (2021, 10)
END_MONTH = (2026, 9)
PAGE_SIZE = 200
MAX_PAGES_PER_MONTH = 20
SSE_A_PREFIXES = ("600", "601", "603", "605", "688")


def months():
    y, m = START_MONTH
    while (y, m) <= END_MONTH:
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def month_bounds(y, m):
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    start = f"{y:04d}{m:02d}01"
    from datetime import datetime, timedelta
    nxt = datetime(ny, nm, 1)
    end = (nxt - timedelta(days=1)).strftime("%Y%m%d")
    return start, end


def get(session, params, attempts=3):
    errs = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                ENDPOINT,
                params=params,
                headers={
                    "User-Agent": UA,
                    "Referer": PAGE,
                    "Accept": "application/json,text/javascript,*/*;q=0.01",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty response")
            text = r.content.decode(r.encoding or "utf-8", errors="replace").strip()
            try:
                obj = json.loads(text)
            except Exception:
                match = re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$", text, flags=re.S)
                if not match:
                    raise ValueError("not JSON/JSONP")
                obj = json.loads(match.group(1))
            if not isinstance(obj, dict) or not isinstance(obj.get("result"), list):
                raise ValueError("unexpected SSE payload shape")
            return obj, {
                "status": r.status_code,
                "url": r.url,
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "attempt": attempt,
                "prior_errors": errs,
            }
        except Exception as exc:
            errs.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def canonical_row(row):
    if not isinstance(row, dict):
        return None
    code = str(row.get("productCode") or row.get("securityCode") or "").strip()
    name = str(row.get("productName") or row.get("securityName") or "").strip()
    start = "".join(ch for ch in str(row.get("startStopDate") or "") if ch.isdigit())[:8]
    end = "".join(ch for ch in str(row.get("endStopDate") or "") if ch.isdigit())[:8]
    control = str(row.get("controlType") or "").strip()
    stop_reason = str(row.get("stopReason") or "").strip()
    end_reason = str(row.get("endStopReason") or "").strip()
    if len(code) != 6 or len(start) != 8:
        return None
    return {
        "productCode": code,
        "productName": name,
        "startStopDate": start,
        "endStopDate": end or None,
        "controlType": control,
        "stopReason": stop_reason,
        "endStopReason": end_reason,
    }


def fingerprint(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fetch_month(session, y, m):
    start, end = month_bounds(y, m)
    all_rows = []
    page_meta = []
    seen_page_fingerprints = set()
    exhausted = False
    for page_no in range(1, MAX_PAGES_PER_MONTH + 1):
        params = {
            "isPagination": "true",
            "sqlId": "GW_PL_JYTS_TFPXX",
            "pageHelp.pageSize": str(PAGE_SIZE),
            "pageHelp.pageNo": str(page_no),
            "productCode": "",
            "keyWords": "",
            "startStopDate": start,
            "endStopDate": end,
        }
        obj, meta = get(session, params)
        rows = obj["result"]
        fp = fingerprint(rows)
        if fp in seen_page_fingerprints and rows:
            raise AssertionError(f"pagination repeated a non-empty page for {start}-{end}, page={page_no}")
        seen_page_fingerprints.add(fp)
        page_help = obj.get("pageHelp") if isinstance(obj.get("pageHelp"), dict) else {}
        page_meta.append({
            "page": page_no,
            "rows": len(rows),
            "payload_sha256": meta["sha256"],
            "fetch_attempt": meta["attempt"],
            "pageHelp": {k: page_help.get(k) for k in ("pageNo", "pageSize", "pageCount", "total") if k in page_help},
        })
        all_rows.extend(rows)
        page_count = page_help.get("pageCount")
        try:
            page_count = int(page_count) if page_count is not None else None
        except Exception:
            page_count = None
        if len(rows) < PAGE_SIZE or (page_count is not None and page_no >= page_count):
            exhausted = True
            break
    if not exhausted:
        raise AssertionError(f"month pagination did not exhaust within bound: {start}-{end}")

    canon = [canonical_row(r) for r in all_rows]
    canon = [r for r in canon if r is not None]
    start_in_window = [r for r in canon if start <= r["startStopDate"] <= end]
    if all_rows and not start_in_window:
        raise AssertionError(f"non-empty month returned no rows whose startStopDate is in range: {start}-{end}")
    return {
        "month": f"{y:04d}-{m:02d}",
        "start": start,
        "end": end,
        "raw_rows": len(all_rows),
        "canonical_rows": len(canon),
        "start_date_in_window_rows": len(start_in_window),
        "pages": page_meta,
        "records": canon,
    }


def main():
    s = requests.Session()

    # Explicit pagination differential check before the full replay.
    probe_params = {
        "isPagination": "true",
        "sqlId": "GW_PL_JYTS_TFPXX",
        "pageHelp.pageSize": "50",
        "productCode": "",
        "keyWords": "",
        "startStopDate": "20240101",
        "endStopDate": "20241231",
    }
    p1, _ = get(s, dict(probe_params, **{"pageHelp.pageNo": "1"}))
    p2, _ = get(s, dict(probe_params, **{"pageHelp.pageNo": "2"}))
    f1, f2 = fingerprint(p1["result"]), fingerprint(p2["result"])
    pagination_differential = bool(p1["result"] and p2["result"] and f1 != f2)
    if not pagination_differential:
        raise AssertionError("SSE pagination differential not proven")

    monthly = []
    canonical = []
    for y, m in months():
        item = fetch_month(s, y, m)
        canonical.extend(item.pop("records"))
        monthly.append(item)

    unique_map = {}
    for row in canonical:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique_map[key] = row
    unique = [unique_map[k] for k in sorted(unique_map)]
    sse_a = [r for r in unique if r["productCode"].startswith(SSE_A_PREFIXES)]
    st_named = [r for r in sse_a if "ST" in r["productName"].upper()]

    corpus_bytes = json.dumps(unique, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    stock_bytes = json.dumps(sse_a, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    complete_months = len(monthly)
    expected_months = sum(1 for _ in months())
    corpus_complete = complete_months == expected_months and all(x["pages"] for x in monthly)
    if not corpus_complete:
        raise AssertionError("full frozen-window monthly replay incomplete")

    report = {
        "schema": "stock-sse-suspension-corpus-replay-v1",
        "run_date_utc": date.today().isoformat(),
        "endpoint": ENDPOINT,
        "frozen_window": {"start_month": "2021-10", "end_month": "2026-09"},
        "pagination": {
            "status": "PASS",
            "differential_page_1_sha256": f1,
            "differential_page_2_sha256": f2,
            "pages_differ": pagination_differential,
            "page_size": PAGE_SIZE,
            "max_pages_per_month": MAX_PAGES_PER_MONTH,
        },
        "monthly_replay": monthly,
        "corpus": {
            "raw_canonical_rows_before_dedup": len(canonical),
            "unique_rows": len(unique),
            "duplicate_rows_removed": len(canonical) - len(unique),
            "sse_a_share_rows": len(sse_a),
            "st_named_sse_a_share_rows": len(st_named),
            "all_product_corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
            "sse_a_share_corpus_sha256": hashlib.sha256(stock_bytes).hexdigest(),
            "a_share_prefixes": SSE_A_PREFIXES,
        },
        "adjudication": {
            "official_sse_historical_suspension_event_corpus": "PASS",
            "pagination_replay": "PASS",
            "frozen_window_monthly_retrieval": "PASS",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "reason_daily_state_not_verified": "event corpus alone does not prove trading-calendar/resumption-day state semantics or complete market-participant daily state files",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }
    Path("stock_sse_suspension_corpus_replay.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "pagination_replay": "PASS",
        "months": expected_months,
        "unique_rows": len(unique),
        "sse_a_share_rows": len(sse_a),
        "st_named_sse_a_share_rows": len(st_named),
        "all_product_corpus_sha256": report["corpus"]["all_product_corpus_sha256"],
        "sse_a_share_corpus_sha256": report["corpus"]["sse_a_share_corpus_sha256"],
        "official_sse_historical_suspension_event_corpus": "PASS",
        "historical_daily_suspension_state": "NOT VERIFIED",
        "shanghai_historical_st_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
