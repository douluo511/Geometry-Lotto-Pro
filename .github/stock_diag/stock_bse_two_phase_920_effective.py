"""BSE official 920 code two-phase effective announcement witness.

Pinned ORIGINAL current 248 legacy/new aliases + three independent exchange
bulletins. Output is a *dated exchange instruction* for code-routing only;
not proof of historic company membership, performed trades, ST or halt status.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

ANNOUNCEMENTS={
 "pilot_selection":{
    "url":"https://www.bse.cn/important_news/200025487.html",
    "title":"关于发布北交所存量上市公司代码切换试点股票名单并实施配套业务安排的公告",
    "phrases":("颖泰生物","艾融软件","龙竹科技","佳先股份","同享科技","球冠电缆","具体时间另行通知"),
    "publication":"2025-04-11",
 },
 "pilot_activation":{
    "url":"https://www.bse.cn/important_news/200025603.html",
    "title":"关于北交所存量上市公司代码切换试点上线的通知",
    "phrases":("2025年5月6日","试点股票启用新证券代码","其他242只存量上市公司股票继续使用现有证券代码"),
    "publication":"2025-04-25",
 },
 "remaining_activation":{
    "url":"https://www.bse.cn/important_news/200026735.html",
    "title":"关于北交所存量上市公司代码切换上线的通知",
    "phrases":("2025年10月9日","为存量股票启用新证券代码","新旧代码对应关系"),
    "publication":"2025-09-12",
 }
}
PILOTS=("颖泰生物","艾融软件","龙竹科技","佳先股份","同享科技","球冠电缆")
PILOT_START=date(2025,5,6)
REST_START=date(2025,10,9)
OPEN=date(2021,11,15)
SHA_RE=re.compile(r"^[0-9a-f]{64}$")

def sha(raw):return hashlib.sha256(raw).hexdigest()
def official(url):
    p=urlparse(url)
    return (p.scheme=="https" and p.hostname in ("www.bse.cn","bse.cn")
        and not p.username and not p.password and p.port is None
        and p.path.startswith("/important_news/") and p.path.endswith(".html")
        and not p.query and not p.fragment)

def parse_announcement(key,raw):
    if key not in ANNOUNCEMENTS:raise ValueError("unknown_exchange_bulletin")
    if not isinstance(raw,bytes) or not raw or len(raw)>3_000_000:
        raise ValueError("missing_or_oversized_primary_bulletin")
    try: text=raw.decode("utf-8",errors="strict")
    except UnicodeDecodeError as exc:raise ValueError("official_primary_announcement_not_UTF8") from exc
    soup=BeautifulSoup(text,"html.parser")
    for tag in soup(["script","style","noscript"]):tag.decompose()
    compact=re.sub(r"\s+","",soup.get_text(" ",strip=True))
    spec=ANNOUNCEMENTS[key]
    if spec["title"] not in compact:
        raise ValueError("official_original_announcement_title_not_found")
    pub=date.fromisoformat(spec["publication"])
    textual_dates=(f"{pub.year}-{pub.month:02d}-{pub.day:02d}",
                   f"{pub.year}年{pub.month}月{pub.day}日")
    if not any(d in compact for d in textual_dates):
        raise ValueError("primary_announcement_publication_date_not_present")
    for phrase in spec["phrases"]:
        if re.sub(r"\s+","",phrase) not in compact:
            raise ValueError(f"missing_exchange_first_party_statement:{key}:{phrase}")
    # DO NOT infer the pilot effective day from the earlier selection notice.
    # Apr 11 says 'date to be announced'; Apr 25 specifies actual May 6.
    return {"official_url":spec["url"],"source_response_sha256":sha(raw),
        "primary_title":spec["title"],"publication_metadata_date":spec["publication"],
        "verified_explicit_bulletin_phrases":list(spec["phrases"]),
        "statement_scope":"EXCHANGE_ANNOUNCED_CODE_ROUTING_ONLY",
        "realized_daily_quote_or_trade_state":"NOT VERIFIED"}

def fetch_announcements(get=None):
    get=get or requests.Session().get
    reports={}; raws={}
    for key,spec in ANNOUNCEMENTS.items():
        attempts=[]
        for n in range(1,4):
            receipt={"attempt":n,"retrieved_at_utc":datetime.now(timezone.utc).isoformat()}
            attempts.append(receipt)
            try:
                r=get(spec["url"],headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"},
                      timeout=(8,25),allow_redirects=True)
                body=r.content
                receipt.update({"http_status":r.status_code,"resolved_url":str(r.url),
                      "bytes":len(body),"sha256":sha(body),
                      "content_type":r.headers.get("Content-Type","")})
                if r.status_code!=200 or not official(str(r.url)):
                    raise ValueError("official_exchange_bulletin_non200_or_redirect")
                parsed=parse_announcement(key,body)
                receipt["status"]="PASS"
                reports[key]={"status":"PASS","attempts":attempts,**parsed}
                raws[key]=body
                break
            except Exception as exc:
                receipt["error"]=f"{type(exc).__name__}:{exc}"
        if key not in reports:
            reports[key]={"status":"NOT VERIFIED","attempts":attempts,
              "official_url":spec["url"]}
    return reports,raws

def build(alias_report,bulletins):
    if (alias_report.get("schema")!="stock-bse-current-code-alias-diagnostic-v1"
        or alias_report.get("actual_http_receipt")!="PASS"
        or alias_report.get("source")!="https://www.bse.cn/service/code_mapping.html"
        or not SHA_RE.fullmatch(str(alias_report.get("raw_sha256") or ""))
        or alias_report.get("observed",{}).get("rows_count")!=248
        or alias_report.get("observed",{}).get("pre_BSE_original_listing_count")!=68):
        raise ValueError("original_source_native_248_aliases_not_verified")
    if not isinstance(bulletins,dict) or set(bulletins)!=set(ANNOUNCEMENTS):
        raise ValueError("incomplete_primary_exchange_announcement_set")
    for key,notice in bulletins.items():
        if (notice.get("status")!="PASS"
            or notice.get("official_url")!=ANNOUNCEMENTS[key]["url"]
            or notice.get("primary_title")!=ANNOUNCEMENTS[key]["title"]
            or notice.get("publication_metadata_date")!=ANNOUNCEMENTS[key]["publication"]
            or notice.get("verified_explicit_bulletin_phrases")!=list(ANNOUNCEMENTS[key]["phrases"])
            or not SHA_RE.fullmatch(str(notice.get("source_response_sha256") or ""))
            or notice.get("realized_daily_quote_or_trade_state")!="NOT VERIFIED"):
            raise ValueError("primary_bulletin_claim_or_provenance_not_validated")
    rows=alias_report["observed"].get("rows")
    if not isinstance(rows,list) or len(rows)!=248:
        raise ValueError("missing_any_current_alias")
    names={row["symbol"] for row in rows}
    if not set(PILOTS).issubset(names):
        raise ValueError("missing_official_pilot_name_in_current_alias_table")
    if len(names)!=248:
        raise ValueError("ambiguous_current_alias_issuer_names")
    if len([r for r in rows if r["symbol"] in PILOTS])!=6:
        raise ValueError("wrong_pilot_or_remaining_denominator")
    history=[]
    for row in rows:
        symbol=row["symbol"]
        start=PILOT_START if symbol in PILOTS else REST_START
        if row["BSE_asof_old_or_new_code_validity"]!="NOT VERIFIED":
            raise ValueError("current_table_forged_historical_effective_state")
        for q in ("2020-01-02","2021-11-14","2024-04-22",
                  "2025-05-05","2025-05-06","2025-10-08",
                  "2025-10-09","2026-10-08"):
            day=date.fromisoformat(q)
            code_from_notice=("NOT_A_BSE_MARKET_DAY" if day<OPEN
              else "EXCHANGE_ANNOUNCED_OLD_CODE_ROUTING" if day<start
              else "EXCHANGE_ANNOUNCED_NEW_920_CODE_ROUTING")
            history.append({
                "current_alias_name":symbol,"legacy_code":row["old_code"],
                "current_920_code":row["new_code"],
                "source_original_list_date_not_BSE_listing":row["source_listed_date_not_BSE_effective"],
                "official_notice_code_switch_effective_day":start.isoformat(),
                "historical_query_day":q,
                "official_notice_code_routing_asof":code_from_notice,
                "historical_issuer_BSE_membership":"NOT VERIFIED",
                "historical_SecurityType1_daily_master":"NOT VERIFIED",
                "realized_daily_ST_suspension_or_trade":"NOT VERIFIED",
                "qualified_business_PIT":"NOT VERIFIED",
            })
    from collections import Counter
    c=Counter(r["official_notice_code_routing_asof"] for r in history)
    return {
        "schema":"stock-bse-two-phase-248-exchange-code-effective-v1",
        "current_alias_raw_sha256":alias_report["raw_sha256"],
        "bulletin_primary_sha256":{k:v["source_response_sha256"] for k,v in bulletins.items()},
        "pilot_code_switch_names":list(PILOTS),
        "pilot_switch_effective_day_announced":PILOT_START.isoformat(),
        "remaining_switch_effective_day_announced":REST_START.isoformat(),
        "pilot_count":6,"remaining_count":242,
        "source_current_alias_count":248,
        "total_asof_code_routing_witnesses":len(history),
        "code_routing_status_counts":dict(sorted(c.items())),
        "asof_issuer_code_routing_only":history,
        "adjudication":{
            "two_phase_exchange_official_issuer_code_routing_announcements":"PASS",
            "current_248_alias_name_and_code_mapping":"PASS",
            "historical_actual_trades_at_announced_code":"NOT VERIFIED",
            "historical_native_SecurityType1_issuer_membership":"NOT VERIFIED",
            "historical_SSE_SZSE_BSE_daily_ST_suspend_PIT":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }

def main():
    p=__import__("argparse").ArgumentParser()
    p.add_argument("--current",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--evidence",type=Path,default=Path("bse_official_code_switch_announcements"))
    a=p.parse_args()
    source=json.loads(a.current.read_text(encoding="utf-8"))
    notices,raws=fetch_announcements()
    a.evidence.mkdir(parents=True,exist_ok=True)
    for key,receipt in notices.items():
        (a.evidence/(key+".json")).write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        if key in raws:(a.evidence/(key+".html")).write_bytes(raws[key])
    if any(v["status"]!="PASS" for v in notices.values()):
        raise SystemExit("first_party_exchange_bulletin_not_verified")
    result=build(source,notices)
    a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"official_bulletins":len(notices),
      "current_alias_mapping_rows":result["source_current_alias_count"],
      "pilot_effective":"2025-05-06","remaining_effective":"2025-10-09",
      "asof_witnesses":result["total_asof_code_routing_witnesses"],
      "code_status_counts":result["code_routing_status_counts"],
      "actual_trading_and_ST_PIT":"NOT VERIFIED",
      "final_gate":"FAIL"},sort_keys=True))
if __name__=="__main__":main()
