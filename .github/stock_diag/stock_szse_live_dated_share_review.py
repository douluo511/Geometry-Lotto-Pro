"""Adjudicate one exact LIVE 1849 source and A-share/dated candidate evidence chain.

Read-only source-bound research queue. Never claim a realized stop/resume, ST,
daily PIT, historical equity identity or a production backtest PASS.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

TOTAL=1849
EQUITY_PAIRS=967
A=958
B=9

def sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def adjudicate(live:dict, dated:dict, share:dict, joined:dict) -> dict:
    lineage=live.get("source_lineage",{})
    if (live.get("schema")!="stock-szse-suspension-detail-corpus-v1"
        or len(live.get("records",[]))!=TOTAL
        or live.get("summary",{}).get("transport_pass")!=TOTAL
        or live.get("summary",{}).get("body_text_extracted")!=TOTAL
        or live.get("adjudication",{}).get("live_official_notice_primary_body")!="PASS"
        or live.get("adjudication",{}).get("final_gate")!="FAIL"
        or lineage.get("live_network_shard_count")!=13
        or lineage.get("live_records_sha256")!=sha(live["records"])
        or lineage.get("official_html_response_sha_changed_count")!=0
        or lineage.get("security_code_semantics_changed_count")!=0
        or lineage.get("daily_asof_claim")!="NOT VERIFIED"):
        raise ValueError("live_official_source_integrity_or_drift_not_qualified")
    if (dated.get("schema")!="szse-effective-event-diagnostic-v1"
        or share.get("schema")!="szse-ashare-evidence-intake-v1"
        or joined.get("schema")!="stock-szse-dated-ashare-claims-join-v1"):
        raise ValueError("candidate_lineage_schema_invalid")
    if (dated.get("source_frozen_denominator")!=TOTAL
        or share.get("source_frozen_denominator")!=TOTAL
        or joined.get("source_frozen_denominator")!=TOTAL
        or dated.get("source_records_sha256")!=lineage["live_records_sha256"]
        or share.get("source_aggregate_sha256")!=lineage["live_records_sha256"]
        or joined.get("source_aggregate_sha256")!=lineage["live_records_sha256"]
        or joined.get("dated_notice_input_sha256")!=sha(dated)
        or joined.get("share_candidate_input_sha256")!=sha(share)
        or joined.get("candidate_pair_ledger_sha256")!=sha(joined.get("pairs"))):
        raise ValueError("independently_recomputed_current_live_hash_lineage_mismatch")
    if (joined.get("total_equity_notice_pairs")!=EQUITY_PAIRS
        or joined.get("a_share_candidate_pairs")!=A
        or joined.get("b_share_exclusions")!=B
        or len(joined.get("pairs") or [])!=EQUITY_PAIRS):
        raise ValueError("current_live_equity_candidate_denominator_mismatch")
    if (dated.get("adjudication",{}).get("actual_resumption_state")!="NOT VERIFIED"
        or share.get("adjudication",{}).get("production_historical_st_pit")!="NOT VERIFIED"
        or joined.get("adjudication",{}).get("production_historical_st_pit")!="NOT VERIFIED"
        or joined.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("unearned_production_or_realized_state_qualification")
    refs={}
    for row in dated.get("rows") or []:
        url=row.get("official_url")
        if not isinstance(url,str) or url in refs:
            raise ValueError("duplicate_or_unverified_source_url")
        refs[url]=row
    if len(refs)!=TOTAL:
        raise ValueError("dated_source_coverage_gap")
    pairs=joined["pairs"]
    if len({(r.get("official_url"),r.get("equity_code_candidate")) for r in pairs})!=EQUITY_PAIRS:
        raise ValueError("duplicate_equity_notice_pair")
    classes=Counter()
    viable={}
    review=[]
    def date_valid(day):
        try:
            return isinstance(day,str) and date.fromisoformat(day).isoformat()==day
        except ValueError:
            return False
    for pair in pairs:
        if not isinstance(pair,dict):
            raise ValueError("malformed_pair")
        url=pair.get("official_url")
        row=refs.get(url)
        if not row:
            raise ValueError("notice_identity_not_in_current_live_date_corpus")
        if (pair.get("raw_sha256")!=row.get("official_response_sha256")
            or pair.get("semantic_excerpt_sha256")!=row.get("semantic_excerpt_sha256")):
            raise ValueError("notice_raw_or_excerpt_sha_mismatch")
        code=pair.get("equity_code_candidate")
        cls=pair.get("candidate_asset_class")
        if cls=="A_SHARE_CANDIDATE":
            if not isinstance(code,str) or not code.startswith(("000","001","002","003","300","301")):
                raise ValueError("A_share_prefix_injection")
        elif cls=="B_SHARE_EXCLUDED":
            if not isinstance(code,str) or not code.startswith(("200","201")):
                raise ValueError("B_share_exclusion_misbound")
        else:
            raise ValueError("unknown_security_asset_class")
        if (pair.get("actual_equity_asof_master")!="NOT VERIFIED"
            or pair.get("realized_stock_halt")!="NOT VERIFIED"
            or pair.get("realized_resumption")!="NOT VERIFIED"
            or pair.get("qualified_daily_st_pit")!="NOT VERIFIED"):
            raise ValueError("realized_or_daily_PIT_falsely_qualified")
        stop=pair.get("notice_stop_date_candidates")
        resume=pair.get("notice_resume_date_candidates")
        if not isinstance(stop,list) or not isinstance(resume,list) or any(
            not date_valid(day) for day in stop+resume
        ):
            raise ValueError("invalid_effective_date_candidate")
        if pair.get("candidate_claim_scope") not in (
            "SINGLE_CODE_NOTICE_DIAGNOSTIC","MULTI_OR_UNQUALIFIED_NOTICE_REVIEW"
        ):
            raise ValueError("unknown_dated_notice_scope")
        if pair["candidate_claim_scope"]=="MULTI_OR_UNQUALIFIED_NOTICE_REVIEW" and (stop or resume):
            raise ValueError("unqualified_multi_code_date_promoted")
        if (pair.get("intraday_only_or_unresolved") is False
            and pair.get("candidate_claim_scope")!="SINGLE_CODE_NOTICE_DIAGNOSTIC"):
            raise ValueError("misleading_intraday_or_multi_scope")
        classes[cls]+=1
        kind="CANDIDATE_ONLY_NEEDS_PRIMARY_STATE_AND_ASOF_MASTER"
        if cls!="A_SHARE_CANDIDATE":
            kind="B_SHARE_OUTSIDE_PRODUCT_A_SHARE_SCOPE"
        elif pair.get("intraday_only_or_unresolved"):
            kind="INTRADAY_OR_UNRESOLVED_NOT_FULL_DAY"
        elif len(stop)==1 and not resume:
            kind="UNCONFIRMED_EXPLICIT_STOP_DATE"
        elif len(resume)==1 and not stop:
            kind="UNCONFIRMED_EXPLICIT_RESUME_DATE"
        elif stop or resume:
            kind="CONFLICTING_CANDIDATE_EVENTS"
        else:
            kind="NO_EFFECTIVE_DAY_CANDIDATE"
        viable[kind]=viable.get(kind,0)+1
        if kind in ("UNCONFIRMED_EXPLICIT_STOP_DATE","UNCONFIRMED_EXPLICIT_RESUME_DATE"):
            review.append({
                "official_url":url,"equity_code_candidate":code,
                "first_party_raw_sha256":pair["raw_sha256"],
                "first_party_semantic_excerpt_sha256":pair["semantic_excerpt_sha256"],
                "notice_stop_date_candidates":stop,
                "notice_resume_date_candidates":resume,
                "verified_daily_status":"NOT VERIFIED",
                "verified_asof_equity_master":"NOT VERIFIED",
                "actual_realized_transition":"NOT VERIFIED",
            })
    if classes!={"A_SHARE_CANDIDATE":A,"B_SHARE_EXCLUDED":B}:
        raise ValueError("incorrect_current_live_equity_B_share_denominator")
    return {
        "schema":"stock-szse-live-dated-ashare-review-v1",
        "input_live_source_sha256":lineage["live_records_sha256"],
        "input_dated_source_sha256":sha(dated),
        "input_share_source_sha256":sha(share),
        "input_joined_pairs_sha256":sha(pairs),
        "source_first_party_notices":TOTAL,
        "A_share_pairs":A,"excluded_B_share_pairs":B,
        "notice_pair_classification_counts":dict(sorted(viable.items())),
        "human_review_event_candidates":sorted(review,key=lambda x:(x["official_url"],x["equity_code_candidate"])),
        "adjudication":{
            "current_live_official_source_provenance":"PASS",
            "current_live_source_ashare_dated_join":"PASS",
            "dated_effective_actions_realized":"NOT VERIFIED",
            "historical_equity_lifecycle":"NOT VERIFIED",
            "full_SSE_SZSE_BSE_day_security_ST_suspend_PIT":"NOT VERIFIED",
            "stock_advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }


def main():
    import argparse
    p=argparse.ArgumentParser()
    for key in ("live","dated","share","joined","out"):
        p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    load=lambda p: json.loads(p.read_text(encoding="utf-8"))
    result=adjudicate(load(a.live),load(a.dated),load(a.share),load(a.joined))
    a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "real_network_notice_pages":TOTAL,
        "A_share_pairs":A,"B_share_exclusions":B,
        "candidate_classifications":result["notice_pair_classification_counts"],
        "human_review_event_candidates":len(result["human_review_event_candidates"]),
        "historical_full_PIT":"NOT VERIFIED","final_gate":"FAIL",
    },ensure_ascii=False,sort_keys=True))
if __name__=="__main__":
    main()
