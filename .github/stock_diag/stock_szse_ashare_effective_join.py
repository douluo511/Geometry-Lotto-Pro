"""Exact-source join of official A-share notice candidates and dated claims.

Never infer historical issuer identity, actual trading state or daily PIT from a
matched document. Even 1849-source network PASS does not establish those facts.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

HEX=re.compile(r"^[a-f0-9]{64}$")
DATE=re.compile(r"^20\d\d-\d\d-\d\d$")


def canonical(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()


def sha(x):
    return isinstance(x,str) and bool(HEX.fullmatch(x))


ALLOWED_KINDS = {
    "SOURCE_NOT_VERIFIED", "INTRADAY_NOT_FULL_DAY",
    "PROSPECTIVE_NOT_REALIZED", "CONTINUATION_NOT_NEW_STOP",
    "EXPLICIT_STOP_CANDIDATE_ONLY", "EXPLICIT_RESUME_CANDIDATE_ONLY",
    "MULTIPLE_TRANSITIONS_UNRESOLVED", "EFFECTIVE_DATE_UNRESOLVED",
}
SINGLE_CODE_DATED_KINDS = {
    "EXPLICIT_STOP_CANDIDATE_ONLY", "EXPLICIT_RESUME_CANDIDATE_ONLY",
}


def checked_archive_day(value):
    """A source publishing date, never a substitute for a trading effective date."""
    if not isinstance(value, str) or re.fullmatch(r"20\\d{6}", value) is None:
        raise ValueError("source archive date absent or malformed")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("impossible source archive date") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("noncanonical source archive date")
    return value


def checked_candidate_days(values):
    if not isinstance(values, list) or len(set(map(str, values))) != len(values):
        raise ValueError("duplicate or malformed effective date candidate list")
    for value in values:
        if not isinstance(value, str) or DATE.fullmatch(value) is None:
            raise ValueError("malformed explicit notice date claim")
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("noncanonical effective date candidate")
        except ValueError as exc:
            raise ValueError("calendar-impossible effective date candidate") from exc
    return values


def join(share:dict, dated:dict, *, expected_notices=1849, expected_a=958, expected_b=9):
    if (share.get("schema")!="szse-ashare-evidence-intake-v1"
            or dated.get("schema")!="szse-effective-event-diagnostic-v1"):
        raise ValueError("unqualified source schema")
    a=share.get("a_share_candidates")
    b=share.get("b_share_exclusion_ledger")
    rows=dated.get("rows")
    if (not isinstance(a,list) or not isinstance(b,list) or not isinstance(rows,list)
            or len(rows)!=expected_notices or len(a)!=expected_a or len(b)!=expected_b
            or share.get("source_frozen_denominator")!=expected_notices
            or dated.get("source_frozen_denominator")!=expected_notices
            or share.get("szse_a_share_candidate_pairs")!=expected_a
            or share.get("szse_b_share_excluded_pairs")!=expected_b
            or share.get("equity_notice_code_candidates")!=expected_a+expected_b):
        raise ValueError("source/issuer pair denominator mismatch")
    hash_fields=(("source_archive_sha256","source_archive_sha256"),
                 ("source_semantic_view_sha256","source_semantic_view_sha256"),
                 ("source_aggregate_sha256","source_records_sha256"))
    for sk,dk in hash_fields:
        if not sha(share.get(sk)) or share[sk]!=dated.get(dk):
            raise ValueError("independent source corpus hash lineage mismatch")
    if (dated.get("adjudication",{}).get("final_gate")!="FAIL"
            or share.get("adjudication",{}).get("production_historical_st_pit")!="NOT VERIFIED"):
        raise ValueError("diagnostic incorrectly qualified a production gate")
    row_map={}
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("invalid notice row")
        url=row.get("official_url")
        u=urlparse(str(url))
        if (u.scheme!="https" or u.hostname!="www.szse.cn" or not
                u.path.startswith("/disclosure/notice/temp/") or u.query or u.fragment
                or u.username or u.password or not sha(row.get("official_response_sha256"))
                or not sha(row.get("semantic_excerpt_sha256")) or url in row_map):
            raise ValueError("duplicated/untrusted notice source provenance")
        if row.get("qualified_daily_st_or_suspension")!="NOT VERIFIED" or row.get("qualified_actual_resumption")!="NOT VERIFIED":
            raise ValueError("daily-source evidence illegally promoted")
        # Missing evidence cannot be silently treated as an empty error list.
        missing = row.get("missing_evidence")
        if not isinstance(missing, list) or any(not isinstance(e, str) or not e for e in missing):
            raise ValueError("unverifiable missing-evidence field")
        if row.get("classification") not in ALLOWED_KINDS:
            raise ValueError("unknown notice classification")
        checked_archive_day(row.get("archive_date"))
        checked_candidate_days(row.get("explicit_effective_stop_date_candidates"))
        checked_candidate_days(row.get("explicit_effective_resume_date_candidates"))
        row_map[url]=row
    out=[]
    seen=set()
    for kind,group in (("A_SHARE_CANDIDATE",a),("B_SHARE_EXCLUDED",b)):
        for pair in group:
            if not isinstance(pair,dict):
                raise ValueError("invalid share notice pair")
            url,code=pair.get("official_url"),pair.get("equity_code_candidate")
            if (url,code) in seen or not isinstance(code,str) or not re.fullmatch(r"\d{6}",code):
                raise ValueError("duplicate or invalid notice-equity candidate")
            seen.add((url,code))
            if kind=="A_SHARE_CANDIDATE" and not code.startswith(("000","001","002","003","300","301")):
                raise ValueError("B or non-equity code would enter A-share research")
            if kind=="B_SHARE_EXCLUDED" and not code.startswith(("200","201")):
                raise ValueError("A-share mistakenly excluded")
            row=row_map.get(url)
            if row is None or pair.get("official_response_sha256")!=row["official_response_sha256"] or pair.get("semantic_excerpt_sha256")!=row["semantic_excerpt_sha256"]:
                raise ValueError("source or excerpt digest does not match independent dated notice")
            if pair.get("archive_date_not_effective_date") != row["archive_date"]:
                raise ValueError("notice and share-candidate publication-date provenance mismatch")
            if (pair.get("actual_stock_lifecycle_qualified")!="NOT VERIFIED"
                    or pair.get("actual_daily_suspension_qualified")!="NOT VERIFIED"):
                raise ValueError("share candidate falsely qualified")
            # Multi-code and conflicting notices remain unresolved, even if a
            # parser happens to produce a plausible stop or resume date.
            unresolved=row["missing_evidence"]
            cls=row["classification"]
            # No effective-day claim survives source gaps, mixed stop/resume,
            # intraday-only notices, or notices outside the dated candidate class.
            source_bound=(not unresolved and row.get("code")==code
                          and cls in SINGLE_CODE_DATED_KINDS
                          and row.get("intraday") is False)
            stop=row["explicit_effective_stop_date_candidates"]
            resume=row["explicit_effective_resume_date_candidates"]
            candidate_scope=("SINGLE_CODE_NOTICE_DIAGNOSTIC" if source_bound
                             else "MULTI_OR_UNQUALIFIED_NOTICE_REVIEW")
            out.append({
                "official_url":url,"equity_code_candidate":code,"candidate_asset_class":kind,
                "raw_sha256":row["official_response_sha256"],
                "semantic_excerpt_sha256":row["semantic_excerpt_sha256"],
                "notice_classification":row.get("classification"),
                "candidate_claim_scope":candidate_scope,
                "notice_stop_date_candidates":stop if source_bound and cls=="EXPLICIT_STOP_CANDIDATE_ONLY" else [],
                "notice_resume_date_candidates":resume if source_bound and cls=="EXPLICIT_RESUME_CANDIDATE_ONLY" else [],
                "notice_date_metadata_not_effective_date":pair.get("archive_date_not_effective_date"),
                "intraday_only_or_unresolved":bool(row.get("intraday")) or not source_bound,
                "actual_equity_asof_master":"NOT VERIFIED",
                "realized_stock_halt":"NOT VERIFIED",
                "realized_resumption":"NOT VERIFIED",
                "qualified_daily_st_pit":"NOT VERIFIED",
            })
    if len(seen)!=expected_a+expected_b:
        raise ValueError("equity candidate pair dropped")
    out.sort(key=lambda x:(x["official_url"],x["equity_code_candidate"]))
    return {
        "schema":"stock-szse-dated-ashare-claims-join-v1",
        "source_frozen_denominator":expected_notices,
        "source_aggregate_sha256":share["source_aggregate_sha256"],
        "dated_notice_input_sha256":canonical(dated),
        "share_candidate_input_sha256":canonical(share),
        "total_equity_notice_pairs":len(out),
        "a_share_candidate_pairs":expected_a,
        "b_share_exclusions":expected_b,
        "candidate_pair_ledger_sha256":canonical(out),
        "pairs":out,
        "adjudication":{
            "historical_source_join_and_hash_consistency":"PASS",
            "actual_stock_lifecycle_asof":"NOT VERIFIED",
            "effective_stop_resume_state":"NOT VERIFIED",
            "day_security_st_suspension_sse_szse_bse":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--share",type=Path,required=True)
    p.add_argument("--dated",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("stock_szse_ashare_dated_candidate_join.json"))
    a=p.parse_args()
    result=join(json.loads(a.share.read_text(encoding="utf-8")),json.loads(a.dated.read_text(encoding="utf-8")))
    a.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("source_frozen_denominator","total_equity_notice_pairs","a_share_candidate_pairs","b_share_exclusions","candidate_pair_ledger_sha256","adjudication")},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
