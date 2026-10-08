"""Two independently fetched BSE CURRENT surfaces, no historical PIT promotion.

Surface A: public current old/new 920-code mapping. Surface B: BSE securities
filter-2 POST query. The filter enum does not independently prove a complete
listed-company identity/lifecycle, even when its pages are exhausted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import requests
from stock_bse_code_alias_source import fetch_and_review

API="https://www.bse.cn/nqxxController/nqxxCnzq.do"
FORM=[("typejb","T"),("xxfcbj[]","2"),("xxzqdm",""),("sortfield","xxzqdm"),("sorttype","asc")]
HTTP={"Referer":"https://www.bse.cn/nq/listedcompany.html",
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0 Safari/537.36",
      "Accept":"application/json,text/plain,*/*"}


def sha(raw:bytes):
    return hashlib.sha256(raw).hexdigest()


def canon(obj):
    return sha(json.dumps(obj,sort_keys=True,ensure_ascii=False,
                          separators=(",",":")).encode("utf-8"))


def official(url):
    p=urlparse(str(url))
    return (p.scheme=="https" and p.netloc=="www.bse.cn" and
            p.path=="/nqxxController/nqxxCnzq.do" and
            not p.username and not p.password and not p.query and not p.fragment)


def decode(raw:bytes):
    if len(raw)>4_000_000 or not raw:
        raise ValueError("missing or oversize first-party POST data")
    text=raw.decode("utf-8-sig",errors="strict").strip()
    try:obj=json.loads(text)
    except json.JSONDecodeError:
        m=re.fullmatch(r"[a-zA-Z_$][\w.$]*\((.*)\)\s*;?",text,re.S)
        if not m:raise ValueError("not strict JSON or JSONP")
        obj=json.loads(m[1])
    if not isinstance(obj,list) or len(obj)!=1 or not isinstance(obj[0],dict):
        raise ValueError("BSE official page contract changed")
    return obj[0]


def _num(x):
    if type(x) is not int and (not isinstance(x,str) or not x.isdecimal()):
        raise ValueError("invalid server pagination quantity")
    return int(x)


def query_page(number:int,session=None):
    sess=session or requests.Session()
    ledger=[]
    for attempt in range(1,4):
        rec={"n":attempt};ledger.append(rec)
        try:
            resp=sess.post(API,headers=HTTP,timeout=(8,25),
                           data=[("page",str(number)),*FORM],allow_redirects=True)
            raw=resp.content
            rec.update({"status_code":resp.status_code,"final_url":str(resp.url),
                        "sha256":sha(raw),"bytes":len(raw)})
            if not official(str(resp.url)) or resp.status_code!=200:
                raise RuntimeError("official source redirect or non-200 POST")
            obj=decode(raw)
            rec["status"]="PASS"
            return obj,{"page":number,"attempts":ledger,"sha256":sha(raw),
                        "bytes":len(raw),"official_url":str(resp.url)},raw
        except Exception as exc:
            rec["error"]=f"{type(exc).__name__}: {exc}"
    raise ValueError(f"official BSE observed POST page={number} unavailable; {ledger}")


def fetch_pages(session=None,raw_dir=None):
    pages=[];receipts=[];observed=[];expected_count=None;expected_pages=None;expected_size=None
    n=0;seen=set()
    while True:
        page,receipt,raw=query_page(n,session=session)
        for field in ("content","number","numberOfElements","totalPages","totalElements","size"):
            if field not in page:raise ValueError("missing official BSE field "+field)
        count,number,size,total_pages,total_elements=(
            _num(page["numberOfElements"]),_num(page["number"]),_num(page["size"]),
            _num(page["totalPages"]),_num(page["totalElements"]))
        if not isinstance(page["content"],list):raise ValueError("missing query result rows")
        if number!=n or count!=len(page["content"]):
            raise ValueError("BSE query page number/result count drift")
        if total_pages<1 or total_pages>200 or size<1 or total_elements<1:
            raise ValueError("untrusted server denominator")
        if n==0:
            expected_pages=total_pages;expected_size=size;expected_count=total_elements
        if (total_pages,total_elements,size)!=(expected_pages,expected_count,expected_size):
            raise ValueError("server changes pagination denominator")
        if n<total_pages-1 and count!=size:raise ValueError("truncated nonfinal query page")
        if n==total_pages-1 and count!=total_elements-size*(total_pages-1):
            raise ValueError("truncated final query page")
        if raw_dir is not None:
            raw_dir.mkdir(parents=True,exist_ok=True)
            file=raw_dir/f"bse_post_filter2_page_{n:03d}.raw"
            file.write_bytes(raw);receipt["evidence_rel_path"]=file.as_posix()
        for i,raw_row in enumerate(page["content"]):
            if not isinstance(raw_row,dict):raise ValueError("malformed native current record")
            if not all(k in raw_row for k in ("xxzqdm","xxzqjc","xxgprq","fxssrq")):
                raise ValueError("missing BSE current query native columns")
            code=str(raw_row["xxzqdm"]).strip()
            if not re.fullmatch(r"\d{6}",code) or code in seen:
                raise ValueError("duplicate/invalid BSE filter2 code")
            seen.add(code)
            listing=str(raw_row["xxgprq"]).strip()
            another=str(raw_row["fxssrq"]).strip()
            if not re.fullmatch(r"20\d{6}",listing) or listing!=another:
                raise ValueError("BSE current query native dates disagree")
            # Validate Gregorian date, never infer BSE original listing from it.
            from datetime import date
            try:date(int(listing[:4]),int(listing[4:6]),int(listing[6:]))
            except ValueError as e:raise ValueError("invalid native query listing date") from e
            observed.append({"code":code,"native_name":str(raw_row["xxzqjc"] or "").strip(),
                             "native_date_not_asof_BSE_effective":listing})
        pages.append(n);receipts.append(receipt)
        n+=1
        if n==expected_pages:break
    if len(observed)!=expected_count:
        raise ValueError("not all BSE server-specified rows received")
    codes=[x["code"] for x in observed]
    if codes!=sorted(codes):raise ValueError("BSE server requested ordering not upheld")
    return {"rows":observed,"server_reported_total":expected_count,"pages":len(pages),
            "query_form":FORM,"evidence":receipts}


def join(alias:dict,query:dict):
    if (alias.get("schema")!="stock-bse-current-code-alias-diagnostic-v1" or
        alias.get("actual_http_receipt")!="PASS" or
        alias.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("no official current alias surface PASS")
    a=alias.get("observed",{})
    maps=a.get("rows")
    if not isinstance(maps,list) or not maps or len(maps)!=a.get("rows_count"):
        raise ValueError("incomplete native code alias rows")
    rows=query.get("rows")
    if (not isinstance(rows,list) or not rows or
        len(rows)!=query.get("server_reported_total") or
        not isinstance(query.get("evidence"),list) or
        len(query["evidence"])!=query.get("pages")):
        raise ValueError("current BSE filter query denominator missing")
    old={};new={}
    for record in maps:
        if record["old_code"] in old or record["new_code"] in new:
            raise ValueError("alias collisions")
        old[record["old_code"]]=record
        new[record["new_code"]]=record
    codes=set()
    used_aliases=set()
    joined=[]
    for record in rows:
        code=record["code"]
        if code in codes:raise ValueError("duplicate issuer in current filter")
        codes.add(code)
        if code in old and code in new and old[code]!=new[code]:
            raise ValueError("old/new historical alias collision")
        source=old.get(code) or new.get(code)
        if source:
            identity=(source["old_code"],source["new_code"])
            if identity in used_aliases:
                raise ValueError("one mapped issuer appears in both old/new current query codes")
            used_aliases.add(identity)
        joined.append({"query_code":code,
                       "current_alias_link":("OLD_CODE" if code in old else
                                             "NEW_920_CODE" if code in new else
                                             "NO_MAPPING_IN_248_ROW_TABLE"),
                       "mapped_old_code":source["old_code"] if source else None,
                       "mapped_new_code":source["new_code"] if source else None,
                       "bse_membership_on_any_prior_date":"NOT VERIFIED",
                       "historical_920_code_valid_from":"NOT VERIFIED",
                       "historical_native_stock_type":"NOT VERIFIED"})
    linked={x["mapped_old_code"] for x in joined if x["mapped_old_code"]}
    unlinked=sorted([{"old_code":x["old_code"],"new_code":x["new_code"],
                      "source_earlier_than_BSE_open":x["pre_BSE_market_open"],
                      "historical_membership":"NOT VERIFIED"}
                     for x in maps if x["old_code"] not in linked],key=lambda x:x["old_code"])
    return {
        "schema":"stock-bse-two-independent-current-surfaces-v1",
        "alias_source_raw_sha256":alias["raw_sha256"],
        "alias_total":len(maps),
        "alias_pre_BSE_display_dates":sum(bool(x["pre_BSE_market_open"]) for x in maps),
        "filter2_query_total":len(rows),
        "query_pages":query["pages"],
        "query_raw_sha256":canon(query["evidence"]),
        "query_candidate_rows_sha256":canon(rows),
        "linked_current_query_rows":sum(x["mapped_old_code"] is not None for x in joined),
        "unlinked_alias_rows":len(unlinked),
        "query_rows_without_mapping":sum(x["mapped_old_code"] is None for x in joined),
        "joined":joined,"unlinked_alias_review":unlinked,
        "adjudication":{
            "two_current_first_party_sources_integrity":"PASS",
            "historic_complete_BSE_issuer_membership":"NOT VERIFIED",
            "historical_920_alias_code_effective_date":"NOT VERIFIED",
            "BSE_filter2_query_complete_listed_company_semantics":"NOT VERIFIED",
            "BSE_native_SecurityType1_source":"NOT VERIFIED",
            "SSE_SZSE_BSE_historical_daily_ST_suspension":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--out",type=Path,default=Path("stock_bse_two_current_surface_witness.json"))
    a.add_argument("--raw-dir",type=Path,default=Path("stock_bse_filter2_raw"))
    args=a.parse_args()
    alias,raw=fetch_and_review()
    if alias.get("actual_http_receipt")!="PASS" or raw is None:
        raise ValueError("official BSE current alias source failed; fail closed")
    Path("stock_bse_alias_original_source.html").write_bytes(raw)
    query=fetch_pages(raw_dir=args.raw_dir)
    result=join(alias,query)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("alias_total","alias_pre_BSE_display_dates","filter2_query_total",
                                           "query_pages","linked_current_query_rows","unlinked_alias_rows",
                                           "query_rows_without_mapping","unlinked_alias_review","adjudication")},sort_keys=True))
if __name__=="__main__":
    main()
