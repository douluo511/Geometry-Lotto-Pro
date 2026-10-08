"""Two current official BSE views: anti-denominator and no-historical-PIT controls."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
spec=importlib.util.spec_from_file_location("dual",here/"stock_bse_current_two_source_check.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

CASE=[]
def check(title,fn):
    fn();CASE.append(title)
def fail(title,fn):
    try:fn()
    except (ValueError,RuntimeError):CASE.append(title);return
    raise AssertionError("FALSE PASS: "+title)

ALIAS={
    "schema":"stock-bse-current-code-alias-diagnostic-v1",
    "actual_http_receipt":"PASS","raw_sha256":"a"*64,
    "adjudication":{"final_gate":"FAIL"},
    "observed":{"rows_count":3,"rows":[
        {"old_code":"832000","new_code":"920000","pre_BSE_market_open":True},
        {"old_code":"872931","new_code":"920931","pre_BSE_market_open":False},
        {"old_code":"832002","new_code":"920002","pre_BSE_market_open":False},
    ]}
}
QUERY={"rows":[{"code":"832000","native_name":"A","native_date_not_asof_BSE_effective":"20201223"},
               {"code":"920931","native_name":"B","native_date_not_asof_BSE_effective":"20240408"},
               {"code":"920999","native_name":"C","native_date_not_asof_BSE_effective":"20251012"}],
       "server_reported_total":3,"pages":1,
       "evidence":[{"page":0,"sha256":"b"*64}]}

def happy():
    v=m.join(ALIAS,QUERY)
    assert v["alias_total"]==3 and v["filter2_query_total"]==3
    assert v["linked_current_query_rows"]==2
    assert v["unlinked_alias_rows"]==1 and v["query_rows_without_mapping"]==1
    assert v["alias_pre_BSE_display_dates"]==1
    assert v["adjudication"]["historic_complete_BSE_issuer_membership"]=="NOT VERIFIED"
    assert v["adjudication"]["final_gate"]=="FAIL"
check("different current official sources cannot invent historical BSE identity",happy)
fail("alias HTTP current failure",lambda:m.join({**ALIAS,"actual_http_receipt":"NOT VERIFIED"},QUERY))
fail("alias source fake final PASS",lambda:m.join({**ALIAS,"adjudication":{"final_gate":"PASS"}},QUERY))
fail("source alias partial denominator",lambda:m.join({**ALIAS,"observed":{**ALIAS["observed"],"rows_count":4}},QUERY))
fail("server page partial total",lambda:m.join(ALIAS,{**QUERY,"server_reported_total":4}))
fail("lost page receipt",lambda:m.join(ALIAS,{**QUERY,"pages":2}))
fail("duplicate current query code",lambda:m.join(ALIAS,{**QUERY,"rows":[QUERY["rows"][0]]*3}))
fail("duplicate official alias source",lambda:m.join({**ALIAS,"observed":{"rows_count":3,"rows":[ALIAS["observed"]["rows"][0]]*3}},QUERY))
fail("source alias collision in new code",lambda:m.join({**ALIAS,"observed":{"rows_count":3,"rows":[ALIAS["observed"]["rows"][0],{**ALIAS["observed"]["rows"][1],"new_code":"920000"},ALIAS["observed"]["rows"][2]]}},QUERY))

class Response:
    def __init__(self,payload,url=m.API,status=200):
        self.content=json.dumps(payload,ensure_ascii=False).encode()
        self.url=url;self.status_code=status
class Sess:
    def __init__(self,responses):
        self.responses=list(responses)
        self.i=0
    def post(self,*a,**kw):
        x=self.responses[min(self.i,len(self.responses)-1)]
        self.i+=1
        return x

def page(n,content,total=3,pages=2,size=2):
    return [{"number":n,"numberOfElements":len(content),"totalElements":total,"totalPages":pages,
             "size":size,"content":content}]
def row(code,date="20240109"):
    return {"xxzqdm":code,"xxzqjc":"测试",
            "xxgprq":date,"fxssrq":date}
def fake_pages():
    return Sess([Response(page(0,[row("830001"),row("830002")])),
                 Response(page(1,[row("920003")]))])
def happy_pages():
    data=m.fetch_pages(session=fake_pages())
    assert data["pages"]==2 and data["server_reported_total"]==3
    assert len(data["rows"])==3 and len(data["evidence"])==2
    assert data["query_form"]==m.FORM
check("complete server-denominated two-page first-party POST",happy_pages)
fail("short nonfinal page",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001")]))])))
fail("duplicate code cross pages",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001"),row("830002")])),Response(page(1,[row("830002")]))])))
fail("page total changes",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001"),row("830002")])),Response(page(1,[row("920003")],total=4))])))
fail("off-host endpoint redirect",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001"),row("830002")]),url="https://evil.example/path")])) )
fail("HTTP 429 cannot be accepted",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001"),row("830002")]),status=429)])))
fail("future impossible native date",lambda:m.fetch_pages(session=Sess([Response(page(0,[row("830001","20240230"),row("830002")]))])))
fail("native dates disagree",lambda:m.fetch_pages(session=Sess([Response(page(0,[{**row("830001"),"fxssrq":"20240110"},row("830002")]))])))
fail("filtered page lacks native security class",lambda:m.fetch_pages(session=Sess([Response(page(0,[{"xxzqdm":"830001"},row("830002")]))])))
assert len(CASE)==18,(len(CASE),CASE)
print("STOCK BSE DUAL-CURRENT-SOURCE FALSIFICATION 18/18 PASS")
