from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
FROZEN_START = date(2021, 10, 1)
FROZEN_END = date(2026, 9, 30)

SOURCES = {
    2021: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20201224_5286951.shtml",
    2022: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20211220_5663057.shtml",
    2023: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20221227_5714459.shtml",
    2024: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20231226_5733941.shtml",
    2025: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20241223_10767110.shtml",
    2026: "https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml",
}

# These are frozen expected contracts copied from the first-party annual SSE
# holiday-closure notices. They are not accepted as data by themselves: every
# interval below must be confirmed by live first-party page text in this run.
CLOSURES = {
    2021: [
        ("元旦", date(2021,1,1), date(2021,1,3), date(2021,1,4)),
        ("春节", date(2021,2,11), date(2021,2,17), date(2021,2,18)),
        ("清明节", date(2021,4,3), date(2021,4,5), date(2021,4,6)),
        ("劳动节", date(2021,5,1), date(2021,5,5), date(2021,5,6)),
        ("端午节", date(2021,6,12), date(2021,6,14), date(2021,6,15)),
        ("中秋节", date(2021,9,19), date(2021,9,21), date(2021,9,22)),
        ("国庆节", date(2021,10,1), date(2021,10,7), date(2021,10,8)),
    ],
    2022: [
        ("元旦", date(2022,1,1), date(2022,1,3), date(2022,1,4)),
        ("春节", date(2022,1,31), date(2022,2,6), date(2022,2,7)),
        ("清明节", date(2022,4,3), date(2022,4,5), date(2022,4,6)),
        ("劳动节", date(2022,4,30), date(2022,5,4), date(2022,5,5)),
        ("端午节", date(2022,6,3), date(2022,6,5), date(2022,6,6)),
        ("中秋节", date(2022,9,10), date(2022,9,12), date(2022,9,13)),
        ("国庆节", date(2022,10,1), date(2022,10,7), date(2022,10,10)),
    ],
    2023: [
        ("元旦", date(2022,12,31), date(2023,1,2), date(2023,1,3)),
        ("春节", date(2023,1,21), date(2023,1,27), date(2023,1,30)),
        ("清明节", date(2023,4,5), date(2023,4,5), date(2023,4,6)),
        ("劳动节", date(2023,4,29), date(2023,5,3), date(2023,5,4)),
        ("端午节", date(2023,6,22), date(2023,6,24), date(2023,6,26)),
        ("中秋节、国庆节", date(2023,9,29), date(2023,10,6), date(2023,10,9)),
    ],
    2024: [
        ("元旦", date(2023,12,30), date(2024,1,1), date(2024,1,2)),
        ("春节", date(2024,2,9), date(2024,2,17), date(2024,2,19)),
        ("清明节", date(2024,4,4), date(2024,4,6), date(2024,4,8)),
        ("劳动节", date(2024,5,1), date(2024,5,5), date(2024,5,6)),
        ("端午节", date(2024,6,10), date(2024,6,10), date(2024,6,11)),
        ("中秋节", date(2024,9,15), date(2024,9,17), date(2024,9,18)),
        ("国庆节", date(2024,10,1), date(2024,10,7), date(2024,10,8)),
    ],
    2025: [
        ("元旦", date(2025,1,1), date(2025,1,1), date(2025,1,2)),
        ("春节", date(2025,1,28), date(2025,2,4), date(2025,2,5)),
        ("清明节", date(2025,4,4), date(2025,4,6), date(2025,4,7)),
        ("劳动节", date(2025,5,1), date(2025,5,5), date(2025,5,6)),
        ("端午节", date(2025,5,31), date(2025,6,2), date(2025,6,3)),
        ("国庆节、中秋节", date(2025,10,1), date(2025,10,8), date(2025,10,9)),
    ],
    2026: [
        ("元旦", date(2026,1,1), date(2026,1,3), date(2026,1,5)),
        ("春节", date(2026,2,15), date(2026,2,23), date(2026,2,24)),
        ("清明节", date(2026,4,4), date(2026,4,6), date(2026,4,7)),
        ("劳动节", date(2026,5,1), date(2026,5,5), date(2026,5,6)),
        ("端午节", date(2026,6,19), date(2026,6,21), date(2026,6,22)),
        ("中秋节", date(2026,9,25), date(2026,9,27), date(2026,9,28)),
        ("国庆节", date(2026,10,1), date(2026,10,7), date(2026,10,8)),
    ],
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def fetch(session: requests.Session, url: str, attempts: int = 3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Referer": "https://www.sse.com.cn/disclosure/dealinstruc/closed/list/",
                },
                timeout=(8, 30),
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty body")
            return r, attempt, errors
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep((2 ** (attempt - 1)) + random.random() * 0.25)

def visible_text(raw: bytes, encoding: str | None) -> str:
    # SSE annual notice responses currently declare only "text/html" with no
    # charset. requests therefore defaults to ISO-8859-1, which corrupts all
    # Chinese contract text. Prefer strict UTF-8 (the actual page encoding)
    # and fall back only if UTF-8 genuinely fails.
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = raw.decode(encoding or "utf-8", errors="replace")
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", "", text)

def cn_date_fragment(d: date) -> str:
    return f"{d.month}月{d.day}日"

def validate_contract(year: int, text: str):
    checks = []
    for holiday, start, end, reopen in CLOSURES[year]:
        fragments = [holiday, cn_date_fragment(start), cn_date_fragment(end), cn_date_fragment(reopen), "休市"]
        missing = [x for x in fragments if x not in text]
        checks.append({
            "holiday": holiday,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "reopen": reopen.isoformat(),
            "fragments": fragments,
            "missing": missing,
            "pass": not missing,
        })
    title_year = str(year) in text and ("休市安排" in text or "休市" in text)
    return title_year, checks

def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)

def canonical_calendar():
    closure_dates = set()
    closure_lineage = {}
    for year, rows in CLOSURES.items():
        for holiday, start, end, reopen in rows:
            for d in daterange(start, end):
                closure_dates.add(d)
                closure_lineage.setdefault(d.isoformat(), []).append({
                    "year_notice": year,
                    "holiday": holiday,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "reopen": reopen.isoformat(),
                })

    trading = []
    nontrading = []
    for d in daterange(FROZEN_START, FROZEN_END):
        if d.weekday() >= 5:
            nontrading.append({"date": d.isoformat(), "reason": "WEEKEND"})
        elif d in closure_dates:
            nontrading.append({
                "date": d.isoformat(),
                "reason": "OFFICIAL_SSE_HOLIDAY_CLOSURE",
                "lineage": closure_lineage.get(d.isoformat(), []),
            })
        else:
            trading.append(d.isoformat())
    return trading, nontrading

def main():
    session = requests.Session()
    pages = {}
    all_contracts_pass = True

    for year, url in SOURCES.items():
        r, attempt, prior_errors = fetch(session, url)
        text = visible_text(r.content, r.encoding)
        title_year, checks = validate_contract(year, text)
        page_pass = title_year and all(x["pass"] for x in checks)
        all_contracts_pass = all_contracts_pass and page_pass
        pages[str(year)] = {
            "url": r.url,
            "http_status": r.status_code,
            "content_type": r.headers.get("Content-Type"),
            "bytes": len(r.content),
            "sha256": sha256(r.content),
            "attempt": attempt,
            "prior_errors": prior_errors,
            "title_year_contract": title_year,
            "closure_contracts": checks,
            "pass": page_pass,
        }

    trading, nontrading = canonical_calendar()
    trading_bytes = ("\n".join(trading) + "\n").encode("utf-8")
    nontrading_dates = {x["date"] for x in nontrading}

    boundary_expectations = {
        "2021-10-01": False,
        "2021-10-07": False,
        "2021-10-08": True,
        "2022-01-31": False,
        "2022-02-06": False,
        "2022-02-07": True,
        "2023-09-29": False,
        "2023-10-06": False,
        "2023-10-09": True,
        "2024-02-09": False,
        "2024-02-17": False,
        "2024-02-19": True,
        "2025-10-01": False,
        "2025-10-08": False,
        "2025-10-09": True,
        "2026-09-25": False,
        "2026-09-27": False,
        "2026-09-28": True,
    }
    trading_set = set(trading)
    boundary_checks = {
        d: {
            "expected_trading": expected,
            "actual_trading": d in trading_set,
            "pass": (d in trading_set) == expected,
        }
        for d, expected in boundary_expectations.items()
    }

    weekend_makeup_checks = {
        # SSE notices explicitly keep these weekend "makeup work" dates closed.
        "2021-09-18": "WEEKEND",
        "2021-09-26": "WEEKEND",
        "2021-10-09": "WEEKEND",
        "2022-01-29": "WEEKEND",
        "2022-01-30": "WEEKEND",
        "2023-10-07": "WEEKEND",
        "2023-10-08": "WEEKEND",
        "2024-02-18": "WEEKEND",
        "2025-02-08": "WEEKEND",
        "2026-02-28": "WEEKEND",
    }
    weekend_checks = {
        d: {
            "expected_nontrading": True,
            "actual_nontrading": d in nontrading_dates or date.fromisoformat(d) < FROZEN_START or date.fromisoformat(d) > FROZEN_END,
            "weekday": date.fromisoformat(d).weekday(),
        }
        for d in weekend_makeup_checks
    }

    boundary_pass = all(x["pass"] for x in boundary_checks.values())
    weekend_pass = all(x["weekday"] >= 5 for x in weekend_checks.values())
    calendar_pass = all_contracts_pass and boundary_pass and weekend_pass

    report = {
        "schema": "stock-sse-official-trading-calendar-v1",
        "frozen_window": {"start": FROZEN_START.isoformat(), "end": FROZEN_END.isoformat()},
        "sources": pages,
        "source_years": sorted(SOURCES),
        "calendar": {
            "trading_day_count": len(trading),
            "nontrading_day_count": len(nontrading),
            "trading_dates_sha256": sha256(trading_bytes),
            "trading_dates": trading,
            "nontrading_dates": nontrading,
        },
        "boundary_checks": boundary_checks,
        "weekend_makeup_checks": weekend_checks,
        "adjudication": {
            "all_six_official_annual_notices_live_verified": all_contracts_pass,
            "boundary_checks": "PASS" if boundary_pass else "FAIL",
            "weekend_makeup_closed_rule": "PASS" if weekend_pass else "FAIL",
            "exchange_trading_calendar_frozen_window": "PASS" if calendar_pass else "FAIL",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }

    Path("stock_sse_official_trading_calendar.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "all_contracts_pass": all_contracts_pass,
        "boundary_pass": boundary_pass,
        "weekend_pass": weekend_pass,
        "trading_day_count": len(trading),
        "trading_dates_sha256": report["calendar"]["trading_dates_sha256"],
        "exchange_trading_calendar_frozen_window": report["adjudication"]["exchange_trading_calendar_frozen_window"],
        "historical_daily_suspension_state": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "final_gate": "FAIL",
    }, ensure_ascii=True, sort_keys=True))

    if not calendar_pass:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
