"""Offline-only current/live source provenance negative controls (not real network)."""
import copy,hashlib,importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location("stock_source",HERE/"stock_szse_live_candidate_rebind.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
cases=[]
def notice(i):
    url=f"https://www.szse.cn/disclosure/notice/temp/t20200102_{500000+i}.html"
    body="证券代码000001在交易所披露关于股票临时停牌的公告，完整原文可查询。"
    return {
       "url":url,"archive_date":"20200102",
       "status":"PASS",
       "transport":{"status":"PASS","http_status":200,"same_official_host":True,
                    "resolved_url":url,"sha256":hashlib.sha256(url.encode()).hexdigest()},
       "article_body_status":"PASS","article_source":".news-detail-con #desContent",
       "body_text_chars":len(body),"body_text_sha256":hashlib.sha256(body.encode()).hexdigest(),
       "semantic_sample":body,"semantic_sample_sha256":hashlib.sha256(body.encode()).hexdigest(),
       "security_codes":["000001"],"title":"深交所股票临时停牌公告",
       "stop_terms":["停牌"],"resume_terms":[],
    }
original=[notice(i) for i in range(m.SHARDS)]
frozen={
    "schema":"stock-szse-suspension-detail-corpus-v1",
    "source_archive":{"event_rows":m.SHARDS,"canonical_sha256":m.ARCHIVE_SHA},
    "records":copy.deepcopy(original),
}
def input_shards():
    return {i:{
        "schema":"szse-1849-shard-live-v1",
        "shard_total":m.SHARDS,"shard_index":i,"frozen_total":m.SHARDS,
        "source_archive_sha256":m.ARCHIVE_SHA,
        "selected":1,"pass":1,"nonpass":0,"records":[copy.deepcopy(original[i])],
        "adjudication":{"daily_st_suspension_pit":"NOT VERIFIED","final_gate":"FAIL"},
    } for i in range(m.SHARDS)}
docs=input_shards()
r=m.rebind(frozen,docs,expected_total=m.SHARDS)
assert len(r["records"])==m.SHARDS
assert r["adjudication"]["live_official_notice_primary_body"]=="PASS"
assert r["adjudication"]["three_market_ST_suspension_daily_PIT"]=="NOT VERIFIED"
assert r["source_lineage"]["official_html_response_sha_changed_count"]==0
cases.append("positive 13-shard source without state promotion")

def rejected(name,func):
    x=copy.deepcopy(docs)
    y=copy.deepcopy(frozen)
    func(y,x)
    try:m.rebind(y,x,expected_total=m.SHARDS)
    except (ValueError,KeyError,TypeError):
        cases.append(name)
        return
    raise AssertionError("accepted forbidden live source: "+name)

rejected("missing one exact-run live shard",lambda y,x:x.pop(12))
rejected("fabricated first-party shard PASS",lambda y,x:x[0].update(pass_=0,**{"pass":0}))
rejected("mutated official URL list",lambda y,x:x[0]["records"][0].update(url="https://www.szse.cn/disclosure/notice/temp/other.html"))
rejected("swapped shards not accepted",lambda y,x:(x[0]["records"],x[1]["records"])==(x[1]["records"],x[0]["records"]))
rejected("bad first-party response SHA",lambda y,x:x[1]["records"][0]["transport"].update(sha256="bad"))
rejected("cross-origin redirect rejected",lambda y,x:x[1]["records"][0]["transport"].update(resolved_url="https://bad.example/"))
rejected("generic DOM cannot qualify live body",lambda y,x:x[1]["records"][0].update(article_source=".content"))
rejected("semantic excerpt was mutated",lambda y,x:x[1]["records"][0].update(semantic_sample_sha256="0"*64))
rejected("unrecognized real response status",lambda y,x:x[1]["records"][0].update(status="NOT VERIFIED"))
rejected("fake qualified daily status refused",lambda y,x:x[1]["adjudication"].update(daily_st_suspension_pit="PASS"))
rejected("wrong frozen first-party count",lambda y,x:y["source_archive"].update(event_rows=1849))
rejected("wrong old source archive SHA",lambda y,x:y["source_archive"].update(canonical_sha256="0"*64))
rejected("invalid snippet fails closed",lambda y,x:x[1]["records"][0].update(semantic_sample=None))

moved=input_shards()
moved[1]["records"][0]["transport"]["sha256"]="a"*64
out=m.rebind(frozen,moved,expected_total=m.SHARDS)
assert out["source_lineage"]["official_html_response_sha_changed_count"]==1
assert out["adjudication"]["three_market_ST_suspension_daily_PIT"]=="NOT VERIFIED"
cases.append("changed official raw response SHA retained as drift")

moved=input_shards()
moved[1]["records"][0]["security_codes"]=["001234"]
out=m.rebind(frozen,moved,expected_total=m.SHARDS)
assert out["source_lineage"]["security_code_semantics_changed_count"]==1
assert out["adjudication"]["cross_snapshot_semantics"]=="NOT VERIFIED"
cases.append("changed official symbol taxonomy reported unqualified")

assert len(cases)==16,(len(cases),cases)
print("STOCK LIVE SZSE TO EQUITY CANDIDATE BINDING OFFLINE COUNTEREXAMPLES 16/16 PASS")
