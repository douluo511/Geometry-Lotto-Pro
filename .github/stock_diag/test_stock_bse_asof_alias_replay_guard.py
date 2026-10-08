"""Offline anti-forgery contracts; synthetic fixture NEVER qualifies a live source."""
import copy
from datetime import date
import hashlib
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("bse_replay",ROOT/"stock_bse_asof_alias_replay_guard.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SOURCE=b"OFFLINE_TEST_SYNTHETIC_NOT_FIRST_PARTY"
foot=m.FOOTNOTE
rows=[
    {"row_order":i,"symbol":f"SYNTHETIC_TEST_{i}",
     "old_code":f"{430000+i:06d}","new_code":f"{920000+i:06d}",
     "source_listed_date_not_BSE_effective":"2020-06-03" if i<=68 else "2022-08-03",
     "pre_BSE_market_open":i<=68,
     "BSE_asof_old_or_new_code_validity":"NOT VERIFIED",
     "share_class_and_issuer_lifecycle":"NOT VERIFIED"}
    for i in range(1,249)
]
observed={
    "rows":rows,"rows_count":248,
    "pre_BSE_original_listing_count":68,
    "official_date_column_qualification_note":foot,
    "official_date_column_note_sha256":hashlib.sha256(foot.encode()).hexdigest(),
}
report={
    "schema":"stock-bse-current-code-alias-diagnostic-v1",
    "source":m.SOURCE_URL,"actual_http_receipt":"PASS",
    "raw_sha256":hashlib.sha256(SOURCE).hexdigest(),
    "retrieved_at_utc":"2026-10-08T07:00:00+00:00",
    "observed":copy.deepcopy(observed),
    "attempts":[{"attempt":1,"status_code":200,"status":"PASS",
                 "sha256":hashlib.sha256(SOURCE).hexdigest(),
                 "raw_bytes":len(SOURCE),"at_utc":"2026-10-08T07:00:00+00:00",
                 "final_url":m.SOURCE_URL,"content_type":"text/html"}],
}
class Source:
    def _official(self,url):
        return url==m.SOURCE_URL
    def parse(self,raw,content_type):
        if raw!=SOURCE:raise ValueError("first_party_original_bytes_tampered")
        return copy.deepcopy(observed)

src=Source()
tests=[]
result=m.reject_false_asof(report,SOURCE,src)
assert result["first_party_current_alias_rows"]==248
assert result["old_selected_tier_listing_before_BSE_open"]==68
assert result["historical_status_counts"]=={"NOT VERIFIED":992,"NOT_A_BSE_MARKET_DAY":496}
assert result["adjudication"]["final_gate"]=="FAIL"
assert all(x["qualified_historical_PIT"]=="NOT VERIFIED" for x in result["source_checked_issuer_alias_slices"])
assert all(x["historical_BSE_listing_and_code_alias_state"]=="NOT_A_BSE_MARKET_DAY"
           for x in result["source_checked_issuer_alias_slices"] if x["historical_day_query"]<"2021-11-15")
tests.append("248 real-schema synthetic rows across six date slices, not live data")

def bad(name,modify):
    v=copy.deepcopy(report)
    raw=SOURCE
    raw=modify(v,raw) or raw
    try:m.reject_false_asof(v,raw,src)
    except (ValueError,TypeError,KeyError):
        tests.append(name)
        return
    raise AssertionError("FAIL OPEN: "+name)

bad("future live timestamp without tz",lambda r,b:r.__setitem__("retrieved_at_utc","2026-10-08T07:00:00"))
bad("wrong source host",lambda r,b:r.__setitem__("source","https://evil.example/fake.html"))
bad("fake source schema",lambda r,b:r.__setitem__("schema","future_qualified"))
bad("fake original HTML bytes",lambda r,b:b"FORGED_HTML")
bad("raw SHA changed without first-party bytes",lambda r,b:r.__setitem__("raw_sha256","0"*64))
bad("HTTP 404 is not primary",lambda r,b:r["attempts"][0].__setitem__("status_code",404))
bad("bad URL redirect",lambda r,b:r["attempts"][0].__setitem__("final_url","https://elsewhere.example"))
bad("no primary receipt",lambda r,b:r.__setitem__("attempts",[]))
bad("failed receipt cannot establish native alias",lambda r,b:r["attempts"][0].__setitem__("status","NOT VERIFIED"))
bad("response content changed SHA",lambda r,b:r["attempts"][0].__setitem__("sha256","1"*64))
bad("missing current alias",lambda r,b:r["observed"]["rows"].pop())
bad("old NEEQ code alias renamed without first party raw",lambda r,b:r["observed"]["rows"][0].__setitem__("old_code","430999"))
bad("post-dated 920 code injected",lambda r,b:r["observed"]["rows"][0].__setitem__("new_code","920999"))
bad("pre-open original dates cannot become modern BSE listing",lambda r,b:r["observed"]["rows"][0].__setitem__("source_listed_date_not_BSE_effective","2021-11-15"))
bad("selected-tier footnote omitted",lambda r,b:r["observed"].__setitem__("official_date_column_qualification_note",""))
bad("pre-open count silently reduced",lambda r,b:r["observed"].__setitem__("pre_BSE_original_listing_count",0))
bad("pretend historical 920 alias actually verified",lambda r,b:r["observed"]["rows"][0].__setitem__("BSE_asof_old_or_new_code_validity","PASS"))
bad("pretend issuer lifecycle from alias only",lambda r,b:r["observed"]["rows"][0].__setitem__("share_class_and_issuer_lifecycle","PASS"))
bad("future first selected-tier date invalid",lambda r,b:r["observed"]["rows"][0].__setitem__("source_listed_date_not_BSE_effective","2028-01-01"))
bad("observation time cannot claim future data",lambda r,b:r.__setitem__("retrieved_at_utc","2020-01-01T00:00:00+00:00"))
bad("duplicate successful HTTP receipts",lambda r,b:r["attempts"].append(copy.deepcopy(r["attempts"][0])))
# A byte-identical HTML snapshot cannot be reassigned to another
# historical/as-of observation time by editing only one JSON metadata field.
bad("report timestamp later than actual successful HTTP receipt",
    lambda r,b:r.__setitem__("retrieved_at_utc","2026-10-09T07:00:00+00:00"))
bad("report timestamp earlier than actual successful HTTP receipt",
    lambda r,b:r.__setitem__("retrieved_at_utc","2026-10-07T07:00:00+00:00"))
bad("successful HTTP receipt time altered but report remains unchanged",
    lambda r,b:r["attempts"][0].__setitem__("at_utc","2026-10-07T07:00:00+00:00"))
bad("successful HTTP receipt missing timestamp",
    lambda r,b:r["attempts"][0].pop("at_utc"))
def equivalent_utc_offset_preserves_same_instant():
    v=copy.deepcopy(report)
    v["retrieved_at_utc"]="2026-10-08T15:00:00+08:00"
    result=m.reject_false_asof(v,SOURCE,src)
    assert result["adjudication"]["final_gate"]=="FAIL"
    assert result["adjudication"]["BSE_historical_effective_920_code_alias"]=="NOT VERIFIED"
tests.append("same instant in Beijing offset accepted but still no historical PIT") if (equivalent_utc_offset_preserves_same_instant() is None) else None
assert len(tests)==27,(len(tests),tests)
print("STOCK BSE AS-OF CURRENT ALIAS ANTI-FUTURE-LEAKAGE 27/27 OFFLINE PASS")
