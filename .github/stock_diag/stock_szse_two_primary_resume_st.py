"""Two independently retrieved Shenzhen primary notices with explicit dated directives.

Qualified output: exchange notice announced terms only. A dated directive is
NOT independently verified actual completed market-day execution or daily PIT.
"""
from __future__ import annotations
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from bs4 import BeautifulSoup

SOURCE={
    "000981":{
        "shard":3,"index":338,
        "official_url":"https://www.szse.cn/disclosure/notice/temp/t20181119_557619.html",
        "official_response_sha256":"bb8d3711295d0bd729544a97c7e02c9ee3f85b77d0c0c14ee39dd106e8a4b1e5",
        "primary_body_sha256":"2fa87bb6740c33a2ce8418e9ab3e40b3455bd690c3f725e728dd052747bb872b",
        "notice_date":"2018-11-19","announced_resume_day":"2018-11-20",
        "expected_alias":"银亿股份",
    },
    "300630":{
        "shard":15,"index":1577,
        "official_url":"https://www.szse.cn/disclosure/notice/temp/t20250106_611420.html",
        "official_response_sha256":"953096ecb07647564c7ed921726b892d501eb029569937c5247f2918aa927664",
        "primary_body_sha256":"85cdd20b9450c578f4aa51339c2f1fd2e9a26cf3816fc4fd4c8f144c9777300e",
        "notice_date":"2025-01-06","announced_stop_day":"2025-01-06",
        "announced_resume_day":"2025-01-07","announced_risk_warning_start":"2025-01-07",
        "expected_alias":"普利制药","announced_warning_alias":"*ST普利",
    },
}
def sha(b): return hashlib.sha256(b).hexdigest()

def date_ymd(iso):
    d=date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"

def parse_announced_terms(code,text):
    """Positive exact primary-text event grammar, not a production state."""
    if code not in SOURCE:raise ValueError("unexpected_symbol")
    spec=SOURCE[code]
    if spec["expected_alias"] not in text:
        raise ValueError("issuer_alias_not_in_primary_notice")
    if not re.search(r"证券代码[：:]"+re.escape(code)+r"(?!\d)",text):
        raise ValueError("security_code_not_explicitly_attached")
    resume=date_ymd(spec["announced_resume_day"])
    if code=="000981":
        if ("本所决定" not in text or "股票" not in text
            or not re.search(r"自"+resume+r"开市起复牌",text)):
            raise ValueError("not_an_explicit_exchange_decision_and_resumption_day")
        return {"official_notice_decision":"EXCHANGE_STATED_RESUMPTION_DIRECTIVE",
            "notice_publication_date":spec["notice_date"],
            "announced_resume_day":spec["announced_resume_day"],
            "actual_market_resumption_executed":"NOT VERIFIED"}
    stop=date_ymd(spec["announced_stop_day"])
    warning=date_ymd(spec["announced_risk_warning_start"])
    if (not re.search(r"于"+stop+r"开市起停牌，?于"+resume+r"开市起复牌",text)
        or "退市风险警示" not in text
        or not re.search(r"公司股票于"+warning+r"开市起被实施",text)
        or spec["announced_warning_alias"] not in text):
        raise ValueError("stock_halt_resume_or_risk_warning_schedule_not_proven")
    return {"official_notice_decision":"STOCK_AND_CONVERTIBLE_HALT_RESUME_AND_RISK_WARNING_NOTICE",
        "notice_publication_date":spec["notice_date"],
        "announced_stop_day":spec["announced_stop_day"],
        "announced_resume_day":spec["announced_resume_day"],
        "announced_risk_warning_start":spec["announced_risk_warning_start"],
        "announced_warning_alias":spec["announced_warning_alias"],
        "actual_market_halt_executed":"NOT VERIFIED",
        "actual_market_resumption_executed":"NOT VERIFIED",
        "actual_historical_ST_day_state":"NOT VERIFIED"}

def load_primary(code,root):
    spec=SOURCE[code]
    # The actual first-party notice URL encodes its publication day.  A
    # free-standing manually frozen day is not source evidence on its own.
    filename=spec["official_url"].rsplit("/",1)[-1]
    match=re.fullmatch(r"t(20\\d{6})_\\d+\\.html",filename)
    if match is None:
        raise ValueError("unverifiable_official_notice_URL_day")
    url_day=match.group(1)
    try:
        date.fromisoformat(spec["notice_date"])
        declared_day=spec["notice_date"].replace("-","")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("malformed_original_notice_day") from exc
    if url_day!=declared_day:
        raise ValueError("notice_day_disagrees_with_first_party_URL")
    folder=root/f"shard-{spec['shard']:02d}"
    manifest=json.loads((folder/"szse_shard_report.json").read_text(encoding="utf-8"))
    rows=[r for r in manifest.get("records",[]) if r.get("index")==spec["index"]]
    if len(rows)!=1:raise ValueError("missing_or_duplicate_original_shard_source")
    row=rows[0]
    if (row.get("status")!="PASS" or row.get("url")!=spec["official_url"]
        or row.get("source_sha256")!=spec["official_response_sha256"]
        or row.get("article_body_sha256")!=spec["primary_body_sha256"]):
        raise ValueError("raw_official_document_identity_or_hash_mismatch")
    attempts=row.get("attempts")
    if (not isinstance(attempts,list) or not attempts
        or attempts[-1].get("status")!="PASS"
        or attempts[-1].get("http_status")!=200
        or attempts[-1].get("sha256")!=spec["official_response_sha256"]):
        raise ValueError("original_raw_http_provenance_not_verified")
    raw_name=row.get("raw_path")
    if (not isinstance(raw_name,str)
        or not re.fullmatch(r"szse_shard_raw/\d{4}_[123]_[0-9a-f]{64}\.html",raw_name)):
        raise ValueError("raw_article_file_path_not_bound")
    file=(folder/raw_name).resolve()
    if not file.is_file() or not file.is_relative_to(folder.resolve()) or file.is_symlink():
        raise ValueError("not_the_original_captured_HTML_file")
    raw=file.read_bytes()
    if sha(raw)!=spec["official_response_sha256"]:
        raise ValueError("first_party_raw_SHA256_mismatch")
    # Two verified first-party pages use UTF-8; no fuzzy/replace decoding.
    html=raw.decode("utf-8",errors="strict")
    el=BeautifulSoup(html,"html.parser").select_one(".news-detail-con #desContent")
    if el is None:raise ValueError("official_named_primary_article_missing")
    body=re.sub(r"\s+","",el.get_text("\n",strip=True))
    if sha(body.encode("utf-8"))!=spec["primary_body_sha256"]:
        raise ValueError("primary_article_body_SHA256_mismatch")
    terms=parse_announced_terms(code,body)
    return {"code":code,"official_url":spec["official_url"],
        "original_notice_date":spec["notice_date"],
        "original_official_response_sha256":spec["official_response_sha256"],
        "original_primary_article_body_sha256":spec["primary_body_sha256"],
        "source_status":"PRIMARY_EXCHANGE_NOTICE_TEXT_VERIFIED",
        **terms,
        "asof_listing_delisting_universe":"NOT VERIFIED",
        "whole_market_daily_ST_and_halt_PIT":"NOT VERIFIED",
    }

def build(root):
    evidence=[load_primary(code,root) for code in sorted(SOURCE)]
    return {"schema":"stock-szse-two-primary-stop-resume-risk-witness-v1",
      "primary_verified_notices":2,
      "provenance":evidence,
      "adjudication":{
        "official_named_first_party_exchange_notices":"PASS",
        "exact_dated_notice_claims":"PASS",
        "actual_executed_market_halt_resume":"NOT VERIFIED",
        "independent_historical_ST_day_state":"NOT VERIFIED",
        "full_SSE_SZSE_BSE_day_security_PIT":"NOT VERIFIED",
        "stock_advanced_business":"NOT VERIFIED",
        "final_gate":"FAIL",
      },
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    result=build(a.root)
    a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"official_primary_notices":2,
     "codes":[x["code"] for x in result["provenance"]],
     "announced_resume_days":[x["announced_resume_day"] for x in result["provenance"]],
     "announced_risk_warning_day":"2025-01-07",
     "actual_execution_and_complete_PIT":"NOT VERIFIED",
     "final_gate":"FAIL"},ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
