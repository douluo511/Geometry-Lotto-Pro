from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests

ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
FROZEN_END = "20260930"
LOOKUP_END = "20261006"
TARGETS = [
    {"code":"688496","name":"*ST清越","start":"20260911"},
    {"code":"601059","name":"信达证券","start":"20260915"},
    {"code":"601198","name":"东兴证券","start":"20260915"},
    {"code":"600293","name":"三峡新材","start":"20260929"},
    {"code":"603183","name":"建研院","start":"20260930"},
]

def digits8(v):
    if v is None:
        return None
    d="".join(ch for ch in str(v) if ch.isdigit())
    return d[:8] if len(d)>=8 else None

def get(session, params, attempts=3):
    errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=session.get(
                ENDPOINT,
                params=params,
                headers={"User-Agent":UA,"Referer":PAGE,"Accept":"application/json,text/javascript,*/*;q=0.01"},
                timeout=(8,30),
                allow_redirects=True,
            )
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("empty response")
            text=r.content.decode(r.encoding or "utf-8",errors="replace").strip()
            try:
                obj=json.loads(text)
            except Exception:
                m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",text,flags=re.S)
                if not m:
                    raise ValueError("not JSON/JSONP")
                obj=json.loads(m.group(1))
            if not isinstance(obj,dict) or not isinstance(obj.get("result"),list):
                raise ValueError("unexpected payload shape")
            return obj,{
                "attempt":attempt,
                "prior_errors":errors,
                "http_status":r.status_code,
                "payload_sha256":hashlib.sha256(r.content).hexdigest(),
                "url":r.url,
            }
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts:
                raise
            time.sleep(1.0*(2**(attempt-1)))

def canonical(row):
    if not isinstance(row,dict):
        return None
    code=str(row.get("productCode") or row.get("securityCode") or "").strip()
    start=digits8(row.get("startStopDate"))
    end=digits8(row.get("endStopDate"))
    return {
        "code":code,
        "name":str(row.get("productName") or row.get("securityName") or "").strip(),
        "start":start,
        "end":end,
        "controlType":row.get("controlType"),
        "stopReason":row.get("stopReason"),
        "endStopReason":row.get("endStopReason"),
    }

def main():
    s=requests.Session()
    resolutions=[]
    contradictions=[]
    unresolved=[]
    for t in TARGETS:
        params={
            "isPagination":"true",
            "sqlId":"GW_PL_JYTS_TFPXX",
            "pageHelp.pageSize":"200",
            "pageHelp.pageNo":"1",
            "productCode":t["code"],
            "keyWords":"",
            "startStopDate":t["start"],
            "endStopDate":LOOKUP_END,
        }
        obj,meta=get(s,params)
        rows=[canonical(x) for x in obj["result"]]
        rows=[x for x in rows if x and x["code"]==t["code"] and x["start"]==t["start"]]
        exact=[]
        for row in rows:
            end=row["end"]
            if end is None:
                state="OPEN_AS_OF_RETRIEVAL_SUPPORTED"
            elif end>=FROZEN_END:
                state="ACTIVE_THROUGH_FROZEN_END_SUPPORTED"
            else:
                state="CONTRADICTED_END_BEFORE_FROZEN_END"
            exact.append({**row,"state":state})
        item={
            "target":t,
            "fetch":meta,
            "matching_rows":exact,
        }
        if not exact:
            item["adjudication"]="NOT VERIFIED"
            unresolved.append(item)
        elif any(x["state"]=="CONTRADICTED_END_BEFORE_FROZEN_END" for x in exact):
            item["adjudication"]="CONTRADICTED"
            contradictions.append(item)
        elif all(x["state"] in {"OPEN_AS_OF_RETRIEVAL_SUPPORTED","ACTIVE_THROUGH_FROZEN_END_SUPPORTED"} for x in exact):
            item["adjudication"]="SUPPORTED_ACTIVE_THROUGH_FROZEN_END"
            resolutions.append(item)
        else:
            item["adjudication"]="NOT VERIFIED"
            unresolved.append(item)

    all_supported=(len(resolutions)==len(TARGETS) and not contradictions and not unresolved)
    report={
        "schema":"stock-sse-open-interval-resolution-v1",
        "frozen_end":FROZEN_END,
        "lookup_end":LOOKUP_END,
        "targets":TARGETS,
        "resolutions":resolutions,
        "contradictions":contradictions,
        "unresolved":unresolved,
        "summary":{
            "target_count":len(TARGETS),
            "supported_count":len(resolutions),
            "contradicted_count":len(contradictions),
            "unresolved_count":len(unresolved),
        },
        "adjudication":{
            "open_intervals_active_through_frozen_end":"SUPPORTED" if all_supported else "NOT VERIFIED",
            "historical_daily_suspension_state":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_sse_open_interval_resolution.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=True,sort_keys=True))
    return 0 if all_supported else 2

if __name__=="__main__":
    raise SystemExit(main())
