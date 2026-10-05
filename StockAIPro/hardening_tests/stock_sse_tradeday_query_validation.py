from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

SCRIPT = "https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_tradeTip_2021.js"
ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
SQL = "GW_PL_JYTS_TFPXX_TRADEDAY"
TEST_DATES = ("20191231", "20241230", "20260930")


def get(session, url, *, params=None, attempts=4):
    errors=[]
    for attempt in range(1, attempts+1):
        try:
            r=session.get(
                url,
                params=params or {},
                headers={
                    "User-Agent": UA,
                    "Referer": PAGE,
                    "Accept": "application/json,text/javascript,text/plain,*/*",
                },
                timeout=(8,30),
                allow_redirects=True,
            )
            if r.status_code in (403,429) or r.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty response")
            return r, {"attempt":attempt,"prior_errors":errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))


def parse(text):
    s=text.strip()
    try:
        obj=json.loads(s)
    except Exception:
        m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",s,re.S)
        if not m:
            raise ValueError("not JSON/JSONP")
        obj=json.loads(m.group(1))
    if not isinstance(obj,dict):
        raise ValueError("root not object")
    return obj


def bounded(row):
    if not isinstance(row,dict):
        return row
    wanted=(
        "productCode","productName","securityCode","securityName",
        "startStopDate","endStopDate","bizDate","tradeDate",
        "controlType","stopReason","endStopReason","isTradeDay",
        "SEC_CODE","SEC_NAME_CN","TRADE_DATE",
    )
    out={k:row.get(k) for k in wanted if k in row}
    if not out:
        out={k:row.get(k) for k in sorted(row)[:20]}
    return out


def extract_codes(rows):
    codes=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        code=row.get("productCode") or row.get("securityCode") or row.get("SEC_CODE")
        if code is not None:
            s=str(code).strip()
            if s:
                codes.append(s)
    return sorted(set(codes))


def main():
    session=requests.Session()
    js,jsmeta=get(session,SCRIPT)
    js_text=js.content.decode(js.encoding or "utf-8",errors="replace")
    if SQL not in js_text or "bizDate" not in js_text:
        raise AssertionError("first-party TRADEDAY/bizDate contract missing")

    results=[]
    historical_nonempty=0
    for d in TEST_DATES:
        payload=None
        attempts=[]
        for variant,extra in (
            ("jsonCallBack",{"jsonCallBack":"jsonpCallback"}),
            ("callback",{"callback":"jsonpCallback"}),
            ("plain",{}),
        ):
            params={"sqlId":SQL,"bizDate":d}
            params.update(extra)
            try:
                r,meta=get(session,ENDPOINT,params=params,attempts=3)
                txt=r.content.decode(r.encoding or "utf-8",errors="replace")
                item={
                    "variant":variant,
                    "http_status":r.status_code,
                    "attempt":meta["attempt"],
                    "prior_errors":meta["prior_errors"],
                    "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                    "url":r.url,
                }
                try:
                    obj=parse(txt)
                    rows=obj.get("result")
                    item["top_keys"]=sorted(obj)[:30]
                    item["result_count"]=len(rows) if isinstance(rows,list) else None
                    item["sample"]=[bounded(x) for x in rows[:5]] if isinstance(rows,list) else []
                    attempts.append(item)
                    if isinstance(rows,list):
                        payload=obj
                        break
                except Exception as exc:
                    item["parse_error"]=f"{type(exc).__name__}: {exc}"
                    attempts.append(item)
            except Exception as exc:
                attempts.append({"variant":variant,"error":f"{type(exc).__name__}: {exc}"})
        rows=payload.get("result") if isinstance(payload,dict) and isinstance(payload.get("result"),list) else []
        codes=extract_codes(rows)
        if d < "20260000" and rows:
            historical_nonempty += 1
        results.append({
            "bizDate":d,
            "attempts":attempts,
            "result_count":len(rows),
            "unique_product_codes":len(codes),
            "product_code_sample":codes[:20],
            "row_sample":[bounded(x) for x in rows[:10]],
            "pageHelp":payload.get("pageHelp") if isinstance(payload,dict) else None,
        })

    live_historical_surface = historical_nonempty >= 2
    report={
        "schema":"stock-sse-tradeday-query-validation-v1",
        "official_script":SCRIPT,
        "endpoint":ENDPOINT,
        "sql_id":SQL,
        "script_sha256":hashlib.sha256(js.content).hexdigest(),
        "script_fetch_attempt":jsmeta["attempt"],
        "test_dates":results,
        "adjudication":{
            "first_party_tradeday_contract":"PASS",
            "historical_tradeday_query_surface":"SUPPORTED" if live_historical_surface else "NOT VERIFIED",
            "historical_daily_suspension_state":"NOT VERIFIED",
            "daily_state_semantics":"NOT VERIFIED",
            "reason":"live TRADEDAY rows alone do not prove their exact state semantics or interval end-date inclusion; independent semantic cross-check is still required",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_tradeday_query_validation.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "script_sha256":report["script_sha256"],
        "first_party_tradeday_contract":"PASS",
        "dates":[
            {
                "bizDate":x["bizDate"],
                "result_count":x["result_count"],
                "unique_product_codes":x["unique_product_codes"],
                "row_sample":x["row_sample"][:3],
            } for x in results
        ],
        "historical_tradeday_query_surface":report["adjudication"]["historical_tradeday_query_surface"],
        "historical_daily_suspension_state":"NOT VERIFIED",
        "final_gate":"FAIL",
    },ensure_ascii=True,sort_keys=True))


if __name__=="__main__":
    main()
