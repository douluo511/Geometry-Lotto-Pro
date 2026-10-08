"""2024 BSE 920 IPO official source dates vs 2025 conversion falsifications."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("bse2024",Path(__file__).with_name("stock_bse_2024_ipo_primary_witness.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cases=[]

def assert_true(ok):
    assert ok

def pass_case(label,callback):
    callback();cases.append(label)
def reject(label,callback):
    try:callback()
    except (ValueError,RuntimeError):cases.append(label);return
    raise AssertionError("FALSE PASS "+label)

def html(key,mutate=""):
    spec=m.CASES[key]
    s="<html><body><h1>"+spec["exact_title"]+"</h1><main>"+". ".join(spec["required"])+"</main></body></html>"
    return s.replace(mutate,"") .encode() if mutate else s.encode()

def both():
    return {key:{"status":"PASS",**m.parse(key,html(key))} for key in m.CASES}

def positive():
    report=m.reconcile(both())
    assert report["new_920_ipo_code_rule_effective"]=="2024-04-22"
    assert report["new_920_ipo_actual_2024_listing_example"]=={"code":"920098","listed_date":"2024-12-05"}
    assert report["old_248_bse_equities_pilot_code_routing"]=="2025-05-06"
    assert report["old_248_bse_equities_rest_code_routing"]=="2025-10-09"
    assert report["adjudication"]["production_historical_st_pit"]=="NOT VERIFIED"
    assert report["adjudication"]["final_gate"]=="FAIL"
pass_case("BSE new IPO chronology separate from 248 old issuers",positive)
pass_case("original raw byte SHA stable",lambda:assert_true(
    m.parse("real_2024_920_ipo",html("real_2024_920_ipo"))["original_html_sha256"]==
    m.sha(html("real_2024_920_ipo"))))
reject("forged 2025 effective date for BSE 920 new IPO rule",lambda:m.parse(
    "new_ipo_920_rule",html("new_ipo_920_rule","2024年4月22日起施行")))
reject("2024 listed 920098 without original date",lambda:m.parse(
    "real_2024_920_ipo",html("real_2024_920_ipo","2024年12月5日")))
reject("2024 issuer code 920098 must be grounded",lambda:m.parse(
    "real_2024_920_ipo",html("real_2024_920_ipo","证券代码：920098")))
reject("issuer full legal company title absent",lambda:m.parse(
    "real_2024_920_ipo",html("real_2024_920_ipo","陕西科隆新材料科技股份有限公司")))
reject("BSE 2024 primary article title absent",lambda:m.parse(
    "new_ipo_920_rule",html("new_ipo_920_rule",m.CASES["new_ipo_920_rule"]["exact_title"])))
reject("unknown first-party source category",lambda:m.parse("another_notice",b"<html>bad</html>"))
reject("HTML after non-UTF8 byte spoof",lambda:m.parse("new_ipo_920_rule",b"\xff"+html("new_ipo_920_rule")))
reject("empty official source never counts",lambda:m.parse("new_ipo_920_rule",b""))
reject("off-host redirect invalid",lambda:m.official(
    "https://www.bse.cn.evil.invalid/important_news/200021617.html","new_ipo_920_rule"))
reject("different on-host primary path invalid",lambda:m.official(
    "https://www.bse.cn/important_news/200025603.html","new_ipo_920_rule"))
reject("query-parameter source identity spoof",lambda:m.official(
    m.CASES["new_ipo_920_rule"]["url"]+"?x=1","new_ipo_920_rule"))
reject("one primary evidence absent",lambda:m.reconcile({"real_2024_920_ipo":both()["real_2024_920_ipo"]}))
bad=both();bad["new_ipo_920_rule"]["historical_stock_day_ST_or_suspended"]="PASS"
reject("fake current daily PIT promotion disallowed",lambda:m.reconcile(bad))
bad=both();bad["real_2024_920_ipo"]["original_html_sha256"]="0"*64
# A valid 64-char malicious value cannot be authenticated without saved bytes;
# falsify by deleting field, not by pretending a digest length checks authenticity.
del bad["real_2024_920_ipo"]["original_html_sha256"]
reject("missing official byte digest disallowed",lambda:m.reconcile(bad))
bad=both();bad["real_2024_920_ipo"]["observed_statement_exact_phrases"]=[]
reject("unsourced issuer claims rejected",lambda:m.reconcile(bad))

class Response:
    def __init__(self,url,content,status=200,ctype="text/html"):
        self.url=url;self.content=content;self.status_code=status;self.headers={"Content-Type":ctype}
class Session:
    def __init__(self,response):self.response=response;self.count=0
    def get(self,*args,**kwargs):self.count+=1;return self.response
k="real_2024_920_ipo"
good=m.CASES[k]["url"]
def test_good():
    result,raw=m.fetch(k,Session(Response(good,html(k))))
    assert result["status"]=="PASS" and result["original_html_sha256"]==m.sha(raw)
    assert result["historical_stock_day_ST_or_suspended"]=="NOT VERIFIED"
pass_case("real source HTTP 200 scoped; no history upgrade",test_good)
def test_429():
    sess=Session(Response(good,html(k),429))
    result,raw=m.fetch(k,sess)
    assert raw is None and result["status"]=="NOT VERIFIED" and sess.count==3
pass_case("HTTP429 with correct source bytes still rejected",test_429)
def test_redirect():
    result,raw=m.fetch(k,Session(Response("https://example.com/other",html(k))))
    assert raw is None and result["status"]=="NOT VERIFIED"
pass_case("off-host redirected source cannot be primary receipt",test_redirect)
assert len(cases)==20,(len(cases),cases)
print("BSE 2024 NEW-IPO VS 2025 LEGACY SOURCE CONTRACTS 20/20 PASS")
