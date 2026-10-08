"""Synthetic adversarial cases ONLY; separate workflow loads pinned REAL source."""
import copy
from datetime import date
import importlib.util
from pathlib import Path
here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("bse_cross",here/"stock_bse_crosssource_phase_delist.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
P=list(sorted(m.PILOTS))
aliases=[]
for i in range(248):
    old,new=(("835305","920305") if i==246 else ("839680","920680") if i==247
            else (f"{430000+i:06d}",f"{920000+i:06d}"))
    name=P[i] if i<6 else f"SYNTHETIC_{i:03d}"
    aliases.append((old,new,name))
slices=[]
for old,new,name in aliases:
    start=date(2025,5,6) if name in m.PILOTS else date(2025,10,9)
    for day in m.DAYS:
        d=date.fromisoformat(day)
        state=("NOT_A_BSE_MARKET_DAY" if d<date(2021,11,15)
             else "HISTORICAL_ALIAS_NOT_SOURCE_VERIFIED_ASOF" if d<date(2025,4,11)
             else "EXCHANGE_ANNOUNCED_OLD_CODE_ROUTING" if d<start
             else "EXCHANGE_ANNOUNCED_NEW_920_CODE_ROUTING")
        slices.append({
          "current_alias_name":name,"legacy_code":old,"current_920_code":new,
          "historical_query_day":day,"official_notice_code_routing_asof":state,
          "official_notice_code_switch_effective_day":start.isoformat(),
          "source_original_list_date_not_BSE_listing":"2020-07-01",
          "historical_issuer_BSE_membership":"NOT VERIFIED",
          "historical_SecurityType1_daily_master":"NOT VERIFIED",
          "realized_daily_ST_suspension_or_trade":"NOT VERIFIED",
          "qualified_business_PIT":"NOT VERIFIED",
        })
phase={"schema":"stock-bse-two-phase-248-exchange-code-effective-v1",
       "source_current_alias_count":248,"pilot_count":6,"remaining_count":242,
       "total_asof_code_routing_witnesses":1984,"pilot_switch_effective_day_announced":"2025-05-06",
       "remaining_switch_effective_day_announced":"2025-10-09",
       "current_alias_raw_sha256":"f"*64,"asof_issuer_code_routing_only":slices,
       "adjudication":{"final_gate":"FAIL",
         "historical_native_SecurityType1_issuer_membership":"NOT VERIFIED"}}
joined=[{"query_code":old,"mapped_old_code":old,"mapped_new_code":new,
         "current_alias_link":"OLD_CODE",
         "bse_membership_on_any_prior_date":"NOT VERIFIED",
         "historical_920_code_valid_from":"NOT VERIFIED",
         "historical_native_stock_type":"NOT VERIFIED"} for old,new,_ in aliases[:246]]
joined+= [{"query_code":f"{800000+i:06d}","mapped_old_code":None,
          "mapped_new_code":None,"current_alias_link":"NO_MAPPING_IN_248_ROW_TABLE",
          "bse_membership_on_any_prior_date":"NOT VERIFIED",
          "historical_920_code_valid_from":"NOT VERIFIED",
          "historical_native_stock_type":"NOT VERIFIED"} for i in range(102)]
gap=[{"old_code":old,"new_code":new,"historical_membership":"NOT VERIFIED"} for old,new,_ in aliases[246:]]
current={"schema":"stock-bse-two-independent-current-surfaces-v1",
         "alias_source_raw_sha256":"f"*64,"alias_total":248,"filter2_query_total":348,
         "query_pages":18,"linked_current_query_rows":246,"query_rows_without_mapping":102,
         "unlinked_alias_rows":2,"query_raw_sha256":"a"*64,
         "query_candidate_rows_sha256":"b"*64,"joined":joined,
         "unlinked_alias_review":gap,"adjudication":{"final_gate":"FAIL"}}
event=[]
for old,new,_ in aliases[246:]:
    day,pub=m.REPORT_PDFS[(old,new)]
    event.append({"code":new,"official_pdf_raw_sha256":("c"*64 if new=="920305" else "d"*64),
          "full_body_sha256":"e"*64,
          "issuer_announced_exchange_delist_date":day,
          "source_announcement_date_from_path_not_timestamp":pub,
          "realized_exchange_delisting_register_verified":"NOT VERIFIED",
          "actual_day_by_day_stock_trading_verified":"NOT VERIFIED",
          "first_party_transport_status":"PASS"})
delist={"schema":"stock-bse-two-absent-current-code-delist-notice-witness-v1",
        "cross_source_alias_total":248,"cross_source_filter2_rows":348,
        "unlinked_alias_denominator":2,"notice_count":2,
        "first_party_original_issuer_announcements":event,
        "adjudication":{"official_issuer_pdf_stated_delist_and_decision_days":"PASS",
            "historical_BSE_actual_market_register_execution":"NOT VERIFIED",
            "final_gate":"FAIL"}}
inputs=[phase,current,delist]
r=m.reconcile(*inputs)
assert (r["firstparty_248_alias_denominator"],r["firstparty_348_current_filter2_denominator"],
        r["current_filter2_matched_aliases"],r["current_filter2_not_mapped"],
        r["current_aliases_unobserved_filter2_with_separate_PDF"])==(248,348,246,102,2)
assert len(r["asof_candidate_evidence"])==248
assert all(x["qualified_day_security_PIT"]=="NOT VERIFIED" for x in r["asof_candidate_evidence"])
assert {x["new_920_code"]:x["delist_PDF_stated_effective_day"] for x in r["asof_candidate_evidence"] if x["delist_PDF_stated_effective_day"]}=={"920305":"2026-07-30","920680":"2026-01-05"}
checks=["positive_full_248_348_and_two_stated_delist_PDFs"]
def negative(name,mutate):
    case=copy.deepcopy(inputs)
    mutate(case)
    try:m.reconcile(*case)
    except (ValueError,TypeError,KeyError,AttributeError):
        checks.append(name)
        return
    raise AssertionError("FAIL-OPEN:"+name)
negative("one_missing_current_mapped_issuer",lambda x:x[1]["joined"].pop(0))
negative("rebound_smaller_current_server_denominator",lambda x:(x[1]["joined"].pop(),x[1].__setitem__("filter2_query_total",347)))
negative("missing_one_original_248_alias_slice",lambda x:x[0]["asof_issuer_code_routing_only"].pop())
negative("historical_920_alias_injected_to_2024",lambda x:x[0]["asof_issuer_code_routing_only"][2].__setitem__("official_notice_code_routing_asof","EXCHANGE_ANNOUNCED_OLD_CODE_ROUTING"))
negative("source_report_false_final",lambda x:x[0]["adjudication"].__setitem__("final_gate","PASS"))
negative("relabel_2025-05-06_as_all_248_new",lambda x:x[0]["asof_issuer_code_routing_only"][m.DAYS.index("2025-05-06")+8*7].__setitem__("official_notice_code_routing_asof","EXCHANGE_ANNOUNCED_NEW_920_CODE_ROUTING"))
negative("source_alias_SHA_not_cross_bound",lambda x:x[1].__setitem__("alias_source_raw_sha256","0"*64))
negative("present_current_filter2_as_historical_PIT",lambda x:x[1]["joined"][0].__setitem__("historical_native_stock_type","PASS"))
negative("current_query_mapping_points_wrong_new_code",lambda x:x[1]["joined"][0].__setitem__("mapped_new_code","920999"))
negative("current_query_duplicated_native_security_code",lambda x:x[1]["joined"][1].__setitem__("query_code",x[1]["joined"][0]["query_code"]))
negative("missing_current_extra_not_in_248_alias_table",lambda x:x[1]["joined"].pop())
negative("unmapped_filter2_not_allowed_false_old_mapping",lambda x:x[1]["joined"][-1].__setitem__("mapped_new_code","920019"))
negative("unlinked_source_alias_issuer_not_original_2",lambda x:x[1]["unlinked_alias_review"][0].__setitem__("new_code","920019"))
negative("drop_independent_issuer_PDF_source",lambda x:x[2]["first_party_original_issuer_announcements"].pop())
negative("swap_issuer_delist_effective_date",lambda x:x[2]["first_party_original_issuer_announcements"][0].__setitem__("issuer_announced_exchange_delist_date","2026-01-05"))
negative("swap_original_source_announcement_date",lambda x:x[2]["first_party_original_issuer_announcements"][0].__setitem__("source_announcement_date_from_path_not_timestamp","2026-07-30"))
negative("fake_actual_exchange_register_execution",lambda x:x[2]["first_party_original_issuer_announcements"][0].__setitem__("realized_exchange_delisting_register_verified","PASS"))
negative("false_current_query_BSE_historical_membership",lambda x:x[1]["joined"][0].__setitem__("bse_membership_on_any_prior_date","PASS"))
negative("malformed_original_delist_PDF_SHA",lambda x:x[2]["first_party_original_issuer_announcements"][0].__setitem__("official_pdf_raw_sha256","broken"))
negative("partial_2020_hist_code_list",lambda x:x[0]["asof_issuer_code_routing_only"][0].__setitem__("historical_query_day","2024-04-22"))
negative("ambiguous_current_alias_issuer_change_between_days",lambda x:x[0]["asof_issuer_code_routing_only"][1].__setitem__("current_alias_name","OTHER"))
negative("phantom_third_unmatched_alias",lambda x:x[1]["unlinked_alias_review"].append({"old_code":"499999","new_code":"920999","historical_membership":"NOT VERIFIED"}))
assert len(checks)==23,(len(checks),checks)
print("BSE 248/348/2 first-party source and future PIT falsification OFFLINE 23/23 PASS")
