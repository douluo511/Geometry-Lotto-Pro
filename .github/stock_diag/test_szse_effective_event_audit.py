"""Mandatory evidence/provenance and future-leakage negative controls for SZSE PIT."""
import importlib.util
from pathlib import Path
import hashlib
import json
import tempfile
from urllib.parse import urlparse

src=Path(__file__).with_name("stock_szse_effective_event_audit.py")
spec=importlib.util.spec_from_file_location("szse_effective",src)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
tests=[]

def row(text, title="深圳证券交易所关于停牌的公告", codes=None):
    if codes is None:
        codes=["002628"]
    return {
        "url":"https://www.szse.cn/disclosure/notice/temp/t20180102_507883.html",
        "archive_date":"20180102",
        "transport":{"status":"PASS","sha256":"a"*64},
        "status":"PASS","article_body_status":"PASS",
        "article_source":".news-detail-con #desContent",
        "semantic_sample":text,
        "semantic_sample_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "security_codes":codes,"title":title,
    }

def check(name, source, expected, *issues):
    r=m.classify(source)
    assert r["classification"]==expected,(name,r)
    for issue in issues:
        assert issue in r["missing_evidence"], (name,r["missing_evidence"])
    assert r["qualified_daily_st_or_suspension"]=="NOT VERIFIED"
    assert r["qualified_actual_resumption"]=="NOT VERIFIED"
    tests.append(name)
    return r

explicit="成都路桥证券代码002628于2018年1月2日开市起临时停牌，相关公告另行披露。"
r=check("explicit effective stop is only candidate",row(explicit),"EXPLICIT_STOP_CANDIDATE_ONLY")
assert r["explicit_effective_stop_date_candidates"]==["2018-01-02"]
check("date in footer is not effective stop",
      row("2018年1月2日深圳证券交易所公告。公司股票继续依法交易。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("intraday stop not all day",
      row("证券代码300885，2020年9月11日13时28分起临时停牌，于13时38分复牌。",codes=["300885"]),
      "INTRADAY_NOT_FULL_DAY")
check("conditional resumption is never actual",
      row("公司股票于2018年1月2日开市起停牌，待指定媒体披露公告后复牌。"),
      "EXPLICIT_STOP_CANDIDATE_ONLY")
assert m.classify(row("公司股票于2018年1月2日开市起停牌，待指定媒体披露公告后复牌。"))["conditional_resumption"]
check("prospective not realized",
      row("拟于2018年1月2日开市起临时停牌，尚待交易所核准。"),
      "PROSPECTIVE_NOT_REALIZED")
check("continued pause not new onset",
      row("公司股票2018年1月2日开市起继续停牌，另待公告。"),
      "CONTINUATION_NOT_NEW_STOP")
check("single source no unique code",
      row(explicit,codes=[]),"SOURCE_NOT_VERIFIED","unambiguous_instrument_identity")
check("ambiguous multiple symbols",
      row(explicit,codes=["002628","300885"]),"SOURCE_NOT_VERIFIED","unambiguous_instrument_identity")
bad=row(explicit); bad["semantic_sample_sha256"]="0"*64
check("tampered excerpt fails closed",bad,"SOURCE_NOT_VERIFIED","excerpt_hash")
bad=row(explicit);bad["transport"]["sha256"]="not-real"
check("unbound response fails closed",bad,"SOURCE_NOT_VERIFIED","source_sha256")
bad=row(explicit);bad["article_body_status"]="NOT VERIFIED"
check("page chrome not primary evidence",bad,"SOURCE_NOT_VERIFIED","primary_article")
bad=row(explicit);bad["url"]="https://example.com/not-the-official-source"
check("cross-domain data rejected",bad,"SOURCE_NOT_VERIFIED","official_host")
bad=row(explicit);bad["transport"]["status"]="NOT VERIFIED"
check("failed transport cannot generate PIT",bad,"SOURCE_NOT_VERIFIED","source_transport")
check("relative today cannot borrow archive day",
      row("今日开市起临时停牌，待进一步公告后复牌。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("impossible effective date is rejected",
      row("2026年2月30日开市起停牌，今日继续交易。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("invalid future-day explicit date not inferred",
      row("2027年1月9日发布文件，明年起将决定是否停牌。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("intraday overrides otherwise explicit stop",
      row("股票于2026年7月23日开市起临时停牌，今日09时44分复牌。"),
      "INTRADAY_NOT_FULL_DAY")
check("no actual resume from planned later announcement",
      row("公司股票2019年2月11日开市起停牌，待相关条件满足后复牌。"),
      "EXPLICIT_STOP_CANDIDATE_ONLY")
# Positive evidence candidates must never turn into realized daily PIT.
resume="深圳证券交易所公告，证券代码002628于2018年1月3日开市起复牌。"
r=check("dated official resume only candidate", row(resume), "EXPLICIT_RESUME_CANDIDATE_ONLY")
assert r["explicit_effective_resume_date_candidates"]==["2018-01-03"]
r=check("resume stated as restored trading only candidate",
        row("证券代码002628于2020年9月11日交易日起恢复交易。"),
        "EXPLICIT_RESUME_CANDIDATE_ONLY")
assert r["explicit_effective_resume_date_candidates"]==["2020-09-11"]
check("proposed resume cannot be completed",
      row("公司拟于2018年1月3日开市起复牌，仍待批复。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("pending condition cannot be completed",
      row("待审核完成后于2018年1月3日开市起复牌，条件仍未满足。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("impossible resume date refused",
      row("证券代码002628于2018年2月30日开市起复牌。"),
      "EFFECTIVE_DATE_UNRESOLVED")
check("publication date cannot be promoted to resumed state",
      row("2018年1月3日交易所公告复牌申请事项，尚待批准。"),
      "EFFECTIVE_DATE_UNRESOLVED")
r=check("stop and resume claims require full transition replay",
      row("公司股票于2018年1月2日开市起停牌，2018年1月3日开市起复牌。"),
      "MULTIPLE_TRANSITIONS_UNRESOLVED")
assert r["explicit_effective_stop_date_candidates"]==["2018-01-02"]
assert r["explicit_effective_resume_date_candidates"]==["2018-01-03"]
check("intraday resume is not all-day trading history",
      row("证券代码300885于2018年1月3日13时28分起复牌。",codes=["300885"]),
      "INTRADAY_NOT_FULL_DAY")
check("multiple contradictory resume dates unresolved",
      row("证券代码002628于2018年1月3日开市起复牌，2018年1月4日开市起复牌。"),
      "EFFECTIVE_DATE_UNRESOLVED")
bad=row(resume);bad["transport"]["status"]="NOT VERIFIED"
check("resume on unavailable source must not qualify", bad,
      "SOURCE_NOT_VERIFIED", "source_transport")

assert len(tests)==28
print("STOCK SOURCE-BOUND PIT SEMANTIC COUNTEREXAMPLES 28/28 PASS")
