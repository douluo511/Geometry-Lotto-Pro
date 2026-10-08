"""Two unmatched *current* BSE aliases: corroborate with actual issuer delist PDFs.

Claims are official first-party announced decisions, entry into delisting
arrangement, and issuer-stated future removal dates. They are not independent
proof of executed final exchange register change or of full day x stock PIT.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import fitz
import requests

CASES={
 "920305":{
  "old_code":"835305","company":"南京云创大数据科技股份有限公司",
  "url":"https://www.bse.cn/disclosure/2026/2026-07-29/8a64d7d9ca1641609307b4f2aa5fecaf.pdf",
  "announcement_date":"2026-07-29","decision_date":"2026-06-09",
  "delisting_period_open":"2026-07-09","delisting_period_last_session":"2026-07-29",
  "issuer_announced_delist_day":"2026-07-30",
  "required_title":"关于公司股票终止上市暨摘牌的公告"
 },
 "920680":{
  "old_code":"839680","company":"深圳市广道数字技术股份有限公司",
  "url":"https://www.bse.cn/disclosure/2025/2025-12-31/8690dbac1d5c42db98e9c7388e562129.pdf",
  "announcement_date":"2025-12-31","decision_date":"2025-11-12",
  "delisting_period_open":"2025-12-11","delisting_period_last_session":"2025-12-31",
  "issuer_announced_delist_day":"2026-01-05",
  "required_title":"关于公司股票终止上市暨摘牌的公告"
 },
}
MAX=10_000_000


def sha(b:bytes):return hashlib.sha256(b).hexdigest()
def norm(t):return re.sub(r"\s+","",t or "")

def official(url:str,case:dict):
    u=urlparse(str(url))
    if (u.scheme!="https" or u.netloc!="www.bse.cn" or
        u.username or u.password or u.query or u.fragment or
        u.path!=urlparse(case["url"]).path):
        raise ValueError("unqualified official first-party delisting PDF")


def request_source(case:dict,session=None):
    session=session or requests.Session()
    attempts=[]
    for n in range(1,4):
        entry={"attempt":n,"started_at_utc":datetime.now(timezone.utc).isoformat()}
        attempts.append(entry)
        try:
            official(case["url"],case)
            response=session.get(case["url"],allow_redirects=True,
                timeout=(10,30),
                headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155.0.0.0 Safari/537.36",
                         "Accept":"application/pdf,*/*"})
            body=response.content
            entry.update({"http":response.status_code,"final_url":response.url,
                          "raw_sha256":sha(body),"raw_bytes":len(body),
                          "content_type":str(response.headers.get("Content-Type",""))})
            official(str(response.url),case)
            if (response.status_code!=200 or not body.startswith(b"%PDF-") or
                len(body)>MAX or len(body)<1000):
                raise ValueError("invalid official PDF response bytes or status")
            entry["status"]="PASS"
            return {"status":"PASS","source_url":case["url"],"attempts":attempts,
                    "raw_sha256":sha(body),"raw_bytes":len(body)},body
        except Exception as exc:
            entry["error"]=f"{type(exc).__name__}: {exc}"
    return {"status":"NOT VERIFIED","source_url":case["url"],"attempts":attempts},None


def parse(case:dict,raw:bytes):
    if not isinstance(raw,bytes) or not raw.startswith(b"%PDF-"):
        raise ValueError("not an actual PDF")
    document=fitz.open(stream=raw,filetype="pdf")
    if not 1<=len(document)<=15:raise ValueError("implausible official notice pages")
    pages=[norm(page.get_text()) for page in document]
    head=pages[0]
    entire="".join(pages)
    code=next(key for key,item in CASES.items() if item["url"]==case["url"])
    if not all(key in head for key in (code,case["company"],case["required_title"])):
        raise ValueError("first page does not bind issuer, equity code and delisting notice title")
    def chinese(d):
        y,m,dd=[int(x) for x in d.split("-")]
        date(y,m,dd)  # Gregorian guard
        return f"{y}年{m}月{dd}日"
    # Explicit source role assertions: decision date, delisting-period start/end
    # and subsequent intended delisting date are NOT interchangeable.
    d=chinese(case["decision_date"])
    begin=chinese(case["delisting_period_open"])
    end=chinese(case["delisting_period_last_session"])
    delist=chinese(case["issuer_announced_delist_day"])
    if not re.search(rf"(?:于|在|自){re.escape(begin)}进入退市整理期",entire):
        raise ValueError("native document lacks delisting trading-window start")
    if not re.search(rf"截至{re.escape(end)}.*?退市整理期交易已满15个交易日",entire):
        raise ValueError("completed 15-session issuer statement absent")
    if not re.search(rf"股票将于{re.escape(delist)}被北京证券交易所终止上市并摘牌",entire):
        raise ValueError("exact future effective removal claim absent")
    if not re.search(rf"于{re.escape(d)}收到北京证券交易所出具",entire):
        raise ValueError("primary exchange decision received day absent")
    if not re.search(r"（[一1]）证券种类.{0,30}人民币普通股",entire):
        raise ValueError("RMB equity security class not evidenced")
    return {"issuer":case["company"],"code":code,"notice_title":case["required_title"],
            "pages":len(pages),"first_page_text_sha256":sha(head.encode()),
            "full_body_sha256":sha(entire.encode()),"exchange_decision_received_day":case["decision_date"],
            "announced_delisting_trade_open":case["delisting_period_open"],
            "issuer_reported_final_delisting_trade_day":case["delisting_period_last_session"],
            "issuer_announced_exchange_delist_date":case["issuer_announced_delist_day"],
            "source_announcement_date_from_path_not_timestamp":case["announcement_date"],
            "realized_exchange_delisting_register_verified":"NOT VERIFIED",
            "actual_day_by_day_stock_trading_verified":"NOT VERIFIED"}


def audit(two_current:dict,raw_by_code:dict,receipts:dict):
    if (two_current.get("schema")!="stock-bse-two-independent-current-surfaces-v1"
        or two_current.get("alias_total")!=248 or two_current.get("filter2_query_total")!=348
        or two_current.get("linked_current_query_rows")!=246
        or two_current.get("unlinked_alias_rows")!=2 or
        two_current.get("query_rows_without_mapping")!=102
        or two_current.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("current two-source denominator not qualified")
    gap=two_current.get("unlinked_alias_review")
    if (not isinstance(gap,list) or len(gap)!=2 or
        {(r.get("new_code"),r.get("old_code")) for r in gap}!=
            {(code,c["old_code"]) for code,c in CASES.items()}):
        raise ValueError("exact two unmatched issuer source identities drifted")
    for item in gap:
        if item.get("historical_membership")!="NOT VERIFIED":
            raise ValueError("upstream fabricated historical issuer status")
    docs=[]
    for code,case in sorted(CASES.items()):
        if (code not in raw_by_code or
            receipts.get(code,{}).get("status")!="PASS" or
            receipts[code].get("raw_sha256")!=sha(raw_by_code[code])):
            raise ValueError("official raw receipt and exact PDF SHA not bound")
        verified=parse(case,raw_by_code[code])
        docs.append({**verified,"source_url":case["url"],
                     "official_pdf_raw_sha256":sha(raw_by_code[code]),
                     "first_party_transport_status":"PASS"})
    return {"schema":"stock-bse-two-absent-current-code-delist-notice-witness-v1",
            "cross_source_alias_total":248,
            "cross_source_filter2_rows":348,
            "unlinked_alias_denominator":2,
            "first_party_original_issuer_announcements":docs,
            "notice_count":len(docs),
            "adjudication":{
                "both_current_surface_alias_gap_identity":"PASS",
                "official_issuer_pdf_stated_delist_and_decision_days":"PASS",
                "historical_BSE_actual_market_register_execution":"NOT VERIFIED",
                "historical_asof_listing_and_alias_effective":"NOT VERIFIED",
                "historical_SSE_SZSE_BSE_day_security_ST_suspension":"NOT VERIFIED",
                "production_historical_st_pit":"NOT VERIFIED",
                "advanced_business":"NOT VERIFIED",
                "final_gate":"FAIL",
            }}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--two-current",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("stock_bse_two_delist_notices.json"))
    args=p.parse_args()
    raw={}; receipts={}
    for code,case in sorted(CASES.items()):
        receipt,body=request_source(case)
        receipts[code]=receipt
        if body is not None:
            raw[code]=body
            Path(f"stock_bse_delist_{code}.pdf").write_bytes(body)
    if len(raw)!=2:
        args.out.write_text(json.dumps({"official_sources":receipts,
            "status":"NOT VERIFIED","adjudication":{"final_gate":"FAIL"}},
            ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        raise RuntimeError("missing official first-party delisting notices; never promote")
    report=audit(json.loads(args.two_current.read_text(encoding="utf-8")),raw,receipts)
    report["source_receipts"]=receipts
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"notices":report["notice_count"],
        "codes":[r["code"] for r in report["first_party_original_issuer_announcements"]],
        "issuer_announced_delist_dates":[r["issuer_announced_exchange_delist_date"]
                                        for r in report["first_party_original_issuer_announcements"]],
        "raw_digests":[r["official_pdf_raw_sha256"] for r in report["first_party_original_issuer_announcements"]],
        "adjudication":report["adjudication"]},sort_keys=True))
if __name__=="__main__":
    main()
