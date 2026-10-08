"""BSE 248 current aliases + 348 current query rows + two original issuer PDFs.

Strict first-party source-integrity bridge ONLY. A present-day current-list
query and issuer delist notices are NOT an independent daily historical
SecurityType=1 membership file or a final executed delisting register.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
import hashlib
import json
import re
from pathlib import Path

ALIAS=248
QUERY=348
JOINED=246
EXTRAS=102
UNLINKED=2
PILOTS={"颖泰生物","艾融软件","龙竹科技","佳先股份","同享科技","球冠电缆"}
DAYS=("2020-01-02","2021-11-14","2024-04-22","2025-05-05",
      "2025-05-06","2025-10-08","2025-10-09","2026-10-08")
REPORT_PDFS={
    ("835305","920305"):("2026-07-30","2026-07-29"),
    ("839680","920680"):("2026-01-05","2025-12-31"),
}
HEX=re.compile(r"^[a-f0-9]{64}$")

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def checked_sha(value):
    if not isinstance(value,str) or HEX.fullmatch(value) is None:
        raise ValueError("missing_actual_firstparty_SHA256")
    return value

def reconcile(phases:dict,query:dict,delist:dict)->dict:
    if (phases.get("schema")!="stock-bse-two-phase-248-exchange-code-effective-v1"
        or phases.get("source_current_alias_count")!=ALIAS
        or phases.get("pilot_count")!=6 or phases.get("remaining_count")!=242
        or phases.get("total_asof_code_routing_witnesses")!=ALIAS*len(DAYS)
        or phases.get("pilot_switch_effective_day_announced")!="2025-05-06"
        or phases.get("remaining_switch_effective_day_announced")!="2025-10-09"
        or phases.get("adjudication",{}).get("final_gate")!="FAIL"
        or phases.get("adjudication",{}).get("historical_native_SecurityType1_issuer_membership")!="NOT VERIFIED"):
        raise ValueError("unqualified_or_truncated_official_BSE_alias_phase_lineage")
    original_alias_sha=checked_sha(phases.get("current_alias_raw_sha256"))
    if (query.get("schema")!="stock-bse-two-independent-current-surfaces-v1"
        or query.get("alias_source_raw_sha256")!=original_alias_sha
        or query.get("alias_total")!=ALIAS
        or query.get("filter2_query_total")!=QUERY
        or query.get("query_pages")!=18
        or query.get("linked_current_query_rows")!=JOINED
        or query.get("query_rows_without_mapping")!=EXTRAS
        or query.get("unlinked_alias_rows")!=UNLINKED
        or query.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("source_native_348_current_query_or_248_mapping_mismatch")
    checked_sha(query.get("query_raw_sha256"))
    checked_sha(query.get("query_candidate_rows_sha256"))
    if (delist.get("schema")!="stock-bse-two-absent-current-code-delist-notice-witness-v1"
        or delist.get("cross_source_alias_total")!=ALIAS
        or delist.get("cross_source_filter2_rows")!=QUERY
        or delist.get("unlinked_alias_denominator")!=UNLINKED
        or delist.get("notice_count")!=2
        or delist.get("adjudication",{}).get("official_issuer_pdf_stated_delist_and_decision_days")!="PASS"
        or delist.get("adjudication",{}).get("historical_BSE_actual_market_register_execution")!="NOT VERIFIED"
        or delist.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("unqualified_original_BSE_issuer_PDF_or_gap_denominator")
    events=delist.get("first_party_original_issuer_announcements")
    if not isinstance(events,list) or len(events)!=UNLINKED:
        raise ValueError("two_actual_source_documents_not_bound")
    signed={}
    for event in events:
        if not isinstance(event,dict):
            raise ValueError("invalid_dated_issuer_PDF_evidence")
        pair=(event.get("code"),event.get("official_pdf_raw_sha256"))
        old=event.get("code")
        oldpair=(event.get("code"),event.get("source_url"))
        # Actual source code and its matching earlier old-code identity are
        # checked against the two current-source unmatched aliases below.
        if old in signed:
            raise ValueError("duplicate_firstparty_issuer_delisting_evidence")
        checked_sha(event.get("official_pdf_raw_sha256"))
        checked_sha(event.get("full_body_sha256"))
        if (event.get("issuer_announced_exchange_delist_date")
            not in [r[0] for r in REPORT_PDFS.values()]
            or event.get("realized_exchange_delisting_register_verified")!="NOT VERIFIED"
            or event.get("actual_day_by_day_stock_trading_verified")!="NOT VERIFIED"
            or event.get("first_party_transport_status")!="PASS"):
            raise ValueError("PDF_future_announcement_promoted_to_executed_register")
        signed[old]=event
    if set(signed)!={"920305","920680"}:
        raise ValueError("two_firstparty_issuer_PDF_codes_missing")

    all_slices=phases.get("asof_issuer_code_routing_only")
    if not isinstance(all_slices,list) or len(all_slices)!=ALIAS*len(DAYS):
        raise ValueError("incomplete_official_alias_asof_date_slices")
    by_old={}
    code_seen=set()
    for item in all_slices:
        if not isinstance(item,dict):
            raise ValueError("malformed_historical_code_routing_slice")
        old,new,name,day=item.get("legacy_code"),item.get("current_920_code"),item.get("current_alias_name"),item.get("historical_query_day")
        if (not isinstance(old,str) or re.fullmatch(r"\d{6}",old) is None
            or not isinstance(new,str) or re.fullmatch(r"920\d{3}",new) is None
            or not isinstance(name,str) or not name or day not in DAYS):
            raise ValueError("unknown_native_alias_or_date_slice")
        if any(item.get(k)!="NOT VERIFIED" for k in (
            "historical_issuer_BSE_membership",
            "historical_SecurityType1_daily_master",
            "realized_daily_ST_suspension_or_trade",
            "qualified_business_PIT"
        )):
            raise ValueError("published_current_sources_misused_as_complete_daily_PIT")
        start=date(2025,5,6) if name in PILOTS else date(2025,10,9)
        d=date.fromisoformat(day)
        expected=("NOT_A_BSE_MARKET_DAY" if d<date(2021,11,15)
                  else "HISTORICAL_ALIAS_NOT_SOURCE_VERIFIED_ASOF" if d<date(2025,4,11)
                  else "EXCHANGE_ANNOUNCED_OLD_CODE_ROUTING" if d<start
                  else "EXCHANGE_ANNOUNCED_NEW_920_CODE_ROUTING")
        if (item.get("official_notice_code_routing_asof")!=expected
            or item.get("official_notice_code_switch_effective_day")!=start.isoformat()):
            raise ValueError("published_920_alias_date_or_no_lookahead_contradiction")
        existing=by_old.setdefault(old,{"symbol":name,"old_code":old,"new_code":new,
                         "source_original_list_date":item.get("source_original_list_date_not_BSE_listing"),
                         "phase_start":start.isoformat(),"days":set()})
        if (existing["new_code"]!=new or existing["symbol"]!=name
            or existing["phase_start"]!=start.isoformat()
            or existing["source_original_list_date"]!=item.get("source_original_list_date_not_BSE_listing")
            or day in existing["days"]):
            raise ValueError("discontinuous_or_duplicate_alias_identity")
        existing["days"].add(day)
    if (len(by_old)!=ALIAS or
        len({r["new_code"] for r in by_old.values()})!=ALIAS or
        sum(r["symbol"] in PILOTS for r in by_old.values())!=6 or
        any(r["days"]!=set(DAYS) for r in by_old.values())):
        raise ValueError("false_subset_became_current_historical_universe")

    qrows=query.get("joined")
    gap=query.get("unlinked_alias_review")
    if not isinstance(qrows,list) or len(qrows)!=QUERY or not isinstance(gap,list) or len(gap)!=UNLINKED:
        raise ValueError("current_primary_query_rows_or_gap_missing")
    codes=set();used=set();observed={};extras=[]
    for row in qrows:
        code=row.get("query_code")
        if not isinstance(code,str) or re.fullmatch(r"\d{6}",code) is None or code in codes:
            raise ValueError("duplicate_or_invalid_native_current_code")
        codes.add(code)
        old,new=row.get("mapped_old_code"),row.get("mapped_new_code")
        if old is None:
            if (new is not None or row.get("current_alias_link")!="NO_MAPPING_IN_248_ROW_TABLE"):
                raise ValueError("unmapped_current_source_fabricated_alias")
            extras.append(code)
        else:
            if (old not in by_old or by_old[old]["new_code"]!=new
                or code not in (old,new)
                or row.get("current_alias_link") not in ("OLD_CODE","NEW_920_CODE")
                or old in used):
                raise ValueError("one_current_query_code_not_source_bound")
            used.add(old)
            observed[old]=code
        for field in ("bse_membership_on_any_prior_date","historical_920_code_valid_from","historical_native_stock_type"):
            if row.get(field)!="NOT VERIFIED":
                raise ValueError("current_filter_enum_claims_false_historical_membership")
    if len(used)!=JOINED or len(extras)!=EXTRAS:
        raise ValueError("current_second_surface_denominator_reduced")
    lost=set(by_old)-used
    by_gap={(x.get("old_code"),x.get("new_code")) for x in gap}
    if (len(lost)!=2 or by_gap!={(x,by_old[x]["new_code"]) for x in lost}
        or by_gap!={("835305","920305"),("839680","920680")}
        or any(x.get("historical_membership")!="NOT VERIFIED" for x in gap)):
        raise ValueError("source_original_2_issuer_gap_removed_or_reclassified")
    for old,new in by_gap:
        event=signed.get(new)
        if event is None or event.get("code")!=new:
            raise ValueError("delist_issuer_original_PDF_missing")
        if event.get("issuer_announced_exchange_delist_date")!=REPORT_PDFS[(old,new)][0]:
            raise ValueError("dated_primary_BSE_issuer_delisting_statement_changed")
        if event.get("source_announcement_date_from_path_not_timestamp")!=REPORT_PDFS[(old,new)][1]:
            raise ValueError("source_PDF_notice_date_role_swapped")
    claims=[]
    for old in sorted(by_old):
        row=by_old[old]
        alias=(old,row["new_code"])
        event=signed.get(row["new_code"]) if old in lost else None
        claims.append({
            "old_code":old,"new_920_code":row["new_code"],
            "current_alias_issuer_name":row["symbol"],
            "firstparty_current_alias_raw_sha256":original_alias_sha,
            "official_920_switch_announced":row["phase_start"],
            "current_filter2_presence":"OBSERVED_IN_FILTER2_QUERY" if old in used else "NOT_OBSERVED_IN_FILTER2_QUERY",
            "current_query_code":observed.get(old),
            "delist_PDF_stated_effective_day":event["issuer_announced_exchange_delist_date"] if event else None,
            "delist_PDF_raw_sha256":event["official_pdf_raw_sha256"] if event else None,
            "delist_PDF_actual_market_register_execution":"NOT VERIFIED",
            "historical_issuer_listing_and_delisting_lifecycle":"NOT VERIFIED",
            "actual_daily_ST_suspension_trading":"NOT VERIFIED",
            "historical_native_SecurityType1":"NOT VERIFIED",
            "qualified_day_security_PIT":"NOT VERIFIED",
        })
    return {
        "schema":"stock-bse-248-phase-current-348-two-delist-reconciliation-v1",
        "source_current_alias_raw_sha256":original_alias_sha,
        "primary_current_filter2_receipt_ledger_sha256":query["query_raw_sha256"],
        "original_issuer_delist_PDF_sha256_by_920":{k:v["official_pdf_raw_sha256"] for k,v in sorted(signed.items())},
        "firstparty_248_alias_denominator":ALIAS,
        "firstparty_348_current_filter2_denominator":QUERY,
        "current_filter2_matched_aliases":JOINED,
        "current_filter2_not_mapped":EXTRAS,
        "current_aliases_unobserved_filter2_with_separate_PDF":UNLINKED,
        "firstparty_announced_920_pilot_date":"2025-05-06",
        "firstparty_announced_920_remaining_date":"2025-10-09",
        "candidate_issuer_event_evidence_sha256":digest(claims),
        "asof_candidate_evidence":claims,
        "adjudication":{
            "source_current_code_and_filter_denominators":"PASS",
            "two_independent_issuer_delist_PDF_claims":"PASS",
            "exact_920_switch_announced_dates":"PASS",
            "complete_historical_native_issuer_universe":"NOT VERIFIED",
            "independent_actual_exchange_delisting_execution":"NOT VERIFIED",
            "all_SSE_SZSE_BSE_daily_ST_halt_resumption":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    for f in ("phase","current","delist","output"):
        p.add_argument("--"+f,type=Path,required=True)
    a=p.parse_args()
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    result=reconcile(read(a.phase),read(a.current),read(a.delist))
    a.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in (
        "firstparty_248_alias_denominator","firstparty_348_current_filter2_denominator",
        "current_filter2_matched_aliases","current_filter2_not_mapped",
        "current_aliases_unobserved_filter2_with_separate_PDF",
        "adjudication")},sort_keys=True))
if __name__=="__main__":raise SystemExit(main())
