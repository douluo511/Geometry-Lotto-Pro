"""First-party BSE 2024 920 new-IPO vs 2025 legacy-switch anti-falsification.

Never elevate an official 2024 code rule / single issuer's 2024 listing
announcement to exchange-wide historical SecurityType=1 or daily ST/PIT.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

CASES = {
    "new_ipo_920_rule": {
        "url": "https://www.bse.cn/important_news/200021617.html",
        "exact_title": "关于发布《北京证券交易所全国中小企业股份转让系统证券代码、证券简称编制指引》的公告",
        "required": (
            "2024年4月22日起施行",
            "2024年4月22日后启动发行工作的",
            "920号段的证券代码",
            "2024年4月22日前已在本所上市的公司继续沿用现有证券代码",
        ),
    },
    "real_2024_920_ipo": {
        "url": "https://www.bse.cn/issue_report_meeting/200024028.html",
        "exact_title": "科隆新材今日在北交所上市",
        "required": (
            "2024年12月5日",
            "陕西科隆新材料科技股份有限公司",
            "证券代码：920098",
            "在北交所上市",
        ),
    },
}
MAX_BYTES = 3_000_000

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def official(url:str,which:str)->None:
    if which not in CASES:
        raise ValueError("unknown primary first-party source")
    obj = urlparse(str(url))
    expected=urlparse(CASES[which]["url"])
    if not (obj.scheme=="https" and obj.hostname=="www.bse.cn" and
            obj.netloc=="www.bse.cn" and obj.path==expected.path and
            not obj.username and not obj.password and not obj.query and not obj.fragment):
        raise ValueError("first-party exact source identity invalid")

def parse(which:str,body:bytes)->dict:
    if which not in CASES:
        raise ValueError("unknown first-party category")
    if not isinstance(body,bytes) or not 0<len(body)<=MAX_BYTES:
        raise ValueError("missing/oversized original HTML")
    try:
        text=body.decode("utf-8-sig",errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("official first-party page not strictly UTF-8") from exc
    soup=BeautifulSoup(text,"html.parser")
    for t in soup(["script","style","noscript"]):
        t.decompose()
    compact=re.sub(r"\s+","",soup.get_text(" ",strip=True))
    expected=CASES[which]
    if expected["exact_title"] not in compact:
        raise ValueError("official primary source title missing")
    for phrase in expected["required"]:
        if phrase not in compact:
            raise ValueError("exact first-party business statement absent: "+phrase)
    return {
        "source_category":which,
        "url":expected["url"],
        "original_html_sha256":sha(body),
        "observed_statement_exact_phrases":list(expected["required"]),
        "statement_scope":"EXCHANGE_RULE_OR_ONE_ORIGINAL_ISSUER_LISTING",
        "per_issuer_original_exchange_listing":"920098" if which=="real_2024_920_ipo" else None,
        "historical_daily_SecurityType1_listing_eligibility":"NOT VERIFIED",
        "historical_stock_day_ST_or_suspended":"NOT VERIFIED",
    }

def fetch(which:str,session=None):
    official(CASES[which]["url"],which)
    sess=session or requests.Session()
    attempts=[]
    for n in range(1,4):
        rec={"n":n,"received_at_utc":datetime.now(timezone.utc).isoformat()}
        attempts.append(rec)
        try:
            response=sess.get(CASES[which]["url"],headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155.0.0.0 Safari/537.36",
                "Accept":"text/html"},timeout=(8,30),allow_redirects=True)
            raw=response.content
            rec.update({"http":response.status_code,"final_url":str(response.url),
                        "original_html_sha256":sha(raw),"bytes":len(raw),
                        "content_type":str(response.headers.get("Content-Type",""))})
            if response.status_code!=200:
                raise ValueError("original source HTTP non-200")
            official(response.url,which)
            if "html" not in rec["content_type"].lower():
                raise ValueError("original content-type not HTML")
            parsed=parse(which,raw)
            rec["status"]="PASS"
            return {"status":"PASS","attempts":attempts,**parsed},raw
        except Exception as exc:
            rec["error"]=f"{type(exc).__name__}: {exc}"
    return {"status":"NOT VERIFIED","source":CASES[which]["url"],"attempts":attempts},None

def reconcile(records:dict)->dict:
    if not isinstance(records,dict) or set(records)!=set(CASES):
        raise ValueError("not both independent official first-party sources")
    for key in CASES:
        actual=records[key]
        if (actual.get("status")!="PASS" or
            actual.get("url")!=CASES[key]["url"] or
            actual.get("observed_statement_exact_phrases")!=list(CASES[key]["required"]) or
            not re.fullmatch(r"[0-9a-f]{64}",str(actual.get("original_html_sha256") or "")) or
            actual.get("historical_stock_day_ST_or_suspended")!="NOT VERIFIED"):
            raise ValueError("source assertion/identity cannot qualify")
    return {
        "schema":"stock-bse-new-920-ipo-2024-vs-legacy-conversion-2025-source-v1",
        "official_first_party_sources":records,
        "new_920_ipo_code_rule_effective":"2024-04-22",
        "new_920_ipo_actual_2024_listing_example":{"code":"920098","listed_date":"2024-12-05"},
        "old_248_bse_equities_pilot_code_routing":"2025-05-06",
        "old_248_bse_equities_rest_code_routing":"2025-10-09",
        "adjudication":{
            "actual_bse_2024_rule_and_920098_original_listing_source":"PASS",
            "complete_2024_920_ipo_exchange_population":"NOT VERIFIED",
            "248_existing_issuer_per_code_route_asof":"NOT VERIFIED",
            "historical_full_BSE_SecurityType1_master":"NOT VERIFIED",
            "historical_SSE_SZSE_BSE_daily_ST_halt":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "full_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        }
    }

def main():
    rec={};received={}
    for category in CASES:
        result,raw=fetch(category)
        rec[category]=result
        if raw is not None:
            Path(f"stock_bse_2024_{category}.html").write_bytes(raw)
            received[category]=raw
    report=reconcile(rec)
    Path("stock_bse_2024_ipo_primary_source.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"witnesses":len(received),
          "actual_first_party_sha":{k:sha(v) for k,v in received.items()},
          "effective_rule":report["new_920_ipo_code_rule_effective"],
          "new_2024_ipo":report["new_920_ipo_actual_2024_listing_example"],
          "adjudication":report["adjudication"]},sort_keys=True))
if __name__=="__main__":
    main()
