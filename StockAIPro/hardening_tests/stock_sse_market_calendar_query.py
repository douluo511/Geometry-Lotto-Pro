from __future__ import annotations
import hashlib,json,re,time
from pathlib import Path
import requests

ENDPOINT="https://query.sse.com.cn/commonSoaQuery.do"
PAGE="https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
SQL="PL_SCRL_SCRLB"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36"
WINDOWS=(("2019-12-01","2019-12-31"),("2024-12-01","2024-12-31"),("2026-09-01","2026-09-30"))

def fetch(params,attempts=4):
    s=requests.Session(); errors=[]
    for attempt in range(1,attempts+1):
        try:
            r=s.get(ENDPOINT,params=params,headers={"User-Agent":UA,"Referer":PAGE,"Accept":"application/json,text/javascript,*/*"},timeout=(8,30))
            if r.status_code in (403,429) or r.status_code>=500: raise RuntimeError(f"retryable HTTP {r.status_code}")
            r.raise_for_status()
            text=r.content.decode(r.encoding or "utf-8",errors="replace").strip()
            try: obj=json.loads(text)
            except Exception:
                m=re.match(r"^[A-Za-z0-9_.$]+\((.*)\)\s*;?\s*$",text,re.S)
                if not m: raise
                obj=json.loads(m.group(1))
            if not isinstance(obj,dict) or not isinstance(obj.get("result"),list): raise ValueError("unexpected payload")
            return obj,{"attempt":attempt,"prior_errors":errors,"sha256":hashlib.sha256(r.content).hexdigest(),"url":r.url}
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt==attempts: raise
            time.sleep(1.0*(2**(attempt-1)))

def bounded(row):
    if not isinstance(row,dict): return row
    return {k:row.get(k) for k in sorted(row)[:24]}

def main():
    results=[]
    field_union=set()
    for begin,end in WINDOWS:
        params={
            "isPagination":"true","order":"tradeBeginDate|desc,stockCode|desc",
            "tradeBeginDate":begin,"tradeEndDate":end,"sqlId":SQL,
            "pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.cacheSize":"1",
            "pageHelp.endPage":"1","pageHelp.pageSize":"100",
        }
        obj,meta=fetch(params)
        rows=obj["result"]
        for row in rows:
            if isinstance(row,dict): field_union.update(row)
        results.append({
            "begin":begin,"end":end,"result_count":len(rows),"pageHelp":obj.get("pageHelp"),
            "sample":[bounded(x) for x in rows[:5]],"payload_sha256":meta["sha256"],"attempt":meta["attempt"],
        })
    fields=sorted(field_union)
    trading_day_flags=[f for f in fields if any(t in f.lower() for t in ("istrade","tradeflag","openflag","closed","holiday"))]
    event_fields=[f for f in fields if any(t in f.lower() for t in ("stock","ipo","meeting","event","tradebegin","tradeend"))]
    report={
        "schema":"stock-sse-market-calendar-query-v1","sql_id":SQL,"windows":results,
        "field_union":fields,"trading_day_flag_fields":trading_day_flags,"event_like_fields":event_fields,
        "adjudication":{
            "market_calendar_live_query":"SUPPORTED",
            "exchange_trading_day_calendar":"SUPPORTED" if trading_day_flags else "NOT VERIFIED",
            "market_event_calendar_surface":"SUPPORTED" if event_fields else "NOT VERIFIED",
            "historical_daily_suspension_state":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED","full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED","product_bytes_changed":False,"final_gate":"FAIL",
        },
    }
    Path("stock_sse_market_calendar_query.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"windows":[{"begin":x["begin"],"end":x["end"],"result_count":x["result_count"],"sample":x["sample"][:2]} for x in results],
        "field_union":fields,"trading_day_flag_fields":trading_day_flags,"event_like_fields":event_fields,
        "exchange_trading_day_calendar":report["adjudication"]["exchange_trading_day_calendar"],
        "market_event_calendar_surface":report["adjudication"]["market_event_calendar_surface"],
        "historical_daily_suspension_state":"NOT VERIFIED","final_gate":"FAIL"},ensure_ascii=True,sort_keys=True))

if __name__=="__main__": main()
