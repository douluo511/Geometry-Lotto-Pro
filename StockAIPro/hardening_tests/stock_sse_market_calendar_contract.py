from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

SCRIPT="https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
TARGET="PL_SCRL_SCRLB"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"


def fetch(attempts=4):
    errors=[]
    s=requests.Session()
    for attempt in range(1,attempts+1):
        try:
            r=s.get(
                SCRIPT,
                headers={
                    "User-Agent":UA,
                    "Referer":"https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/",
                    "Accept":"text/javascript,application/javascript,text/plain,*/*",
                },
                timeout=(8,30),
                allow_redirects=True,
            )
            if r.status_code in (403,429) or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty official JS")
            return r,{"attempt":attempt,"prior_errors":errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))


def contexts(text,needle,radius=1000):
    out=[]
    start=0
    while True:
        i=text.find(needle,start)
        if i<0:
            break
        lo=max(0,i-radius)
        hi=min(len(text),i+len(needle)+radius)
        out.append(" ".join(text[lo:hi].split()))
        start=i+len(needle)
    return out


def main():
    r,meta=fetch()
    text=r.content.decode(r.encoding or "utf-8",errors="replace")
    ctx=contexts(text,TARGET)
    if not ctx:
        raise AssertionError(f"{TARGET} not declared in official JS")

    parameter_like=sorted(set(
        name for block in ctx
        for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:",block)
        if name not in {"http","https"}
    ))
    date_like=sorted(set(
        token for block in ctx
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:Date|Day|Month|Year)[A-Za-z0-9_]*",block,re.I)
    ))
    endpoint_like=sorted(set(
        token for block in ctx
        for token in re.findall(r"[A-Za-z0-9_./-]+\.do",block)
    ))

    report={
        "schema":"stock-sse-market-calendar-contract-discovery-v1",
        "official_script":SCRIPT,
        "payload_sha256":hashlib.sha256(r.content).hexdigest(),
        "fetch_attempt":meta["attempt"],
        "prior_errors":meta["prior_errors"],
        "target_sql_id":TARGET,
        "occurrence_count":len(ctx),
        "parameter_like_tokens":parameter_like,
        "date_like_tokens":date_like,
        "endpoint_like_tokens":endpoint_like,
        "contexts":ctx,
        "adjudication":{
            "official_calendar_sql_identifier":"SUPPORTED",
            "calendar_query_parameters":"SUPPORTED" if parameter_like else "NOT VERIFIED",
            "calendar_semantics":"NOT VERIFIED",
            "historical_daily_suspension_state":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_market_calendar_contract.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "payload_sha256":report["payload_sha256"],
        "target_sql_id":TARGET,
        "occurrence_count":len(ctx),
        "parameter_like_tokens":parameter_like,
        "date_like_tokens":date_like,
        "endpoint_like_tokens":endpoint_like,
        "contexts":ctx[:3],
        "calendar_semantics":"NOT VERIFIED",
        "historical_daily_suspension_state":"NOT VERIFIED",
        "final_gate":"FAIL",
    },ensure_ascii=True,sort_keys=True))


if __name__=="__main__":
    main()
