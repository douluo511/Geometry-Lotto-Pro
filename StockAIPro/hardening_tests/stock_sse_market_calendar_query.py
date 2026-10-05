from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
import requests

ENDPOINT="https://query.sse.com.cn/commonSoaQuery.do"
PAGE="https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SQL="PL_SCRL_SCRLB"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
WINDOWS=(("2019-12-01","2019-12-31"),("2024-12-01","2024-12-31"),("2026-09-01","2026-09-30"))

def request_raw(params,attempts=4):
    s=requests.Session(); errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=s.get(ENDPOINT,params=params,headers={"User-Agent":UA,"Referer":PAGE,"Accept":"application/json,text/javascript,*/*"},timeout=(8,30))
            if r.status_code in (403,429) or r.status_code>=500: raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            if not r.content: raise RuntimeError("empty response")
            return r,{"attempt":attempt,"prior_errors":errors}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts: raise
            time.sleep(1.0*(2**(attempt-1)))

def parse_payload(text):
    s=text.strip()
    try:
        obj=json.loads(s); kind="json"
    except Exception:
        m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",s,re.S)
        if m:
            obj=json.loads(m.group(1)); kind="jsonp"
        else:
            m=re.match(r"^(?:var\s+)?[A-Za-z0-9_.$]+\s*=\s*(\{.*\})\s*;?\s*$",s,re.S)
            if not m: raise ValueError("response is not JSON, JSONP, or simple object assignment")
            obj=json.loads(m.group(1)); kind="assignment"
    if not isinstance(obj,dict) or not isinstance(obj.get("result"),list):
        raise ValueError("parsed root does not contain result list")
    return obj,kind

def bounded(row):
    if not isinstance(row,dict): return row
    return {k:row.get(k) for k in sorted(row)[:24]}

def query_window(begin,end):
    base={"isPagination":"true","order":"tradeBeginDate|desc,stockCode|desc","tradeBeginDate":begin,"tradeEndDate":end,"sqlId":SQL,
          "pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.cacheSize":"1","pageHelp.endPage":"1","pageHelp.pageSize":"100"}
    attempts=[]
    for variant,extra in (("jsonCallBack",{"jsonCallBack":"jsonpCallback"}),("callback",{"callback":"jsonpCallback"}),("plain",{})):
        params=dict(base); params.update(extra)
        try:
            r,meta=request_raw(params)
            text=r.content.decode(r.encoding or "utf-8",errors="replace")
            item={"variant":variant,"http_status":r.status_code,"attempt":meta["attempt"],"prior_errors":meta["prior_errors"],
                  "payload_sha256":hashlib.sha256(r.content).hexdigest(),"content_type":r.headers.get("Content-Type"),
                  "prefix":" ".join(text[:600].split()),"url":r.url}
            try:
                obj,kind=parse_payload(text)
                item["parsed_as"]=kind; item["result_count"]=len(obj["result"]); attempts.append(item)
                return obj,attempts
            except Exception as exc:
                item["parse_error"]=f"{type(exc).__name__}: {exc}"; attempts.append(item)
        except Exception as exc:
            attempts.append({"variant":variant,"request_error":f"{type(exc).__name__}: {exc}"})
    return None,attempts

def main():
    results=[]; field_union=set(); parsed_windows=0
    for begin,end in WINDOWS:
        obj,attempts=query_window(begin,end)
        rows=obj["result"] if isinstance(obj,dict) else []
        if isinstance(obj,dict): parsed_windows+=1
        for row in rows:
            if isinstance(row,dict): field_union.update(row)
        results.append({"begin":begin,"end":end,"parsed":isinstance(obj,dict),"result_count":len(rows),
                        "pageHelp":obj.get("pageHelp") if isinstance(obj,dict) else None,
                        "sample":[bounded(x) for x in rows[:5]],"attempts":attempts})
    fields=sorted(field_union)
    trading_day_flags=[f for f in fields if any(t in f.lower() for t in ("istrade","tradeflag","openflag","closed","holiday"))]
    event_fields=[f for f in fields if any(t in f.lower() for t in ("stock","ipo","meeting","event","tradebegin","tradeend"))]
    live="SUPPORTED" if parsed_windows>=2 else "NOT VERIFIED"
    report={"schema":"stock-sse-market-calendar-query-v2","sql_id":SQL,"windows":results,
            "field_union":fields,"trading_day_flag_fields":trading_day_flags,"event_like_fields":event_fields,
            "adjudication":{"market_calendar_live_query":live,
                "exchange_trading_day_calendar":"SUPPORTED" if live=="SUPPORTED" and trading_day_flags else "NOT VERIFIED",
                "market_event_calendar_surface":"SUPPORTED" if live=="SUPPORTED" and event_fields else "NOT VERIFIED",
                "historical_daily_suspension_state":"NOT VERIFIED","shanghai_historical_st_pit":"NOT VERIFIED",
                "full_historical_st_pit":"NOT VERIFIED","advanced_business":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL"}}
    Path("stock_sse_market_calendar_query.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"parsed_windows":parsed_windows,
        "windows":[{"begin":x["begin"],"end":x["end"],"parsed":x["parsed"],"result_count":x["result_count"],"sample":x["sample"][:2],
                    "attempt_prefixes":[{"variant":a.get("variant"),"parsed_as":a.get("parsed_as"),"prefix":a.get("prefix"),"parse_error":a.get("parse_error"),"request_error":a.get("request_error")} for a in x["attempts"]]} for x in results],
        "field_union":fields,"trading_day_flag_fields":trading_day_flags,"event_like_fields":event_fields,
        "market_calendar_live_query":live,"exchange_trading_day_calendar":report["adjudication"]["exchange_trading_day_calendar"],
        "market_event_calendar_surface":report["adjudication"]["market_event_calendar_surface"],
        "historical_daily_suspension_state":"NOT VERIFIED","final_gate":"FAIL"},ensure_ascii=True,sort_keys=True))

if __name__=="__main__": main()
