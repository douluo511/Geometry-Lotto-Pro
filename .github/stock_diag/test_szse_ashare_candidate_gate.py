"""Fail-first controls: share class, source binding and no daily-state promotion."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    o=importlib.util.module_from_spec(s)
    s.loader.exec_module(o)
    return o

m=module("gate",HERE/"stock_szse_ashare_candidate_gate.py")
production=module("stock_product_pit",HERE.parents[1]/"StockAIPro"/"staging"/"Stock_AI_Pro"/"versions"/"4.3.0"/"stock_ai"/"historical_pit.py")
cases=[]

def notice(day, number, codes, *, debt=(), category="SINGLE_EQUITY_CODE_NOTICE"):
    url=f"https://www.szse.cn/disclosure/notice/temp/t{day}_{number}.html"
    row={
        "official_url":url, "archive_date":day,
        "official_response_sha256":hashlib.sha256(url.encode()).hexdigest(),
        "semantic_excerpt_sha256":hashlib.sha256((url+"excerpt").encode()).hexdigest(),
        "identity_candidates":sorted(set(list(codes)+list(debt))),
        "equity_code_candidates":sorted(set(codes)),
        "convertible_code_candidates":sorted(set(debt)),
        "instrument_scope":category,
        "instrument_qualification":"NOT VERIFIED",
        "qualified_daily_st_or_suspension":"NOT VERIFIED",
    }
    return row

def fixture():
    rows=[
        notice("20180102","507883",["002628"]),
        notice("20180131","507926",["000613","200613"],category="MULTI_CLASS_EQUITY_NOTICE"),
        notice("20180201","507933",[],debt=["128100"],category="CONVERTIBLE_BOND_NOTICE"),
        notice("20180511","508100",["300197"],debt=["123004"],category="MIXED_EQUITY_AND_CONVERTIBLE_NOTICE"),
    ]
    bound=[]
    for row in rows:
        for code in row["equity_code_candidates"]:
            bound.append({
                "official_url":row["official_url"],
                "official_response_sha256":row["official_response_sha256"],
                "semantic_excerpt_sha256":row["semantic_excerpt_sha256"],
                "archive_date_not_effective_date":row["archive_date"],
                "equity_code_candidate":code,
                "multi_instrument_notice":len(row["equity_code_candidates"])+len(row["convertible_code_candidates"])>1,
                "actual_stock_lifecycle_qualified":"NOT VERIFIED",
                "actual_daily_suspension_qualified":"NOT VERIFIED",
            })
    return {
        "schema":"szse-effective-event-diagnostic-v1",
        "source_frozen_denominator":len(rows),
        "source_archive_sha256":"a"*64,
        "source_semantic_view_sha256":"b"*64,
        "source_records_sha256":"c"*64,
        "instrument_scope_counts":{
            "SINGLE_EQUITY_CODE_NOTICE":1,"MULTI_CLASS_EQUITY_NOTICE":1,
            "CONVERTIBLE_BOND_NOTICE":1,"MIXED_EQUITY_AND_CONVERTIBLE_NOTICE":1,
        },
        "rows":rows,"equity_candidate_bindings":bound,
        "equity_notice_rows":3,"equity_notice_code_candidates":4,
    }

def bad(name,modify):
    v=fixture()
    modify(v)
    try:
        m.classify(v,frozen_expected=4)
    except (ValueError,TypeError,KeyError):
        cases.append(name)
        return
    raise AssertionError("FAIL-OPEN:"+name)

v=fixture()
o=m.classify(v,frozen_expected=4)
assert o["source_frozen_denominator"]==4
assert (o["equity_notice_rows"],o["equity_notice_code_candidates"],
        o["szse_a_share_candidate_pairs"],o["szse_b_share_excluded_pairs"])==(3,4,3,1)
assert o["adjudication"]["production_historical_st_pit"]=="NOT VERIFIED"
assert o["adjudication"]["final_gate"]=="FAIL"
assert len(o["a_share_candidates"])==3
assert len(o["b_share_exclusion_ledger"])==1
assert all(x["actual_daily_suspension_qualified"]=="NOT VERIFIED" for x in o["a_share_candidates"])
cases.append("positive mixed-equity/bond and A/B no daily-state promotions")

assert production._market_for_code("002628")=="SZSE"
assert production._market_for_code("300197")=="SZSE"
assert production._market_for_code("200613") is None
assert production._market_for_code("128100") is None
assert production._market_for_code("123004") is None
cases.append("frozen product historic PIT real market-code contract")

bad("missing one notice rejected",lambda x:x["rows"].pop())
bad("source notice denominator cannot shrink",lambda x:x.__setitem__("source_frozen_denominator",3))
bad("fake archive digest rejected",lambda x:x.__setitem__("source_records_sha256","0123"))
bad("title/URL not first-party official",lambda x:x["rows"][0].__setitem__("official_url","https://example.com/disclosure/notice/temp/t20180102_507883.html"))
bad("http downgrade rejected",lambda x:x["rows"][0].__setitem__("official_url","http://www.szse.cn/disclosure/notice/temp/t20180102_507883.html"))
bad("malformed source response SHA rejected",lambda x:x["rows"][0].__setitem__("official_response_sha256","0"))
bad("altered source row response SHA rejected",lambda x:x["rows"][0].__setitem__("official_response_sha256","1"*64))
bad("source binding changed candidate ignored no longer",lambda x:x["equity_candidate_bindings"][0].__setitem__("equity_code_candidate","001234"))
bad("bond injected into equity candidate rejected",lambda x:x["rows"][2].__setitem__("equity_code_candidates",["128100"]))
bad("B share cannot masquerade as A share",lambda x:x["equity_candidate_bindings"][2].__setitem__("equity_code_candidate","000613"))
bad("duplicate notice code pair rejected",lambda x:x["equity_candidate_bindings"].append(copy.deepcopy(x["equity_candidate_bindings"][0])))
bad("missing A-share evidence pair rejected",lambda x:x["equity_candidate_bindings"].pop(0))
bad("fake actual full-day state rejected",lambda x:x["equity_candidate_bindings"][0].__setitem__("actual_daily_suspension_qualified","PASS"))
bad("fake lifecycle approved from notice rejected",lambda x:x["rows"][0].__setitem__("instrument_qualification","PASS"))
bad("fake source daily verified rejected",lambda x:x["rows"][0].__setitem__("qualified_daily_st_or_suspension","PASS"))
bad("code claimed absent in original notice",lambda x:x["rows"][0].__setitem__("identity_candidates",["600000"]))
bad("duplicate official URL rejected",lambda x:x["rows"][1].__setitem__("official_url",x["rows"][0]["official_url"]))
bad("changed source class counts rejected",lambda x:x["instrument_scope_counts"].__setitem__("CONVERTIBLE_BOND_NOTICE",0))
bad("mismatched archive day rejected",lambda x:x["equity_candidate_bindings"][0].__setitem__("archive_date_not_effective_date","20260930"))
bad("changed mixed-class flag rejected",lambda x:x["equity_candidate_bindings"][1].__setitem__("multi_instrument_notice",False))
assert len(cases)==22,(len(cases),cases)
print(f"STOCK A/B SHARE PRODUCTION PIF COHERENCE NEGATIVE/POSITIVE {len(cases)}/{len(cases)} PASS")
