"""Independent source-byte witness: cross-run SZSE 1849 raw HTML SHA and body SHA.

Both sources must be prior terminal first-party SUCCESS at distinct exact heads.
This does NOT qualify an actual stock halt, resumed state, or daily/ST PIT.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse
HEX=re.compile(r"^[0-9a-f]{64}$")
TOTAL=1849
A=958
B=9

def canonical(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def verify(live:dict,raw:dict,dated:dict,review:dict):
    if (live.get("schema")!="stock-szse-suspension-detail-corpus-v1"
        or raw.get("schema")!="stock-szse-1849-fresh-raw-source-merge-v1"
        or raw.get("source_frozen_denominator")!=TOTAL
        or raw.get("shards_verified")!=19
        or raw.get("raw_response_sha256_unique")!=TOTAL
        or live.get("source_archive",{}).get("event_rows")!=TOTAL
        or live.get("summary",{}).get("body_text_extracted")!=TOTAL
        or raw.get("adjudication",{}).get("full_1849_official_HTTP_and_scoped_primary_body")!="PASS"
        or live.get("adjudication",{}).get("live_official_notice_primary_body")!="PASS"):
        raise ValueError("independent_source_witness_denominator_or_raw_gate_missing")
    live_records=live.get("records")
    evidence=raw.get("evidence")
    if not isinstance(live_records,list) or len(live_records)!=TOTAL or not isinstance(evidence,list) or len(evidence)!=TOTAL:
        raise ValueError("one_capture_missing_1849_raw_records")
    if raw.get("source_records_sha256")!=canonical(evidence):
        raise ValueError("second_capture_raw_aggregate_hash_changed")
    a={}
    b={}
    for row in live_records:
        u=row.get("url")
        if not isinstance(u,str) or u in a: raise ValueError("live_source_duplicate_url")
        tr=row.get("transport") or {}
        if (row.get("status")!="PASS" or row.get("article_body_status")!="PASS"
            or tr.get("status")!="PASS" or tr.get("http_status")!=200
            or tr.get("same_official_host") is not True):
            raise ValueError("unverified_current_live_response")
        a[u]=row
    for row in evidence:
        u=row.get("url")
        if not isinstance(u,str) or u in b: raise ValueError("second_raw_capture_duplicate_url")
        if not isinstance(row.get("index"),int): raise ValueError("raw_index_missing")
        b[u]=row
    if a.keys()!=b.keys() or len(a)!=TOTAL:
        raise ValueError("independent_raw_and_current_live_source_sets_differ")
    response_drift=[]
    article_drift=[]
    for url,cur in a.items():
        old=b[url]
        if cur.get("archive_date")!=old.get("archive_date"):
            raise ValueError("archive_date_changed_between_independent_captures")
        if cur["transport"].get("sha256")!=old.get("raw_sha256"):
            response_drift.append(url)
        if cur.get("body_text_sha256")!=old.get("body_sha256"):
            article_drift.append(url)
        if cur.get("article_source")!=old.get("article_selector"):
            article_drift.append(url)
    if response_drift or article_drift:
        raise ValueError(f"independently_reparsed_source_sha_disagrees:{len(response_drift)}:{len(article_drift)}")
    if (dated.get("source_records_sha256")!=canonical(live_records)
        or dated.get("source_frozen_denominator")!=TOTAL
        or review.get("schema")!="stock-szse-live-dated-ashare-review-v1"
        or review.get("source_first_party_notices")!=TOTAL
        or review.get("A_share_pairs")!=A
        or review.get("excluded_B_share_pairs")!=B
        or review.get("input_live_source_sha256")!=canonical(live_records)
        or review.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("date_and_equity_candidate_research_not_from_exact_live_source")
    candidates=review.get("human_review_event_candidates")
    if not isinstance(candidates,list): raise ValueError("no_current_live_event_candidates")
    controls=[]
    unique=set()
    for candidate in candidates:
        if not isinstance(candidate,dict):raise ValueError("malformed_effective_date_candidate")
        url=candidate.get("official_url");code=candidate.get("equity_code_candidate")
        if url not in a or not isinstance(code,str) or not code.startswith(("000","001","002","003","300","301")):
            raise ValueError("non_Ashare_or_non_official_candidate")
        key=(url,code)
        if key in unique:raise ValueError("duplicate_candidate_equity_source")
        unique.add(key)
        if (candidate.get("first_party_raw_sha256")!=a[url]["transport"]["sha256"]
            or candidate.get("first_party_raw_sha256")!=b[url]["raw_sha256"]
            or candidate.get("verified_daily_status")!="NOT VERIFIED"
            or candidate.get("verified_asof_equity_master")!="NOT VERIFIED"
            or candidate.get("actual_realized_transition")!="NOT VERIFIED"):
            raise ValueError("candidate_witness_unbound_or_falsely_production_qualified")
        controls.append({
            "official_url":url,"equity_code_candidate":code,
            "current_live_source_raw_sha256":a[url]["transport"]["sha256"],
            "independent_reparsed_raw_sha256":b[url]["raw_sha256"],
            "independently_reparsed_body_sha256":b[url]["body_sha256"],
            "primary_claim_candidate_only":candidate.get("notice_stop_date_candidates") or candidate.get("notice_resume_date_candidates"),
            "actual_effective_state":"NOT VERIFIED",
            "historical_daily_ST_suspension_state":"NOT VERIFIED",
        })
    return {
      "schema":"stock-szse-1849-independent-raw-dated-witness-v1",
      "first_party_urls_verified_between_two_distinct_runs":TOTAL,
      "current_live_records_sha256":canonical(live_records),
      "independent_raw_witness_records_sha256":canonical(evidence),
      "raw_bytes_cross_run_sha_mismatches":len(response_drift),
      "article_body_cross_run_sha_mismatches":len(article_drift),
      "A_share_candidate_pairs":A,"B_share_exclusions":B,
      "notice_stop_resume_date_review_candidates":len(controls),
      "witnesses":sorted(controls,key=lambda x:(x["official_url"],x["equity_code_candidate"])),
      "adjudication":{
        "two_real_official_1849_http_raw_bytes_and_primary_body":"PASS",
        "candidate_claim_provenance_witness":"PASS",
        "historical_equity_lifecycle":"NOT VERIFIED",
        "realized_effective_stop_resume":"NOT VERIFIED",
        "three_market_full_day_security_ST_PIT":"NOT VERIFIED",
        "advanced_business":"NOT VERIFIED",
        "final_gate":"FAIL",
      }
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    for k in ("live","raw","dated","review","out"):
        p.add_argument("--"+k,type=Path,required=True)
    a=p.parse_args()
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    obj=verify(read(a.live),read(a.raw),read(a.dated),read(a.review))
    a.out.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
       "independent_source_witnesses":obj["first_party_urls_verified_between_two_distinct_runs"],
       "two_run_html_sha_mismatches":obj["raw_bytes_cross_run_sha_mismatches"],
       "two_run_primary_body_sha_mismatches":obj["article_body_cross_run_sha_mismatches"],
       "event_candidates_cross_witnessed":obj["notice_stop_resume_date_review_candidates"],
       "actual_historical_daily_ST_PIT":"NOT VERIFIED",
       "final_gate":"FAIL",
    },sort_keys=True))
if __name__=="__main__":main()
