"""Independent issuer/month first-party identity evidence anti-fabrication tests."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
from unittest.mock import patch

here=Path(__file__).with_name("stock_szse_native_listing_probe.py")
spec=importlib.util.spec_from_file_location("stock_native_listing",here)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cases=[]

def assert_true(ok):
    assert ok

def check(name,fn):
    fn();cases.append(name)

def reject(name,fn):
    try:fn()
    except (ValueError,RuntimeError):cases.append(name);return
    raise AssertionError("FALSE PASS: "+name)

class FakePage:
    def __init__(self,text):self.text=text
    def get_text(self):return self.text
class FakeDoc:
    def __init__(self,code="001399",when="2026 年 6 月 26 日",main=True):
        self.pages=[FakePage(f"惠科股份有限公司 股票代码：{code} 首次公开发行股票并在主板上市")]+[
            FakePage("惠科股份有限公司 股票将于 "+when+" 在深圳证券交易所主板上市。")]+[
            FakePage("正文内容") for _ in range(10)]+[
            FakePage(f"根据深圳证券交易所关于人民币普通股股票上市的通知 深证上〔2026〕873号 股票代码{code}，于 {when} 上市")]
    def __len__(self):return len(self.pages)
    def __getitem__(self,i):return self.pages[i]

def synthetic_pdf():
    return b"%PDF-1.7\nSYNTHETIC TEST NOT VALID DOCUMENT"

def html(date="2026/06/26",code="001399",duplicates=1,period="2026.06",label="新上市证券"):
    rows="".join(f"<tr><td>{code}</td><td>N惠科股份</td><td>10.12</td><td>700</td><td>430</td><td>{date}</td></tr>" for _ in range(duplicates))
    return f"<html><body><h1>{label} - （{period}）</h1><table>{rows}</table></body></html>".encode()

def fake_candidates():
    pairs=[{"equity_code_candidate":"001399","candidate_asset_class":"A_SHARE_CANDIDATE",
            "official_url":"https://www.szse.cn/disclosure/notice/temp/t20260626_123.html",
            "qualified_daily_st_pit":"NOT VERIFIED"}]
    pairs += [{"equity_code_candidate":f"002{i:03d}","candidate_asset_class":"A_SHARE_CANDIDATE",
               "official_url":f"https://www.szse.cn/disclosure/notice/temp/t20200102_{i}.html",
               "qualified_daily_st_pit":"NOT VERIFIED"} for i in range(957)]
    pairs += [{"equity_code_candidate":f"200{i:03d}","candidate_asset_class":"B_SHARE_EXCLUDED",
               "official_url":f"https://www.szse.cn/disclosure/notice/temp/t20200102_B{i}.html",
               "qualified_daily_st_pit":"NOT VERIFIED"} for i in range(9)]
    return {"schema":"stock-szse-dated-ashare-claims-join-v1",
        "source_frozen_denominator":1849,"total_equity_notice_pairs":967,
        "a_share_candidate_pairs":958,"b_share_exclusions":9,"pairs":pairs}

receipts={"PDF":{"status":"PASS","attempts":[{"sha256":"a"*64}]},
          "HTML":{"status":"PASS","attempts":[{"sha256":"b"*64}]}}

with patch.object(m.fitz,"open",return_value=FakeDoc()):
    positive=m.qualify(synthetic_pdf(),html(),receipts,fake_candidates())
    check("issuer & later SZSE monthly agree on exact stock listing date",
          lambda:assert_true(positive["issuer_claim"]["listing_date_in_issuer_announcement"]=="2026-06-26"))
    check("claim never promotes publication timestamp or realized trading",
          lambda:assert_true(positive["adjudication"]["page_publication_timestamp_pre_signal"]=="NOT VERIFIED"))
    check("no daily PIT pass or business promotion",
          lambda:assert_true(positive["adjudication"]["final_gate"]=="FAIL"))
    reject("wrong listed date on later monthly report",
           lambda:m.qualify(synthetic_pdf(),html(date="2026/06/27"),receipts,fake_candidates()))
    reject("duplicate issuer row",lambda:m.qualify(synthetic_pdf(),html(duplicates=2),receipts,fake_candidates()))
    reject("wrong stock code in statistical source",
           lambda:m.qualify(synthetic_pdf(),html(code="301669"),receipts,fake_candidates()))
    reject("wrong historical month",lambda:m.qualify(synthetic_pdf(),html(period="2026.05"),receipts,fake_candidates()))
    reject("wrong source title",lambda:m.qualify(synthetic_pdf(),html(label="债券市场"),receipts,fake_candidates()))
    bad=fake_candidates();bad["pairs"][0]["candidate_asset_class"]="B_SHARE_EXCLUDED"
    reject("001399 excluded as B-share cannot qualify",lambda:m.qualify(synthetic_pdf(),html(),receipts,bad))
    bad=fake_candidates();bad["pairs"][0]["qualified_daily_st_pit"]="PASS"
    reject("upstream fabricated daily PIT detected",lambda:m.qualify(synthetic_pdf(),html(),receipts,bad))
    bad=fake_candidates();bad["total_equity_notice_pairs"]=966
    reject("shrunk A+B candidate count rejected",lambda:m.qualify(synthetic_pdf(),html(),receipts,bad))
    bad=copy.deepcopy(receipts);bad["PDF"]["status"]="NOT VERIFIED"
    reject("unretrieved first-party issuer PDF rejected",lambda:m.qualify(synthetic_pdf(),html(),bad,fake_candidates()))
    with patch.object(m.fitz,"open",return_value=FakeDoc(code="301669")):
        reject("issuer security code mismatch",lambda:m.qualify(synthetic_pdf(),html(),receipts,fake_candidates()))
    with patch.object(m.fitz,"open",return_value=FakeDoc(when="2026年6月27日")):
        reject("issuer announcement listing date mismatch",lambda:m.qualify(synthetic_pdf(),html(),receipts,fake_candidates()))

reject("off-domain PDF rejected",lambda:m.official("https://example.com/report.PDF","PDF"))
reject("query can spoof official report URL",lambda:m.official(m.MONTH_URL+"?redirect=evil","HTML"))
reject("case-insensitive fake official netloc",lambda:m.official("https://docs.static.szse.cn.evil.org/www/market/periodical/month/W020260706503108829761.html","HTML"))
reject("non-PDF bytes rejected",lambda:m.parse_issuer(b"<html>fake</html>"))

class FakeHTTP:
    def __init__(self,url,raw,status=200,ctype="application/pdf"):
        self.url=url;self.content=raw;self.status_code=status
        self.headers={"Content-Type":ctype}
class FakeSession:
    def __init__(self,response):self.response=response
    def get(self,*args,**kwargs):return self.response
bad,raw=m.fetch(m.PDF_URL,"PDF",session=FakeSession(FakeHTTP(m.PDF_URL,b"<html>fake</html>")))
check("HTTP-200 non-PDF must not be valid listing proof",
      lambda:assert_true(bad["status"]=="NOT VERIFIED" and len(bad["attempts"])==3 and raw is None))

gb=html().decode("utf-8").replace(
    "<html>", '<html><head><meta charset="gb2312"></head>'
).encode("gb18030")
check("explicit official GB2312 declaration may decode strict GB18030",
      lambda:assert_true(m.parse_month(gb)["listing_date"]=="2026-06-26"))
not_declared=html().decode("utf-8").encode("gb18030")
reject("unlabelled GB bytes cannot silently invoke guessing",
       lambda:m.parse_month(not_declared))

assert len(cases)==21,cases
print("SZSE FIRST-PARTY LISTING SOURCE FAULT CONTROLS 21/21 PASS")
