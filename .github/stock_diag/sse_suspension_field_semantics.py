from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SCRIPT = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def fetch(url: str, attempts: int = 3):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": PAGE, "Accept": "text/html,*/*;q=0.8"},
                timeout=(8, 30),
                allow_redirects=True,
            )
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty body")
            encoding = r.encoding or r.apparent_encoding or "utf-8"
            text = r.content.decode(encoding, errors="replace")
            return text, {
                "url": str(r.url),
                "status": int(r.status_code),
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "bytes": len(r.content),
                "attempt": attempt,
                "prior_errors": errors,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt >= attempts:
                raise
            time.sleep(1.0 * (2 ** (attempt - 1)))


def snippets(text: str, needle: str, radius: int = 500):
    out = []
    for match in re.finditer(re.escape(needle), text, flags=re.I):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        item = " ".join(text[start:end].split())
        out.append(item)
    return out[:20]


def classify(snips):
    joined = "\n".join(snips)
    explicit_resumption = any(x in joined for x in ("复牌日期", "复牌日", "恢复交易日", "恢复交易日期"))
    explicit_final_suspended = any(x in joined for x in ("停牌终止日", "停牌终止日期", "停牌结束日", "停牌结束日期", "停牌截止日", "停牌截止日期"))
    generic_end = any(x in joined for x in ("结束日期", "终止日期", "截止日期"))
    if explicit_resumption and not explicit_final_suspended:
        return "RESUMPTION_DATE_SUPPORTED"
    if explicit_final_suspended and not explicit_resumption:
        return "FINAL_SUSPENDED_DATE_SUPPORTED"
    if explicit_resumption and explicit_final_suspended:
        return "AMBIGUOUS_MULTIPLE_SEMANTICS"
    if generic_end:
        return "GENERIC_END_LABEL_ONLY"
    return "NOT VERIFIED"


def main():
    page_text, page_meta = fetch(PAGE)
    script_text, script_meta = fetch(SCRIPT)
    combined = page_text + "\n" + script_text

    start_snips = snippets(combined, "startStopDate")
    end_snips = snippets(combined, "endStopDate")
    control_snips = snippets(combined, "controlType")

    report = {
        "schema": "stock-sse-suspension-field-semantics-v1",
        "sources": {"page": page_meta, "script": script_meta},
        "occurrences": {
            "startStopDate": len(re.findall("startStopDate", combined, flags=re.I)),
            "endStopDate": len(re.findall("endStopDate", combined, flags=re.I)),
            "controlType": len(re.findall("controlType", combined, flags=re.I)),
        },
        "snippets": {
            "startStopDate": start_snips,
            "endStopDate": end_snips,
            "controlType": control_snips,
        },
        "end_stop_date_semantics": classify(end_snips),
        "daily_state_boundary": "NOT VERIFIED",
        "shanghai_historical_st_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "final_gate": "FAIL",
    }

    # This diagnostic intentionally does not promote daily state. Even an explicit
    # label must be combined later with an independently verified trading calendar
    # and replay contract before daily PIT can become PASS.
    if report["occurrences"]["startStopDate"] <= 0 or report["occurrences"]["endStopDate"] <= 0:
        raise RuntimeError("official front-end no longer exposes expected date fields")

    Path("stock_sse_suspension_field_semantics.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "end_stop_date_semantics": report["end_stop_date_semantics"],
        "daily_state_boundary": report["daily_state_boundary"],
        "shanghai_historical_st_pit": report["shanghai_historical_st_pit"],
        "full_historical_st_pit": report["full_historical_st_pit"],
        "final_gate": report["final_gate"],
        "page_sha256": page_meta["sha256"],
        "script_sha256": script_meta["sha256"],
    }, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
