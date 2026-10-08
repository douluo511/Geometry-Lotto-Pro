"""Fail-first tests for exact raw-byte source drift, independent of date parsing."""
import copy
import importlib.util
from pathlib import Path

p=Path(__file__).with_name("stock_szse_current_source_drift.py")
sp=importlib.util.spec_from_file_location("source_drift",p)
m=importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)
URL="https://www.szse.cn/disclosure/notice/temp/"
ARCH="589fddec93bb26e05a067824dbca352129e2dc5db3c2f0027abd3a1d54ffad6e"
tests=[]
def fixture():
    old={"schema":"szse-effective-event-diagnostic-v1","source_frozen_denominator":2,
         "source_archive_sha256":ARCH,"adjudication":{"final_gate":"FAIL"},
         "rows":[{"official_url":URL+"t20180102_1.html","official_response_sha256":"a"*64,"archive_date":"20180102"},
                 {"official_url":URL+"t20180103_2.html","official_response_sha256":"b"*64,"archive_date":"20180103"}]}
    new={"schema":"stock-szse-1849-fresh-raw-source-merge-v1","source_frozen_denominator":2,
         "shards_verified":2,"raw_response_sha256_unique":2,
         "adjudication":{"full_1849_official_HTTP_and_scoped_primary_body":"PASS","final_gate":"FAIL"},
         "evidence":[{"url":URL+"t20180102_1.html","raw_sha256":"a"*64,"archive_date":"20180102"},
                     {"url":URL+"t20180103_2.html","raw_sha256":"b"*64,"archive_date":"20180103"}]}
    return old,new
def reject(title,change):
    old,new=fixture()
    change(old,new)
    try:
        m.compare(old,new,expected=2,expected_shards=2)
    except ValueError:
        tests.append(title)
        return
    raise AssertionError("false PASS "+title)
o,n=fixture()
r=m.compare(o,n,expected=2,expected_shards=2)
assert r["matched_receipts"]==2 and r["drifted_receipts"]==0
assert r["adjudication"]["production_historical_st_pit"]=="NOT VERIFIED"
tests.append("all source bytes match does not prove daily trading")
o,n=fixture()
n["evidence"][0]["raw_sha256"]="f"*64
r=m.compare(o,n,expected=2,expected_shards=2)
assert r["matched_receipts"]==1 and r["drifted_receipts"]==1
assert r["adjudication"]["source_byte_equivalence"]=="NOT VERIFIED"
tests.append("same source URL different bytes fails equivalence")
reject("omitted source document",lambda o,n:n["evidence"].pop())
reject("duplicate source URL",lambda o,n:n["evidence"][1].update({"url":n["evidence"][0]["url"]}))
reject("malformed SHA",lambda o,n:n["evidence"][0].update({"raw_sha256":"fake"}))
reject("different official URL",lambda o,n:n["evidence"][0].update({"url":URL+"t20180102_WRONG.html"}))
reject("fake source PASS",lambda o,n:n["adjudication"].update({"full_1849_official_HTTP_and_scoped_primary_body":"NOT VERIFIED"}))
reject("fewer shards",lambda o,n:n.update({"shards_verified":1}))
reject("changed denominator",lambda o,n:n.update({"source_frozen_denominator":1}))
reject("old production Final fraud",lambda o,n:o["adjudication"].update({"final_gate":"PASS"}))
reject("frozen URL index authority drift",lambda o,n:o.update({"source_archive_sha256":"f"*64}))
assert len(tests)==11,tests
print("STOCK FRESH-HISTORICAL RAW DRIFT TESTS 11/11 PASS")
