"""Reject false historical BSE identities from current 920 alias mappings."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
s=importlib.util.spec_from_file_location("bse_alias",Path(__file__).with_name("stock_bse_code_alias_source.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
cases=[]

def fixture(*rows, header=None):
    header=header or ["序号","证券简称","上市日期","旧代码","新代码"]
    part=lambda vals:"<tr>"+"".join("<td>"+str(x)+"</td>" for x in vals)+"</tr>"
    return ("<html><body><table>"+part(header)+"".join(part(row) for row in rows)+"</table></body></html>").encode()
early=("1","2020挂牌股份","2020/12/23","832000","920000")
late=("2","无锡鼎邦","2024/4/8","872931","920931")
VALID=fixture(early,late)

def passed(label,fn):
    fn();cases.append(label)
def rejected(label,data):
    try:m.parse(data)
    except ValueError:cases.append(label);return
    raise AssertionError("FALSE PASS "+label)
def assert_that(check):
    assert check

def exact():
    r=m.parse(VALID)
    assert r["rows_count"]==2
    assert r["pre_BSE_original_listing_count"]==1
    assert r["rows"][0]["source_listed_date_not_BSE_effective"]=="2020-12-23"
    assert r["rows"][0]["BSE_asof_old_or_new_code_validity"]=="NOT VERIFIED"
    assert r["rows"][1]["new_code"]=="920931"
passed("current alias table parsed but before-BSE dates remain non-PIT",exact)
passed("deterministic parse",lambda:assert_that(m.parse(VALID)==m.parse(VALID)))
rejected("different header cannot be reinterpreted",fixture(early,late,header=["序号","券名","上市日期","旧代码","新代码"]))
rejected("missing header rejected",b"<html><table><tr><td>foo</td></tr></table></html>")
rejected("no actual mappings rejected",fixture())
rejected("duplicate legacy code",fixture(early,("2","其他","2024/4/8","832000","920931")))
rejected("duplicate new alias",fixture(early,("2","其他","2024/4/8","872931","920000")))
rejected("malformed new BSE 920 code",fixture(("1","股","2024/4/8","872931","830001")))
rejected("bad old six-digit code",fixture(("1","股","2024/4/8","BAD","920931")))
rejected("impossible date rejected",fixture(("1","股","2024/2/30","872931","920931")))
rejected("missing code pair rejected",fixture(("1","股","2024/4/8","872931","")))
rejected("row sequence gap rejected",fixture(("2","股","2024/4/8","872931","920931")))
rejected("duplicate header table rejected",b"<html>"+VALID+VALID+b"</html>")
rejected("extra column cannot silently be ignored",fixture(("1","股","2024/4/8","872931","920931","BAD")))
rejected("missing row column rejected",fixture(("1","股","2024/4/8","872931")))
class Response:
    def __init__(self,url,body,status=200,ctype="text/html; charset=utf-8"):
        self.url=url;self.content=body;self.status_code=status;self.headers={"Content-Type":ctype}
class Session:
    def __init__(self,response=None,fail=False):self.response=response;self.fail=fail;self.calls=0
    def get(self,*a,**kw):
        self.calls+=1
        if self.fail:raise ConnectionError("Network is unreachable")
        return self.response
def negative_network():
    sess=Session(fail=True)
    result,raw=m.fetch_and_review(sess)
    assert raw is None and sess.calls==3 and len(result["attempts"])==3
    assert result["actual_http_receipt"]=="NOT VERIFIED"
    assert result["adjudication"]["final_gate"]=="FAIL"
passed("failed real network is explicit NOT VERIFIED",negative_network)
def source_success():
    result,raw=m.fetch_and_review(Session(Response(m.URL,VALID)))
    assert result["actual_http_receipt"]=="PASS" and raw==VALID
    assert result["adjudication"]["historical_920_alias_effective_dates"]=="NOT VERIFIED"
    assert result["adjudication"]["production_historical_st_pit"]=="NOT VERIFIED"
passed("HTTP source success cannot qualify 2020 BSE stock lifetime",source_success)
def offhost():
    out,raw=m.fetch_and_review(Session(Response("https://evil.example/fake",VALID)))
    assert out["actual_http_receipt"]=="NOT VERIFIED" and raw is None
passed("off-host redirect rejects source identity",offhost)
def non200():
    out,_=m.fetch_and_review(Session(Response(m.URL,VALID,status=429)))
    assert out["actual_http_receipt"]=="NOT VERIFIED"
passed("429 cannot become historical source PASS",non200)
def malformed_source():
    out,_=m.fetch_and_review(Session(Response(m.URL,b"<html>missing table</html>")))
    assert out["actual_http_receipt"]=="NOT VERIFIED"
passed("HTTP 200 without official table cannot be PASS",malformed_source)
assert len(cases)==20,(len(cases),cases)
print("STOCK BSE CURRENT ALIAS AS-OF CONTROLS 20/20 PASS")
