"""Synthetic offline controls, NOT real BSE raw evidence or historical quotes."""
import copy
from datetime import date
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("official_bse_two_phase",HERE/"stock_bse_two_phase_920_effective.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
tests=[]
names=list(m.PILOTS)+[f"SYNTHETIC_ISSUER_{i:03d}" for i in range(242)]
rows=[
    {"row_order":i+1,"symbol":name,
     "old_code":f"{430000+i:06d}","new_code":f"{920000+i:06d}",
     "source_listed_date_not_BSE_effective":"2020-07-27" if i<68 else "2023-01-03",
     "pre_BSE_market_open":i<68,
     "BSE_asof_old_or_new_code_validity":"NOT VERIFIED"}
    for i,name in enumerate(names)
]
current={"schema":"stock-bse-current-code-alias-diagnostic-v1",
 "actual_http_receipt":"PASS",
 "source":"https://www.bse.cn/service/code_mapping.html",
 "raw_sha256":"f"*64,
 "observed":{"rows_count":248,"pre_BSE_original_listing_count":68,"rows":rows}}
raw={}
notices={}
for name,spec in m.ANNOUNCEMENTS.items():
    publication=date.fromisoformat(spec["publication"])
    content=(spec["title"]+f"{publication.year}-{publication.month:02d}-{publication.day:02d}"
             +"".join(spec["phrases"])+"北京证券交易所")
    raw[name]=("<html><main>"+content+"</main></html>").encode("utf-8")
    record=m.parse_announcement(name,raw[name])
    notices[name]={"status":"PASS",**record}
tests.append("all 3 synthetic official phrase schemas parse with dated header")
r=m.build(current,notices)
assert r["pilot_count"]==6 and r["remaining_count"]==242
assert r["total_asof_code_routing_witnesses"]==248*11
assert r["adjudication"]["final_gate"]=="FAIL"
assert all(row["historical_issuer_BSE_membership"]=="NOT VERIFIED" for row in r["asof_issuer_code_routing_only"])
def phase(day):
    dayrows=[x for x in r["asof_issuer_code_routing_only"] if x["historical_query_day"]==day]
    assert len(dayrows)==248
    return [x for x in dayrows if x["official_notice_code_routing_asof"]=="EXCHANGE_ANNOUNCED_NEW_920_CODE_ROUTING"]
assert len(phase("2024-04-22"))==0
# A 2025 official list cannot be injected into a 2024 point-in-time backtest.
early=[x for x in r["asof_issuer_code_routing_only"] if x["historical_query_day"]=="2024-04-22"]
assert len(early)==248
assert all(x["official_notice_code_routing_asof"]=="HISTORICAL_ALIAS_NOT_SOURCE_VERIFIED_ASOF"
           for x in early), "2024 aliases are exposed by a later 2025/26 source"
# No official Apr 25 activation instruction may be treated as already
# known on Apr 11/24; even Apr 25 is intraday-UNKNOWN absent a
# verified exact first-party publication time relative to a signal.
for no_knowledge_day in ("2025-04-11","2025-04-24","2025-04-25"):
    matching=[x for x in r["asof_issuer_code_routing_only"]
              if x["historical_query_day"]==no_knowledge_day]
    assert len(matching)==248
    assert all(x["official_notice_code_routing_asof"]==
               "HISTORICAL_ALIAS_NOT_SOURCE_VERIFIED_ASOF" for x in matching), (
               "FALSE PASS: future Apr 25 bulletin leaks into "+no_knowledge_day)
assert len(phase("2025-05-05"))==0
assert len(phase("2025-05-06"))==6
assert len(phase("2025-10-08"))==6
assert len(phase("2025-10-09"))==248
assert len(phase("2026-10-08"))==248
tests.append("exact 0→6→248 two-phase code routing, with historic issuer membership unknown")

def reject(name,fn):
    c=copy.deepcopy(current);n=copy.deepcopy(notices)
    fn(c,n)
    try:m.build(c,n)
    except (ValueError,KeyError,TypeError):
        tests.append(name);return
    raise AssertionError("FAIL OPEN: "+name)
reject("missing official pilot selection",lambda c,n:n.pop("pilot_selection"))
reject("missing official pilot activation",lambda c,n:n.pop("pilot_activation"))
reject("missing official 242 general activation",lambda c,n:n.pop("remaining_activation"))
reject("false official May publication",lambda c,n:n["pilot_activation"].__setitem__("publication_metadata_date","2025-05-07"))
reject("official original raw digest missing",lambda c,n:n["pilot_activation"].__setitem__("source_response_sha256","invalid"))
reject("official source claim changed",lambda c,n:n["pilot_activation"].__setitem__("verified_explicit_bulletin_phrases",[]))
reject("third-party source URL not original",lambda c,n:n["remaining_activation"].__setitem__("official_url","https://other.com"))
reject("original source only selected, not launched",lambda c,n:n["pilot_activation"].__setitem__("status","NOT VERIFIED"))
reject("current mapping 247 cannot become 248",lambda c,n:c["observed"]["rows"].pop())
reject("present-day 920 code without source provenance",lambda c,n:c.__setitem__("raw_sha256","bad"))
reject("missing one of six officially named pilots",lambda c,n:c["observed"]["rows"][0].__setitem__("symbol","ANOTHER_NOT_PILOT"))
reject("unresolved duplicate issuer aliases",lambda c,n:c["observed"]["rows"][7].__setitem__("symbol",c["observed"]["rows"][0]["symbol"]))
reject("current mapping cannot be a historical BSE PIT",lambda c,n:c["observed"]["rows"][0].__setitem__("BSE_asof_old_or_new_code_validity","PASS"))
reject("current alias source cannot be absent",lambda c,n:c.__setitem__("actual_http_receipt","NOT VERIFIED"))
reject("new data is not 248 original aliases",lambda c,n:c["observed"].__setitem__("rows_count",247))
reject("BSE pre-opening selected tier denominator cannot be silently altered",lambda c,n:c["observed"].__setitem__("pre_BSE_original_listing_count",0))

def reject_raw(name,mutation):
    data=mutation(raw["pilot_activation"])
    try:m.parse_announcement("pilot_activation",data)
    except (ValueError,TypeError):
        tests.append(name);return
    raise AssertionError("FAILED TO REJECT HTML CORRUPTION: "+name)
reject_raw("raw HTML changed May 6 to May 7",lambda b:b.replace(b"2025\xe5\xb9\xb45\xe6\x9c\x886\xe6\x97\xa5",b"2025\xe5\xb9\xb45\xe6\x9c\x887\xe6\x97\xa5"))
reject_raw("raw bulletin with missing article title",lambda b:b.replace(m.ANNOUNCEMENTS["pilot_activation"]["title"].encode(),b"WRONG_PRIMARY_ISSUE"))
reject_raw("raw bulletin with wrong original publication",lambda b:b.replace(b"2025-04-25",b"2025-04-26"))
reject_raw("non-UTF8 response rejected",lambda b:b"\xff\xff")
assert len(tests)==22,(len(tests),tests)
print("STOCK BSE TWO-PHASE OFFICIAL CODE EFFECTIVE 22/22 SYNTHETIC NEGATIVE/POSITIVE PASS")
