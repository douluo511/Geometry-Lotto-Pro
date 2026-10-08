"""Diagnose FULL BODY effective stop/resume dates in independent raw SZSE notices.

Source: exact official 19-shard raw-byte artifact, originally validated by #342.
Never equate dated text with a completed stock state transition or daily ST PIT.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
from bs4 import BeautifulSoup

TOTAL=1849
SHARDS=19
A_SHARES=958
B_SHARES=9
RAW_RE=re.compile(r"^szse_shard_raw/[0-9]{4}_[123]_[a-f0-9]{64}\.html$")

def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()
def load_mod(name,path:Path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def full_body_crosscheck(live:dict,join:dict,raw_root:Path,detail,parser)->dict:
    if (live.get("schema")!="stock-szse-suspension-detail-corpus-v1"
        or len(live.get("records",[]))!=TOTAL
        or live.get("summary",{}).get("body_text_extracted")!=TOTAL
        or live.get("adjudication",{}).get("final_gate")!="FAIL"
        or join.get("schema")!="stock-szse-dated-ashare-claims-join-v1"
        or join.get("a_share_candidate_pairs")!=A_SHARES
        or join.get("b_share_exclusions")!=B_SHARES
        or join.get("total_equity_notice_pairs")!=A_SHARES+B_SHARES
        or join.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("frozen_source_or_Ashare_candidate_contract_invalid")
    live_by_url={}
    for row in live["records"]:
        url=row.get("url")
        if not isinstance(url,str) or url in live_by_url:
            raise ValueError("live_URL_duplicate_or_invalid")
        live_by_url[url]=row
    by_url={}
    cases=[]
    seen_index=set()
    for shard_index in range(SHARDS):
        folder=raw_root/f"shard-{shard_index:02d}"
        report_path=folder/"szse_shard_report.json"
        if not report_path.is_file():
            raise ValueError(f"missing_independent_raw_shard:{shard_index}")
        report=json.loads(report_path.read_text(encoding="utf-8"))
        expected_n=min(100,TOTAL-shard_index*100)
        if (report.get("schema")!="stock-szse-frozen-shard-fresh-network-v1"
            or report.get("shard_index")!=shard_index
            or report.get("shard_count")!=SHARDS
            or report.get("full_frozen_denominator")!=TOTAL
            or report.get("requested")!=expected_n
            or report.get("verified")!=expected_n
            or report.get("missing")!=0
            or report.get("adjudication",{}).get("final_gate")!="FAIL"
            or len(report.get("records") or [])!=expected_n):
            raise ValueError(f"shard_incomplete_or_wrong:{shard_index}")
        for item in report["records"]:
            ix=item.get("index")
            url=item.get("url")
            raw_rel=item.get("raw_path")
            if (not isinstance(ix,int) or ix<0 or ix>=TOTAL or ix in seen_index
                or not isinstance(url,str) or url in by_url
                or ix//100!=shard_index
                or item.get("status")!="PASS"
                or item.get("source_type")!="fresh_official_HTTP"
                or not isinstance(raw_rel,str) or RAW_RE.fullmatch(raw_rel) is None):
                raise ValueError("unqualified_raw_first_party_source")
            seen_index.add(ix)
            file=(folder/raw_rel).resolve()
            if not file.is_file() or file.is_symlink() or not file.is_relative_to(folder.resolve()):
                raise ValueError("raw_response_path_invalid")
            raw=file.read_bytes()
            sha=digest(raw)
            live_row=live_by_url.get(url)
            if (live_row is None or sha!=item.get("source_sha256")
                or sha!=live_row.get("transport",{}).get("sha256")
                or item.get("archive_date")!=live_row.get("archive_date")):
                raise ValueError("raw_sha_or_notice_identity_does_not_match_two_sources")
            attempts=item.get("attempts")
            if (not isinstance(attempts,list) or not attempts
                or attempts[-1].get("status")!="PASS"
                or attempts[-1].get("http_status")!=200
                or attempts[-1].get("sha256")!=sha):
                raise ValueError("official_raw_byte_attempt_not_pass")
            match=re.search(r"charset\s*=\s*([A-Za-z0-9_-]+)",str(attempts[-1].get("content_type") or ""),re.I)
            encoding=match.group(1) if match else None
            page=detail.decode_response(SimpleNamespace(content=raw,encoding=encoding))
            body,selector=detail.extract_primary_article(BeautifulSoup(page,"html.parser"))
            if (not isinstance(body,str) or len(body)<25
                or digest(body.encode("utf-8"))!=item.get("article_body_sha256")
                or digest(body.encode("utf-8"))!=live_row.get("body_text_sha256")
                or selector!=item.get("article_selector")
                or selector!=live_row.get("article_source")):
                raise ValueError("independent_full_primary_body_sha_or_selector_not_bound")
            full_stop=parser.explicit_start(body)
            full_resume=parser.explicit_resume(body)
            text=str(live_row.get("semantic_sample") or "")
            excerpt_stop=parser.explicit_start(text)
            excerpt_resume=parser.explicit_resume(text)
            by_url[url]={
                "url":url,"source_sha256":sha,
                "full_body_sha256":digest(body.encode("utf-8")),
                "full_body_chars":len(body),
                "full_stop_date_candidates":full_stop,
                "full_resume_date_candidates":full_resume,
                "excerpt_stop_date_candidates":excerpt_stop,
                "excerpt_resume_date_candidates":excerpt_resume,
                "potentially_conditional_resume":bool(parser.CONDITIONAL_RESUME.search(body)),
                "intraday_notice":bool(parser.INTRADAY.search(body+" "+str(live_row.get("title") or ""))),
                "date_claims_not_realized":"NOT VERIFIED",
            }
    if len(by_url)!=TOTAL or len(seen_index)!=TOTAL or set(by_url)!=set(live_by_url):
        raise ValueError("all_1849_first_party_full_raw_source_denominator_not_covered")
    pairs=join.get("pairs")
    if not isinstance(pairs,list) or len(pairs)!=A_SHARES+B_SHARES:
        raise ValueError("incomplete_source_bound_equity_candidate_pairs")
    source_b=Counter(); a_rows=[]; new_stop=0; new_resume=0
    for pair in pairs:
        url=pair.get("official_url")
        row=by_url.get(url)
        if row is None or pair.get("raw_sha256")!=row["source_sha256"]:
            raise ValueError("dated_equity_candidate_unbound_to_full_raw_source")
        code=pair.get("equity_code_candidate")
        scope=pair.get("candidate_asset_class")
        if scope not in ("A_SHARE_CANDIDATE","B_SHARE_EXCLUDED"):
            raise ValueError("wrong_asset_class")
        source_b[scope]+=1
        if pair.get("qualified_daily_st_pit")!="NOT VERIFIED":
            raise ValueError("false_daily_qualification_in_dated_share_join")
        if scope=="B_SHARE_EXCLUDED":continue
        if code not in live_by_url[url].get("security_codes",[]):
            raise ValueError("A_share_candidate_not_in_full_primary_source")
        # A full-body candidate is still only a textual claim, regardless of
        # whether the excerpt truncated a later dated mention.
        stop=sorted(set(row["full_stop_date_candidates"]))
        resume=sorted(set(row["full_resume_date_candidates"]))
        extra_stops=sorted(set(stop)-set(row["excerpt_stop_date_candidates"]))
        extra_resumes=sorted(set(resume)-set(row["excerpt_resume_date_candidates"]))
        new_stop+=bool(extra_stops)
        new_resume+=bool(extra_resumes)
        a_rows.append({
            "official_url":url,"equity_code_candidate":code,
            "source_raw_sha256":row["source_sha256"],
            "full_article_body_sha256":row["full_body_sha256"],
            "full_body_chars":row["full_body_chars"],
            "full_stop_date_textual_candidates":stop,
            "full_resume_date_textual_candidates":resume,
            "previous_excerpt_missing_stop_dates":extra_stops,
            "previous_excerpt_missing_resume_dates":extra_resumes,
            "conditional_resume_unresolved":row["potentially_conditional_resume"],
            "intraday_not_equal_full_day":row["intraday_notice"],
            "actual_realized_stop_resume":"NOT VERIFIED",
            "asof_stock_issuer_lifecycle":"NOT VERIFIED",
            "daily_st_suspension_pit":"NOT VERIFIED",
        })
    if source_b!={"A_SHARE_CANDIDATE":A_SHARES,"B_SHARE_EXCLUDED":B_SHARES}:
        raise ValueError("A_B_class_denominator_drift")
    # Bounded aggregate output never contains full HTML; raw byte evidence remains
    # under the separate SHA-pinned first-party artifact, with URL+hash lineage.
    all_rows=list(by_url.values())
    count=Counter()
    for row in all_rows:
        if row["full_stop_date_candidates"]:count["source_notices_with_full_stop_date"]+=1
        if row["full_resume_date_candidates"]:count["source_notices_with_full_resume_date"]+=1
        if row["potentially_conditional_resume"]:count["notice_mentions_conditional_resume"]+=1
    return {
        "schema":"stock-szse-full-primary-body-dated-review-v1",
        "frozen_first_party_notice_denominator":TOTAL,
        "real_independently_reparsed_full_primary_bodies":TOTAL,
        "equity_A_candidate_pairs":A_SHARES,
        "excluded_equity_B_pairs":B_SHARES,
        "source_notice_full_text_counts":dict(sorted(count.items())),
        "A_candidate_pairs_with_dates_not_in_excerpt_stop":new_stop,
        "A_candidate_pairs_with_dates_not_in_excerpt_resume":new_resume,
        "A_share_full_body_candidates":sorted(a_rows,key=lambda x:(x["official_url"],x["equity_code_candidate"])),
        "adjudication":{
            "independent_hash_bound_full_article_body_reparse":"PASS",
            "dated_notice_claim_diagnostic":"PASS",
            "actual_effective_halt_resume":"NOT VERIFIED",
            "historic_issuer_listing_delisting_asof":"NOT VERIFIED",
            "full_SSE_SZSE_BSE_daily_ST_suspend":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }

def main():
    p=argparse.ArgumentParser()
    for arg in ("live","joined","raw_root","exact_raw_source_code","exact_dated_parser_code","out"):
        p.add_argument("--"+arg.replace("_","-"),dest=arg,type=Path,required=True)
    a=p.parse_args()
    live=json.loads(a.live.read_text(encoding="utf-8"))
    joined=json.loads(a.joined.read_text(encoding="utf-8"))
    detail=load_mod("pinned_raw_source_detail",a.exact_raw_source_code)
    parser=load_mod("pinned_date_semantics",a.exact_dated_parser_code)
    result=full_body_crosscheck(live,joined,a.raw_root,detail,parser)
    a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
       "full_bodies_reparsed":TOTAL,
       "A_share_pairs":A_SHARES,"B_share_excluded":B_SHARES,
       "full_stop_resume_counts":result["source_notice_full_text_counts"],
       "A_new_stop_dates_outside_excerpt":result["A_candidate_pairs_with_dates_not_in_excerpt_stop"],
       "A_new_resume_dates_outside_excerpt":result["A_candidate_pairs_with_dates_not_in_excerpt_resume"],
       "full_stock_st_daily_PIT":"NOT VERIFIED","final_gate":"FAIL",
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
