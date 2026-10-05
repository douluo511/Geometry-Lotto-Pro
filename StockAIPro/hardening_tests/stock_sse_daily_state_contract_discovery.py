from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

SCRIPT = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
KNOWN_SUSPENSION_SQL = "GW_PL_JYTS_TFPXX"
PREVIOUSLY_GUESSED_TRADEDAY_SQL = "GW_PL_JYTS_TFPXX_TRADEDAY"


def fetch(attempts=4):
    errors = []
    s = requests.Session()
    for attempt in range(1, attempts + 1):
        try:
            r = s.get(
                SCRIPT,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/",
                    "Accept": "text/javascript,application/javascript,text/plain,*/*",
                },
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty official JS")
            return r, {"attempt": attempt, "prior_errors": errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def contexts(text, needle, radius=240):
    out = []
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            break
        lo = max(0, idx - radius)
        hi = min(len(text), idx + len(needle) + radius)
        out.append(" ".join(text[lo:hi].split()))
        start = idx + len(needle)
    return out


def main():
    r, meta = fetch()
    raw = r.content
    text = raw.decode(r.encoding or "utf-8", errors="replace")

    sql_ids = sorted(set(re.findall(
        r"""sqlId\s*["']?\s*:\s*["']([^"']+)["']""",
        text,
        flags=re.I,
    )))
    if KNOWN_SUSPENSION_SQL not in sql_ids:
        raise AssertionError("known first-party suspension sqlId disappeared")

    start_declared = "startStopDate" in text
    end_declared = "endStopDate" in text
    biz_date_declared = "bizDate" in text
    guessed_tradeday_declared = PREVIOUSLY_GUESSED_TRADEDAY_SQL in text

    suspension_context = contexts(text, KNOWN_SUSPENSION_SQL)
    tradeday_context = contexts(text, PREVIOUSLY_GUESSED_TRADEDAY_SQL)
    bizdate_context = contexts(text, "bizDate")

    daily_contract_supported = bool(
        guessed_tradeday_declared
        and biz_date_declared
        and any(PREVIOUSLY_GUESSED_TRADEDAY_SQL in x and "bizDate" in x for x in tradeday_context + bizdate_context)
    )

    report = {
        "schema": "stock-sse-daily-state-contract-discovery-v1",
        "official_script": SCRIPT,
        "http_status": r.status_code,
        "fetch_attempt": meta["attempt"],
        "prior_errors": meta["prior_errors"],
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "sql_ids": sql_ids,
        "contracts": {
            "known_suspension_sql_id": KNOWN_SUSPENSION_SQL,
            "known_suspension_sql_declared": KNOWN_SUSPENSION_SQL in sql_ids,
            "startStopDate_declared": start_declared,
            "endStopDate_declared": end_declared,
            "bizDate_declared_anywhere": biz_date_declared,
            "previously_guessed_tradeday_sql_id": PREVIOUSLY_GUESSED_TRADEDAY_SQL,
            "previously_guessed_tradeday_sql_declared": guessed_tradeday_declared,
            "daily_state_query_contract": "SUPPORTED" if daily_contract_supported else "NOT VERIFIED",
        },
        "bounded_context": {
            "suspension_sql": suspension_context[:5],
            "guessed_tradeday_sql": tradeday_context[:5],
            "bizDate": bizdate_context[:5],
        },
        "adjudication": {
            "official_sse_suspension_query_contract": (
                "PASS" if start_declared and end_declared else "NOT VERIFIED"
            ),
            "guessed_tradeday_sql_contract": (
                "SUPPORTED" if guessed_tradeday_declared else "NOT VERIFIED"
            ),
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }

    Path("stock_sse_daily_state_contract_discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "payload_sha256": report["payload_sha256"],
        "sql_id_count": len(sql_ids),
        "sql_ids": sql_ids,
        "known_suspension_sql_declared": KNOWN_SUSPENSION_SQL in sql_ids,
        "startStopDate_declared": start_declared,
        "endStopDate_declared": end_declared,
        "bizDate_declared_anywhere": biz_date_declared,
        "previously_guessed_tradeday_sql_declared": guessed_tradeday_declared,
        "daily_state_query_contract": report["contracts"]["daily_state_query_contract"],
        "historical_daily_suspension_state": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
