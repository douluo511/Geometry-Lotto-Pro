"""Hash/source-bound A-share candidate gate, never a daily suspension or ST state.

This is a deterministic read-only *evidence intake*. Securities master, as-of
listing dates, official effective events and exchange calendar are separate
mandatory authorities. A frozen official SZSE notice corpus can constrain the
research queue but cannot prove complete historical daily market states.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

HEX = re.compile(r"^[0-9a-f]{64}$")
STOCK_CODE = re.compile(r"^\d{6}$")
ASHARE_PREFIXES = ("000","001","002","003","300","301")
BSHARE_PREFIXES = ("200","201")
FROZEN_NOTICES = 1849


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _official_url(url: str) -> bool:
    try:
        obj = urlparse(url)
    except Exception:
        return False
    return obj.scheme == "https" and obj.netloc.lower() == "www.szse.cn" and (
        obj.path.startswith("/disclosure/notice/temp/") and obj.path.endswith(".html")
    ) and not obj.username and not obj.password and not obj.query and not obj.fragment


def _hash(value) -> bool:
    return isinstance(value,str) and HEX.fullmatch(value) is not None


def _code_type(code: str) -> str:
    if not STOCK_CODE.fullmatch(code):
        raise ValueError("invalid_stock_candidate_code")
    if code.startswith(ASHARE_PREFIXES):
        return "SZSE_A_SHARE_CANDIDATE"
    if code.startswith(BSHARE_PREFIXES):
        return "SZSE_B_SHARE_EXCLUDED_FROM_ASHARE_PIT"
    raise ValueError("non_equity_code_in_equity_binding")


def classify(input_obj: dict, *, frozen_expected=FROZEN_NOTICES) -> dict:
    if input_obj.get("schema") != "szse-effective-event-diagnostic-v1":
        raise ValueError("unrecognized_source_report_schema")
    if input_obj.get("source_frozen_denominator") != frozen_expected:
        raise ValueError("official_notice_denominator_changed")
    if any(input_obj.get(key) is None for key in (
        "source_archive_sha256","source_semantic_view_sha256","source_records_sha256"
    )) or not all(_hash(input_obj.get(k)) for k in (
        "source_archive_sha256","source_semantic_view_sha256","source_records_sha256"
    )):
        raise ValueError("missing_source_aggregate_hashes")
    rows = input_obj.get("rows")
    provided = input_obj.get("equity_candidate_bindings")
    if not isinstance(rows,list) or len(rows) != frozen_expected or not isinstance(provided,list):
        raise ValueError("incomplete_first_party_source_rows")
    scopes = Counter()
    by_pair = {}
    urls = set()
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("invalid_notice_row")
        url = row.get("official_url")
        if not isinstance(url,str) or not _official_url(url) or url in urls:
            raise ValueError("invalid_or_duplicate_official_notice_url")
        urls.add(url)
        raw_sha = row.get("official_response_sha256")
        excerpt_sha = row.get("semantic_excerpt_sha256")
        if not _hash(raw_sha) or not _hash(excerpt_sha):
            raise ValueError("official_notice_source_hash_missing")
        if not isinstance(row.get("archive_date"),str) or re.fullmatch(r"20\d{6}",row["archive_date"]) is None:
            raise ValueError("missing_archive_date_metadata")
        codes = row.get("equity_code_candidates")
        if not isinstance(codes,list) or codes != sorted(set(codes)):
            raise ValueError("unverified_or_duplicate_equity_candidates")
        if not isinstance(row.get("identity_candidates"),list):
            raise ValueError("source_security_codes_missing")
        if not set(codes).issubset(set(row["identity_candidates"])):
            raise ValueError("equity_code_not_in_official_notice")
        if row.get("instrument_qualification") != "NOT VERIFIED" or row.get("qualified_daily_st_or_suspension") != "NOT VERIFIED":
            raise ValueError("source_diagnostic_attempted_to_promote_daily_PIT")
        if not isinstance(row.get("instrument_scope"),str):
            raise ValueError("source_instrument_scope_missing")
        scopes[row["instrument_scope"]] += 1
        for code in codes:
            category = _code_type(code)
            pair = (url,code)
            if pair in by_pair:
                raise ValueError("duplicate_notice_security_pair")
            by_pair[pair] = {
                "official_url":url,
                "official_response_sha256":raw_sha,
                "semantic_excerpt_sha256":excerpt_sha,
                "archive_date_not_effective_date":row["archive_date"],
                "equity_code_candidate":code,
                "multi_instrument_notice":len(codes)+len(row.get("convertible_code_candidates") or [])>1,
                "actual_stock_lifecycle_qualified":"NOT VERIFIED",
                "actual_daily_suspension_qualified":"NOT VERIFIED",
                "security_kind":category,
            }
    declared_scopes = input_obj.get("instrument_scope_counts")
    if not isinstance(declared_scopes,dict) or dict(sorted(scopes.items())) != declared_scopes:
        raise ValueError("instrument_scope_partition_drift")
    if sum(scopes.values()) != frozen_expected:
        raise ValueError("source_notice_partition_lost")
    if len(by_pair) != input_obj.get("equity_notice_code_candidates"):
        raise ValueError("candidate_denominator_drift")
    counted_notices=sum(bool(row["equity_code_candidates"]) for row in rows)
    if counted_notices != input_obj.get("equity_notice_rows"):
        raise ValueError("equity_notice_row_denominator_drift")
    if len(provided)!=len(by_pair):
        raise ValueError("source_candidate_pair_count_changed")
    if len({(x.get("official_url"),x.get("equity_code_candidate")) for x in provided if isinstance(x,dict)})!=len(provided):
        raise ValueError("duplicated_source_candidate_pair")
    for raw in provided:
        if not isinstance(raw,dict):
            raise ValueError("malformed_equity_source_binding")
        pair = (raw.get("official_url"),raw.get("equity_code_candidate"))
        expected = by_pair.get(pair)
        if expected is None:
            raise ValueError("injected_equity_candidate_not_in_official_source")
        if any(raw.get(k)!=expected[k] for k in (
            "official_response_sha256","semantic_excerpt_sha256",
            "archive_date_not_effective_date","multi_instrument_notice",
            "actual_stock_lifecycle_qualified","actual_daily_suspension_qualified"
        )):
            raise ValueError("source_hash_or_provisional_state_mutated")

    a = sorted((row for row in by_pair.values() if row["security_kind"]=="SZSE_A_SHARE_CANDIDATE"),
               key=lambda row:(row["archive_date_not_effective_date"],row["official_url"],row["equity_code_candidate"]))
    b = sorted((row for row in by_pair.values() if row["security_kind"]=="SZSE_B_SHARE_EXCLUDED_FROM_ASHARE_PIT"),
               key=lambda row:(row["archive_date_not_effective_date"],row["official_url"],row["equity_code_candidate"]))
    # The actual production historical_pit.py validates SZSE A-share prefixes only.
    # These are SOURCE-LINKED CANDIDATES, not qualified equity lifecycle or
    # effective whole-day halt/resumption states. Do not write historical_st_pit.
    return {
        "schema":"szse-ashare-evidence-intake-v1",
        "source_frozen_denominator":frozen_expected,
        "source_aggregate_sha256":input_obj["source_records_sha256"],
        "source_archive_sha256":input_obj["source_archive_sha256"],
        "source_semantic_view_sha256":input_obj["source_semantic_view_sha256"],
        "source_notice_scope_counts":dict(sorted(scopes.items())),
        "equity_notice_rows":counted_notices,
        "equity_notice_code_candidates":len(by_pair),
        "szse_a_share_candidate_pairs":len(a),
        "szse_b_share_excluded_pairs":len(b),
        "a_share_candidates":a,
        "b_share_exclusion_ledger":b,
        "adjudication":{
            "official_notice_count":"PASS",
            "ashare_bshare_provisional_partition":"PASS",
            "stock_security_master_historical_identity":"NOT VERIFIED",
            "all_three_markets_historical_st_suspend_daily":"NOT VERIFIED",
            "confirmed_effective_stop_resume_intervals":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("input",type=Path)
    p.add_argument("--output",type=Path,default=Path("stock_szse_ashare_candidate_evidence.json"))
    args=p.parse_args()
    report=classify(json.loads(args.input.read_text(encoding="utf-8")))
    if (report["source_frozen_denominator"],report["equity_notice_rows"],
        report["equity_notice_code_candidates"],report["szse_a_share_candidate_pairs"],
        report["szse_b_share_excluded_pairs"])!=(1849,961,967,958,9):
        raise RuntimeError("frozen primary-authority A/B share denominator mismatch")
    args.output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "source_notices":1849,
        "equity_notice_rows":report["equity_notice_rows"],
        "source_bound_equity_pairs":report["equity_notice_code_candidates"],
        "szse_A_share_candidate_pairs":report["szse_a_share_candidate_pairs"],
        "B_share_excluded_from_A_share_PIT":report["szse_b_share_excluded_pairs"],
        "historical_daily_PIT":"NOT VERIFIED",
        "final_gate":"FAIL",
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
