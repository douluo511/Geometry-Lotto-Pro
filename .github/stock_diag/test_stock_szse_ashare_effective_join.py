"""Falsify any candidate-join false PASS before touching business PIT."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path

p=Path(__file__).with_name("stock_szse_ashare_effective_join.py")
spec=importlib.util.spec_from_file_location("stock_candidate_join",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
HEX="a"*64
SEMH="b"*64
RECH="c"*64
notices=[
    "https://www.szse.cn/disclosure/notice/temp/t20180102_1.html",
    "https://www.szse.cn/disclosure/notice/temp/t20180103_2.html",
]

def fixtures():
    rows=[
        {"official_url":notices[0],"archive_date":"20180102","official_response_sha256":"1"*64,
         "semantic_excerpt_sha256":"2"*64,"qualified_daily_st_or_suspension":"NOT VERIFIED",
         "qualified_actual_resumption":"NOT VERIFIED","code":"000001","missing_evidence":[],
         "classification":"EXPLICIT_STOP_CANDIDATE_ONLY",
         "explicit_effective_stop_date_candidates":["2018-01-02"],
         "explicit_effective_resume_date_candidates":[],"intraday":False},
        {"official_url":notices[1],"archive_date":"20180103","official_response_sha256":"3"*64,
         "semantic_excerpt_sha256":"4"*64,"qualified_daily_st_or_suspension":"NOT VERIFIED",
         "qualified_actual_resumption":"NOT VERIFIED","code":None,
         "missing_evidence":["unambiguous_instrument_identity"],
         "classification":"SOURCE_NOT_VERIFIED",
         "explicit_effective_stop_date_candidates":[],
         "explicit_effective_resume_date_candidates":["2018-01-03"],"intraday":True},
    ]
    share={
        "schema":"szse-ashare-evidence-intake-v1","source_frozen_denominator":2,
        "source_archive_sha256":HEX,"source_semantic_view_sha256":SEMH,
        "source_aggregate_sha256":RECH,"equity_notice_code_candidates":2,
        "szse_a_share_candidate_pairs":1,"szse_b_share_excluded_pairs":1,
        "a_share_candidates":[{
            "official_url":notices[0],"equity_code_candidate":"000001",
            "official_response_sha256":"1"*64,"semantic_excerpt_sha256":"2"*64,
            "actual_stock_lifecycle_qualified":"NOT VERIFIED",
            "actual_daily_suspension_qualified":"NOT VERIFIED",
            "archive_date_not_effective_date":"20180102"
        }],"b_share_exclusion_ledger":[{
            "official_url":notices[1],"equity_code_candidate":"200001",
            "official_response_sha256":"3"*64,"semantic_excerpt_sha256":"4"*64,
            "actual_stock_lifecycle_qualified":"NOT VERIFIED",
            "actual_daily_suspension_qualified":"NOT VERIFIED",
            "archive_date_not_effective_date":"20180103"
        }],
        "adjudication":{"production_historical_st_pit":"NOT VERIFIED"}
    }
    dated={
        "schema":"szse-effective-event-diagnostic-v1","source_frozen_denominator":2,
        "source_archive_sha256":HEX,"source_semantic_view_sha256":SEMH,
        "source_records_sha256":RECH,"rows":rows,
        "adjudication":{"final_gate":"FAIL"}
    }
    return share,dated

cases=[]
def pass_case(name,action):
    action()
    cases.append(name)
def fail_case(name,mutate):
    s,d=fixtures()
    mutate(s,d)
    try:
        m.join(s,d,expected_notices=2,expected_a=1,expected_b=1)
    except (ValueError,TypeError):
        cases.append(name)
        return
    raise AssertionError("FALSE PASS: "+name)

def positive():
    s,d=fixtures()
    out=m.join(s,d,expected_notices=2,expected_a=1,expected_b=1)
    assert out["total_equity_notice_pairs"]==2
    assert out["a_share_candidate_pairs"]==1 and out["b_share_exclusions"]==1
    rows=out["pairs"]
    a=next(x for x in rows if x["candidate_asset_class"]=="A_SHARE_CANDIDATE")
    b=next(x for x in rows if x["candidate_asset_class"]=="B_SHARE_EXCLUDED")
    assert a["notice_stop_date_candidates"]==["2018-01-02"]
    assert b["notice_resume_date_candidates"]==[] and b["candidate_claim_scope"]=="MULTI_OR_UNQUALIFIED_NOTICE_REVIEW"
    assert all(x["realized_resumption"]=="NOT VERIFIED" for x in rows)
    assert out["adjudication"]["production_historical_st_pit"]=="NOT VERIFIED"
    assert out["adjudication"]["final_gate"]=="FAIL"

pass_case("positive candidate join, B-share excluded and no production status",positive)
fail_case("source URL dropped",lambda s,d:d["rows"].pop())
fail_case("source URL duplicated",lambda s,d:d["rows"][1].update({"official_url":notices[0]}))
fail_case("source aggregate sha differs",lambda s,d:s.update({"source_aggregate_sha256":"f"*64}))
fail_case("source archive sha differs",lambda s,d:d.update({"source_archive_sha256":"f"*64}))
fail_case("response raw sha tampered",lambda s,d:d["rows"][0].update({"official_response_sha256":"f"*64}))
fail_case("excerpt sha tampered",lambda s,d:d["rows"][0].update({"semantic_excerpt_sha256":"f"*64}))
fail_case("fake completed daily state",lambda s,d:d["rows"][0].update({"qualified_daily_st_or_suspension":"PASS"}))
fail_case("share identity already qualified",lambda s,d:s["a_share_candidates"][0].update({"actual_stock_lifecycle_qualified":"PASS"}))
fail_case("B-share injected as A-share",lambda s,d:s["a_share_candidates"][0].update({"equity_code_candidate":"200001"}))
fail_case("unknown source host",lambda s,d:d["rows"][0].update({"official_url":"https://evil.example/forged"}))
fail_case("malformed effective day",lambda s,d:d["rows"][0].update({"explicit_effective_stop_date_candidates":["not-a-date"]}))
fail_case("pair count truncated",lambda s,d:s["b_share_exclusion_ledger"].clear())
fail_case("incorrect source denominator",lambda s,d:s.update({"source_frozen_denominator":1}))
fail_case("source schema counterfeit",lambda s,d:d.update({"schema":"qualified-production-history"}))
# FAIL-FIRST counterexamples: old code must not accept absent evidence or
# inconsistent source/date metadata merely because two recorded SHA strings agree.
fail_case("missing evidence list is not proof of clean source",
          lambda s,d:d["rows"][0].pop("missing_evidence"))
fail_case("null evidence list is not proof of clean source",
          lambda s,d:d["rows"][0].update({"missing_evidence":None}))
fail_case("notice archive date disagrees with frozen share pair",
          lambda s,d:d["rows"][0].update({"archive_date":"20180104"}))
fail_case("share candidate archive date disagrees with official notice",
          lambda s,d:s["a_share_candidates"][0].update({"archive_date_not_effective_date":"20180104"}))
fail_case("calendar-impossible effective date despite valid yyyy-mm-dd syntax",
          lambda s,d:d["rows"][0].update({"explicit_effective_stop_date_candidates":["2018-02-30"]}))
fail_case("unknown classifier cannot emit dated claims",
          lambda s,d:d["rows"][0].update({"classification":"SYNTHETIC_FULL_DAY_PASS"}))

def mixed_transition_stays_unqualified():
    s,d=fixtures()
    row=d["rows"][0]
    row["classification"]="MULTIPLE_TRANSITIONS_UNRESOLVED"
    row["explicit_effective_resume_date_candidates"]=["2018-01-03"]
    out=m.join(s,d,expected_notices=2,expected_a=1,expected_b=1)
    pair=next(x for x in out["pairs"] if x["candidate_asset_class"]=="A_SHARE_CANDIDATE")
    assert pair["candidate_claim_scope"]=="MULTI_OR_UNQUALIFIED_NOTICE_REVIEW",pair
    assert pair["notice_stop_date_candidates"]==[],pair
    assert pair["notice_resume_date_candidates"]==[],pair
pass_case("mixed stop and resume cannot emit single-code dated candidates",
          mixed_transition_stays_unqualified)

def intraday_stays_unqualified():
    s,d=fixtures()
    row=d["rows"][0]
    row["classification"]="INTRADAY_NOT_FULL_DAY"
    row["intraday"]=True
    out=m.join(s,d,expected_notices=2,expected_a=1,expected_b=1)
    pair=next(x for x in out["pairs"] if x["candidate_asset_class"]=="A_SHARE_CANDIDATE")
    assert pair["candidate_claim_scope"]=="MULTI_OR_UNQUALIFIED_NOTICE_REVIEW",pair
    assert pair["notice_stop_date_candidates"]==[],pair
pass_case("intraday halt cannot masquerade as full-day effective date candidate",
          intraday_stays_unqualified)

assert len(cases)==23,cases
print("STOCK SZSE ASHARE/DATE JOIN CONTRACTS 23/23 PASS")
