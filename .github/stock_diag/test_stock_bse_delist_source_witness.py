"""No false official executed-delisting PASS from current alias omission or forged PDFs."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("bse_delist",Path(__file__).with_name("stock_bse_delist_source_witness.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
tests=[]

def ok(name,fn):
    fn();tests.append(name)
def reject(name,fn):
    try:fn()
    except (ValueError, RuntimeError, StopIteration):
        tests.append(name);return
    raise AssertionError("FALSE PASS "+name)
def check(b):
    assert b

class Page:
    def __init__(self,text):self.text=text
    def get_text(self):return self.text
class Doc:
    def __init__(self,text):self.pages=[Page(text)]
    def __len__(self):return len(self.pages)
    def __iter__(self):return iter(self.pages)

def body(code):
    x=m.CASES[code]
    def chi(d):return f"{int(d[:4])}年{int(d[5:7])}月{int(d[8:])}日"
    return (
      f"证券代码：{code} {x['company']} {x['required_title']}\n"
      f"本公司股票于{chi(x['delisting_period_open'])}进入退市整理期。"
      f"截至{chi(x['delisting_period_last_session'])}公司股票退市整理期交易已满15个交易日。"
      f"公司股票将于{chi(x['issuer_announced_delist_day'])}被北京证券交易所终止上市并摘牌。"
      f"公司于{chi(x['decision_date'])}收到北京证券交易所出具关于股票终止上市的决定。"
      "（一）证券种类：人民币普通股"
    )
RAW=b"%PDF-FAKE-SYNTHETIC-NEGATIVE-TEST-ONLY"+b"0"*1024
DATA={"schema":"stock-bse-two-independent-current-surfaces-v1",
      "alias_total":248,"filter2_query_total":348,
      "linked_current_query_rows":246,"unlinked_alias_rows":2,
      "query_rows_without_mapping":102,"adjudication":{"final_gate":"FAIL"},
      "unlinked_alias_review":[
          {"old_code":c["old_code"],"new_code":code,"historical_membership":"NOT VERIFIED"}
          for code,c in m.CASES.items()]}
RECEIPTS={code:{"status":"PASS","raw_sha256":m.sha(RAW)} for code in m.CASES}
BYTES={code:RAW for code in m.CASES}

def parse_doc(case):
    code=next(k for k,v in m.CASES.items() if v is case)
    with patch.object(m.fitz,"open",return_value=Doc(body(code))):
        return m.parse(case,RAW)

for code in m.CASES:
    result=parse_doc(m.CASES[code])
    assert result["issuer_announced_exchange_delist_date"]==m.CASES[code]["issuer_announced_delist_day"]
    assert result["realized_exchange_delisting_register_verified"]=="NOT VERIFIED"
    tests.append(f"{code} correct notice role dates without claiming executed delisting")

def audit_both():
    def fake_open(*args,**kwargs):
        # Choose fake document based on caller bytes: all fake RAW identical
        # Instead, use two different PDF bytes preserving %PDF header.
        if kwargs.get("stream")==b"%PDF-FIRST"+b"0"*1100:
            return Doc(body("920305"))
        return Doc(body("920680"))
    raws={"920305":b"%PDF-FIRST"+b"0"*1100,"920680":b"%PDF-SECOND"+b"1"*1100}
    receipts={x:{"status":"PASS","raw_sha256":m.sha(data)} for x,data in raws.items()}
    with patch.object(m.fitz,"open",side_effect=fake_open):
        outcome=m.audit(DATA,raws,receipts)
    assert outcome["notice_count"]==2
    assert outcome["adjudication"]["official_issuer_pdf_stated_delist_and_decision_days"]=="PASS"
    assert outcome["adjudication"]["historical_BSE_actual_market_register_execution"]=="NOT VERIFIED"
    assert outcome["adjudication"]["final_gate"]=="FAIL"
ok("both issuer notices source-bound but not realized exchange register",audit_both)

reject("omit unlinked alias key",lambda:m.audit({**DATA,"unlinked_alias_review":DATA["unlinked_alias_review"][:1]},BYTES,RECEIPTS))
reject("change BSE code mapping",lambda:m.audit({**DATA,"unlinked_alias_review":[{**DATA["unlinked_alias_review"][0],"new_code":"920999"},DATA["unlinked_alias_review"][1]]},BYTES,RECEIPTS))
reject("declared current query too small",lambda:m.audit({**DATA,"filter2_query_total":347},BYTES,RECEIPTS))
reject("forged current final PASS",lambda:m.audit({**DATA,"adjudication":{"final_gate":"PASS"}},BYTES,RECEIPTS))
reject("alias incorrectly qualified historical membership",lambda:m.audit({**DATA,"unlinked_alias_review":[{**DATA["unlinked_alias_review"][0],"historical_membership":"PASS"},DATA["unlinked_alias_review"][1]]},BYTES,RECEIPTS))
reject("fake PDF raw digest",lambda:m.audit(DATA,BYTES,{**RECEIPTS,"920305":{"status":"PASS","raw_sha256":"f"*64}}))
reject("missing second actual PDF",lambda:m.audit(DATA,{"920305":RAW},RECEIPTS))
reject("HTTP 429 no PDF is source pass",lambda:m.audit(DATA,BYTES,{**RECEIPTS,"920305":{"status":"NOT VERIFIED","raw_sha256":m.sha(RAW)}}))

class FakeResp:
    def __init__(self,url,body,status=200):
        self.url=url;self.content=body;self.status_code=status
        self.headers={"Content-Type":"application/pdf"}
class FakeSession:
    def __init__(self,url,body,status=200):
        self.resp=FakeResp(url,body,status);self.calls=0
    def get(self,*a,**kw):self.calls+=1;return self.resp
case=m.CASES["920305"]
receipt,data=m.request_source(case,session=FakeSession(case["url"],RAW))
ok("200 + official URL PDF magic and raw bytes ledger",lambda:check(
   receipt["status"]=="PASS" and data==RAW and receipt["raw_sha256"]==m.sha(RAW)))
receipt,dat=m.request_source(case,session=FakeSession("https://evil.example/x.pdf",RAW))
ok("off-host fake PDF fails closed",lambda:check(receipt["status"]=="NOT VERIFIED" and dat is None))
receipt,dat=m.request_source(case,session=FakeSession(case["url"],b"<html>fake official</html>"))
ok("HTTP 200 HTML impersonating PDF rejected",lambda:check(receipt["status"]=="NOT VERIFIED" and dat is None))
receipt,dat=m.request_source(case,session=FakeSession(case["url"],RAW,429))
ok("rate-limited PDF no false PASS",lambda:check(receipt["status"]=="NOT VERIFIED" and dat is None))
reject("unsupported on-host different official PDF",lambda:m.official(
    "https://www.bse.cn/disclosure/2026/2026-07-29/other.pdf",case))
reject("unknown issuer case PDF",lambda:m.parse(case,b"%PDF-"))
for code,c in m.CASES.items():
    damaged=body(code).replace("终止上市并摘牌","上市并摘牌")
    with patch.object(m.fitz,"open",return_value=Doc(damaged)):
        reject(f"{code} future announced actual delist date must be explicit",
               lambda c=c:m.parse(c,RAW))
assert len(tests)==19,(len(tests),tests)
print("BSE TWO ISSUER NATIVE DELIST SOURCE CONTROLS 19/19 PASS")
