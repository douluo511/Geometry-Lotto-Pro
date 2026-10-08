"""Native first-party SZSE listing claim evidence; never a full lifecycle or PIT.

A dated issuer announcement and later exchange statistical table can corroborate
one listing date. Filename dates and a later monthly report do not themselves
establish point-in-time *publication availability* or realized trading state.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import fitz
import requests

PDF_URL = "https://disc.static.szse.cn/disc/disk03/finalpage/2026-06-25/74fa4668-42d9-49f1-9848-e301446b16e6.PDF"
MONTH_URL = "https://docs.static.szse.cn/www/market/periodical/month/W020260706503108829761.html"
CODE = "001399"
DATE = "2026-06-26"
MAX_PDF = 20_000_000
MAX_HTML = 1_000_000


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def official(url:str,kind:str):
    p=urlparse(url)
    host="disc.static.szse.cn" if kind=="PDF" else "docs.static.szse.cn"
    if (p.scheme!="https" or p.hostname!=host or p.netloc!=host or
        p.query or p.fragment or p.username or p.password):
        raise ValueError("untrusted SZSE source URL")
    if kind=="PDF" and not re.fullmatch(r"/disc/disk03/finalpage/2026-06-25/[0-9a-f-]{36}\\.PDF",p.path):
        raise ValueError("unqualified issuer listing PDF URL")
    if kind=="HTML" and not re.fullmatch(r"/www/market/periodical/month/W[0-9]+\\.html",p.path):
        raise ValueError("unqualified official SZSE statistical URL")


def fetch(url:str,kind:str,session=None):
    official(url,kind)
    getter=(session or requests.Session()).get
    headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) Stock-PIT-official-research/1.0",
             "Accept":"application/pdf" if kind=="PDF" else "text/html"}
    record={"url":url,"source_type":kind,"fetched_at":datetime.now(timezone.utc).isoformat(),
            "attempts":[],"status":"NOT VERIFIED"}
    for i in range(1,4):
        attempt={"n":i}
        record["attempts"].append(attempt)
        try:
            response=getter(url,headers=headers,timeout=(8,30),allow_redirects=True)
            resolved=str(response.url)
            official(resolved,kind)
            raw=response.content
            attempt.update({"http_status":response.status_code,"sha256":digest(raw),
                            "bytes":len(raw),"resolved_url":resolved,
                            "content_type":str(response.headers.get("Content-Type",""))})
            if response.status_code!=200:raise RuntimeError("non-200 first-party response")
            cap=MAX_PDF if kind=="PDF" else MAX_HTML
            if not raw or len(raw)>cap:raise RuntimeError("empty/oversized official bytes")
            ctype=attempt["content_type"].lower()
            if kind=="PDF":
                if not raw.startswith(b"%PDF-") or "pdf" not in ctype:
                    raise RuntimeError("invalid PDF magic/content type")
            elif ("html" not in ctype):
                raise RuntimeError("invalid HTML content type")
            record["status"]="PASS";attempt["status"]="PASS"
            return record,raw
        except Exception as e:
            attempt["error"]=f"{type(e).__name__}: {e}"
    return record,None


def normalize(value:str):
    return re.sub(r"\\s+","",value)


def parse_issuer(raw:bytes):
    if not raw or not raw.startswith(b"%PDF-"):raise ValueError("not a PDF")
    doc=fitz.open(stream=raw,filetype="pdf")
    if len(doc)<13:raise ValueError("incomplete official listing announcement")
    # Explicit page scopes, not arbitrary global 90-page keyword co-occurrence.
    cover=normalize(doc[0].get_text())
    heading=normalize(doc[1].get_text())
    notice=normalize(doc[12].get_text())
    if ("001399" not in cover or "惠科股份有限公司" not in cover or
        "首次公开发行股票" not in cover or "主板上市" not in cover):
        raise ValueError("issuer/code/stock-share-class not grounded on first page")
    if "2026年6月26日" not in heading or "深圳证券交易所" not in heading:
        raise ValueError("issuer pre-listing day not proved")
    if not ("001399" in notice and "人民币普通股" in notice and
            "深证上" in notice and "2026" in notice and "873" in notice and
            "2026年6月26日" in notice):
        raise ValueError("native exchange notification cross-reference missing")
    return {"code":CODE,"listing_date_in_issuer_announcement":DATE,
            "issuer":"惠科股份有限公司","security_kind":"RMB_ORDINARY_STOCK_MAIN_BOARD_ISSUER_DISCLOSURE",
            "pdf_pages":len(doc),"source_page_indices":[0,1,12],
            "cover_page_sha256":digest(cover.encode()),
            "first_day_page_sha256":digest(heading.encode()),
            "exchange_notification_page_sha256":digest(notice.encode())}


def parse_month(raw:bytes):
    if not raw:raise ValueError("missing official monthly HTML")
    try:text=raw.decode("utf-8",errors="strict")
    except UnicodeDecodeError:raise ValueError("not strict UTF8 SZSE monthly HTML")
    soup=BeautifulSoup(text,"html.parser")
    title=normalize(soup.get_text(" ",strip=True))
    if "新上市证券" not in title or "2026.06" not in title:
        raise ValueError("wrong SZSE market report period/category")
    rows=[]
    for tr in soup.find_all("tr"):
        cells=[normalize(x.get_text(" ",strip=True)) for x in tr.find_all(["td","th"],recursive=False)]
        if cells and cells[0]==CODE:
            if len(cells)<6:raise ValueError("malformed official listing row")
            d=cells[5].replace("/","-")
            if date.fromisoformat(d).isoformat()!=DATE:
                raise ValueError("listing date differs from dated issuer announcement")
            rows.append({"code":CODE,"name":cells[1],"listing_date":d,
                         "row_columns":len(cells),"row_sha256":digest("|".join(cells).encode())})
    if len(rows)!=1:raise ValueError("missing/duplicate issuer row in monthly report")
    return rows[0]


def qualify(pdf_data:bytes,month_data:bytes,receipts:dict,candidates:dict):
    issuer=parse_issuer(pdf_data)
    monthly=parse_month(month_data)
    pairs=candidates.get("pairs")
    if (candidates.get("schema")!="stock-szse-dated-ashare-claims-join-v1"
            or candidates.get("source_frozen_denominator")!=1849
            or candidates.get("total_equity_notice_pairs")!=967
            or candidates.get("a_share_candidate_pairs")!=958
            or candidates.get("b_share_exclusions")!=9 or not isinstance(pairs,list)
            or len(pairs)!=967):
        raise ValueError("nonqualified candidate lineage")
    matches=[x for x in pairs if x.get("equity_code_candidate")==CODE and
             x.get("candidate_asset_class")=="A_SHARE_CANDIDATE"]
    if not matches:raise ValueError("001399 not among source-bound actual stock candidates")
    if any(x.get("qualified_daily_st_pit")!="NOT VERIFIED" for x in matches):
        raise ValueError("source candidate falsely upgraded to PIT")
    if not all(receipts[x]["status"]=="PASS" for x in ("PDF","HTML")):
        raise ValueError("source download not verified")
    return {
        "schema":"stock-szse-single-issuer-listing-source-v1",
        "issuer_claim":issuer,"later_monthly_corroboration":monthly,
        "sources":receipts,"candidate_notice_pairs":len(matches),
        "candidate_notice_url_sha256":digest("\\n".join(sorted(x["official_url"] for x in matches)).encode()),
        "scope":"ONE_SCHOLARLY_SOURCE_CHECK_NOT_FULL_UNIVERSE",
        "adjudication":{
            "first_party_dated_stock_listing_claim":"PASS",
            "cross_document_listing_date":"PASS",
            "historical_issuer_actual_exchange_master":"NOT VERIFIED",
            "page_publication_timestamp_pre_signal":"NOT VERIFIED",
            "realized_first_trading_session":"NOT VERIFIED",
            "listed_security_universe_2018_to_2026":"NOT VERIFIED",
            "historical_day_security_st_suspension_sse_szse_bse":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED","final_gate":"FAIL",
        }
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--candidates",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=Path("szse_001399_official_listing_source.json"))
    a=parser.parse_args()
    receipt={};raw={}
    for name,url in (("PDF",PDF_URL),("HTML",MONTH_URL)):
        rr,bytes_=fetch(url,name)
        receipt[name]=rr
        if bytes_ is not None:
            Path(f"szse_001399_{name.lower()}_raw.{('pdf' if name=='PDF' else 'html')}").write_bytes(bytes_)
            raw[name]=bytes_
    if any(rec["status"]!="PASS" for rec in receipt.values()):
        raise ValueError("official first-party listing retrieval not complete")
    rep=qualify(raw["PDF"],raw["HTML"],receipt,
                json.loads(a.candidates.read_text(encoding="utf-8")))
    a.out.write_text(json.dumps(rep,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps({"issuer_code":CODE,"listing_date_claim":DATE,
                      "pdf_response_sha256":receipt["PDF"]["attempts"][-1]["sha256"],
                      "monthly_response_sha256":receipt["HTML"]["attempts"][-1]["sha256"],
                      "candidate_notice_pairs":rep["candidate_notice_pairs"],
                      "adjudication":rep["adjudication"]},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
