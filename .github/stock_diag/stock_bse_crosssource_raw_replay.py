"""Independently reparse pinned 18 BSE native response pages and two issuer PDFs.

Never trust self-consistent downstream 248/348/2 JSON as sufficient provenance.
The original GitHub Actions ZIP digests are checked independently by the caller.
"""
from __future__ import annotations
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

def sha(b): return hashlib.sha256(b).hexdigest()
def canon(o): return sha(json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode())

def load_module(path,name):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def replay_current(original_dir:Path, report:dict, pinned_dir:Path, expected_alias_sha:str)->dict:
    native=load_module(pinned_dir/"stock_bse_current_two_source_check.py","bse_pinned_360_native")
    alias_source=load_module(pinned_dir/"stock_bse_code_alias_source.py","bse_pinned_360_alias")
    alias_raw=(original_dir/"stock_bse_alias_original_source.html").read_bytes()
    if (sha(alias_raw)!=report.get("alias_source_raw_sha256")
        or sha(alias_raw)!=expected_alias_sha):
        raise ValueError("original_alias_HTML_not_hash_bound_to_both_sources")
    parsed_alias=alias_source.parse(alias_raw)
    alias=parsed_alias.get("rows")
    if not isinstance(alias,list) or len(alias)!=248 or parsed_alias.get("pre_BSE_original_listing_count")!=68:
        raise ValueError("original_248_aliases_not_independently_reparsed")
    old={x["old_code"]:x for x in alias}
    new={x["new_code"]:x for x in alias}
    if len(old)!=248 or len(new)!=248:
        raise ValueError("current_alias_source_code_collision")
    root=original_dir/"stock_bse_filter2_raw"
    if not root.is_dir():
        raise ValueError("independent_native_BSE_query_raw_directory_missing")
    pages=sorted(root.glob("bse_post_filter2_page_*.raw"))
    if len(pages)!=18 or {x.name for x in pages}!={f"bse_post_filter2_page_{i:03d}.raw" for i in range(18)}:
        raise ValueError("missing_or_duplicate_first_party_native_query_page")
    original=[]
    sizes=set()
    for i,p in enumerate(pages):
        raw=p.read_bytes()
        native_page=native.decode(raw)
        count=native._num(native_page.get("numberOfElements"))
        total=native._num(native_page.get("totalElements"))
        page=native._num(native_page.get("number"))
        page_count=native._num(native_page.get("totalPages"))
        size=native._num(native_page.get("size"))
        rows=native_page.get("content")
        if (total!=348 or page_count!=18 or page!=i or not isinstance(rows,list)
            or len(rows)!=count or count!=(size if i<17 else total-size*17)):
            raise ValueError("native_current_page_actual_firstparty_server_denominator_changed")
        sizes.add(size)
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError("non_native_BSE_source_code_row")
            code=str(row.get("xxzqdm") or "").strip()
            name=str(row.get("xxzqjc") or "").strip()
            ymd=str(row.get("xxgprq") or "").strip()
            if (re.fullmatch(r"\d{6}",code) is None or not name
                or ymd!=str(row.get("fxssrq") or "").strip()
                or re.fullmatch(r"20\d{6}",ymd) is None):
                raise ValueError("missing_firstparty_current_native_security_fields")
            try:date(int(ymd[:4]),int(ymd[4:6]),int(ymd[6:]))
            except ValueError as exc:raise ValueError("invalid_native_listing_metadata") from exc
            original.append({"code":code,"native_name":name,"native_date_not_asof_BSE_effective":ymd})
    codes=[v["code"] for v in original]
    if (len(sizes)!=1 or len(original)!=348 or codes!=sorted(set(codes))
        or canon(original)!=report.get("query_candidate_rows_sha256")):
        raise ValueError("348_current_native_row_projection_not_exact_original_raw")
    ledger=report.get("joined")
    if not isinstance(ledger,list) or len(ledger)!=348:
        raise ValueError("current_native_code_join_reduced")
    for item,native_row in zip(ledger,original):
        code=native_row["code"]
        known=old.get(code) or new.get(code)
        expected=("OLD_CODE" if code in old else "NEW_920_CODE" if code in new
                  else "NO_MAPPING_IN_248_ROW_TABLE")
        if (item.get("query_code")!=code or item.get("current_alias_link")!=expected
            or item.get("mapped_old_code")!=(known["old_code"] if known else None)
            or item.get("mapped_new_code")!=(known["new_code"] if known else None)):
            raise ValueError("actual_348_source_code_to_248_alias_projection_disagrees")
    return {"alias_HTML_sha256":sha(alias_raw),
            "actual_original_native_query_page_count":18,
            "actual_original_native_current_security_rows":len(original),
            "raw_current_query_rows_sha256":canon(original),
            "actual_current_native_rows_not_historical_issuer_identity":"NOT VERIFIED"}

def replay_issuer_pdfs(original_dir:Path, report:dict, pinned_dir:Path)->dict:
    import fitz  # noqa: F401; required by original exact first-party parser
    primary=load_module(pinned_dir/"stock_bse_delist_source_witness.py","bse_pinned_363_PDF")
    docs=report.get("first_party_original_issuer_announcements")
    if not isinstance(docs,list) or len(docs)!=2:
        raise ValueError("two_native_issuer_original_PDFs_missing")
    seen=set()
    for item in docs:
        code=item.get("code")
        if code not in ("920305","920680") or code in seen:
            raise ValueError("two_original_issuer_PDF_security_ids_changed")
        seen.add(code)
        raw=(original_dir/f"stock_bse_delist_{code}.pdf").read_bytes()
        if sha(raw)!=item.get("official_pdf_raw_sha256"):
            raise ValueError("stored_native_pdf_SHA_and_provenance_mismatch")
        parsed=primary.parse(primary.CASES[code],raw)
        for field in ("issuer","code","full_body_sha256","first_page_text_sha256",
                "exchange_decision_received_day","announced_delisting_trade_open",
                "issuer_reported_final_delisting_trade_day","issuer_announced_exchange_delist_date",
                "source_announcement_date_from_path_not_timestamp"):
            if parsed.get(field)!=item.get(field):
                raise ValueError("independent_native_PDF_date_role_or_body_mismatch:"+field)
        if (parsed.get("actual_day_by_day_stock_trading_verified")!="NOT VERIFIED"
            or parsed.get("realized_exchange_delisting_register_verified")!="NOT VERIFIED"):
            raise ValueError("issuer_PDF_proposes_state_not_actual_master")
    return {"independent_firstparty_PDF_count":2,"original_PDF_source_registrar_state":"NOT VERIFIED"}

def main():
    import argparse
    a=argparse.ArgumentParser()
    for name in ("phase","current","delist","native_dir","pdf_dir","native_code","pdf_code","output"):
        a.add_argument("--"+name.replace("_","-"),dest=name,type=Path,required=True)
    p=a.parse_args()
    read=lambda f:json.loads(f.read_text(encoding="utf-8"))
    phase,current,delist=read(p.phase),read(p.current),read(p.delist)
    result={
        "native":replay_current(p.native_dir,current,p.native_code,phase["current_alias_raw_sha256"]),
        "issuer_PDF":replay_issuer_pdfs(p.pdf_dir,delist,p.pdf_code),
        "adjudication":{"independent_original_raw_projection":"PASS",
          "native_historical_security_master":"NOT VERIFIED",
          "actual_historical_ST_halt_or_register":"NOT VERIFIED",
          "complete_three_market_PIT":"NOT VERIFIED","final_gate":"FAIL"},
    }
    p.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"raw_18_page_348_security_projection":"PASS",
       "two_primary_original_PDF_redecoded":"PASS","historical_daily_PIT":"NOT VERIFIED",
       "final_gate":"FAIL"},sort_keys=True))
if __name__=="__main__":main()
