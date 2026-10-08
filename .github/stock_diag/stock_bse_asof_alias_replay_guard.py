"""BSE current 248 code aliases: source-native, historically fail-closed as-of replay.

An Oct-2026 code mapping is NOT a historical as-of company universe.
The official footnote says original Select-tier listing dates are carried into
the table. Neither those dates nor a 920xxx prefix proves BSE membership in
2020, the 920-code effective date, or a day's actual trading state.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re

BSE_OPEN = date(2021, 11, 15)
FROZEN_COUNT=248
PRE_OPEN_COUNT=68
SOURCE_URL="https://www.bse.cn/service/code_mapping.html"
FOOTNOTE="注：由全国股转系统原精选层平移进入北交所的上市公司，上表中上市日期字段为其在原精选层的挂牌日期。"
QUALIFIED={"NOT VERIFIED","NOT_A_BSE_MARKET_DAY"}
QUERY_DAYS=("2020-01-02","2021-11-14","2021-11-15","2022-01-04","2024-04-01","2026-10-08")
HEX64=re.compile(r"^[a-f0-9]{64}$")

def canonical(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()

def source_module(path):
    spec=importlib.util.spec_from_file_location("official_bse_current_alias",path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def reject_false_asof(report:dict, raw:bytes, source) -> dict:
    if not isinstance(raw,bytes) or not raw:
        raise ValueError("first_party_original_HTML_bytes_required")
    if (report.get("schema")!="stock-bse-current-code-alias-diagnostic-v1"
        or report.get("source")!=SOURCE_URL
        or report.get("actual_http_receipt")!="PASS"
        or report.get("raw_sha256")!=hashlib.sha256(raw).hexdigest()):
        raise ValueError("BSE_current_source_bytes_not_hash_bound")
    attempt=report.get("attempts")
    if not isinstance(attempt,list) or not attempt:
        raise ValueError("no_recorded_official_HTTP_receipt")
    receipts=[x for x in attempt if x.get("status")=="PASS"]
    if len(receipts)!=1 or receipts[0].get("status_code")!=200:
        raise ValueError("actual_BSE_HTTPS_200_response_not_proven")
    success=receipts[0]
    if (success.get("sha256")!=report["raw_sha256"]
        or success.get("raw_bytes")!=len(raw)
        or not source._official(success.get("final_url") or "")):
        raise ValueError("source_redirect_bytes_or_authenticity_inconsistent")
    first_party=source.parse(raw,success.get("content_type") or "")
    observed=report.get("observed")
    if not isinstance(observed,dict) or first_party!=observed:
        raise ValueError("normalized_rows_changed_without_raw_HTML")
    rows=observed.get("rows")
    if (not isinstance(rows,list)
        or observed.get("rows_count")!=FROZEN_COUNT
        or len(rows)!=FROZEN_COUNT
        or observed.get("pre_BSE_original_listing_count")!=PRE_OPEN_COUNT
        or observed.get("official_date_column_qualification_note")!=FOOTNOTE):
        raise ValueError("current_mapping_denominator_or_native_footnote_drift")
    stamped=report.get("retrieved_at_utc")
    try:
        retrieval=datetime.fromisoformat(stamped.replace("Z","+00:00"))
        if retrieval.tzinfo is None:
            raise ValueError("report_observation_time_zone_missing")
        # A historical/as-of source claim must be tied to the successful
        # first-party HTTP attempt's own recorded clock instant, not a
        # separately mutable report field. Equivalent UTC offsets are valid.
        actual_receipt_raw=success.get("at_utc")
        actual_receipt=datetime.fromisoformat(actual_receipt_raw.replace("Z","+00:00"))
        if actual_receipt.tzinfo is None:
            raise ValueError("successful_HTTP_receipt_time_zone_missing")
        if retrieval.astimezone(timezone.utc)!=actual_receipt.astimezone(timezone.utc):
            raise ValueError("asof_report_timestamp_not_bound_to_successful_HTTP_receipt")
        observed_day=actual_receipt.astimezone(timezone.utc).date()
    except (AttributeError,ValueError,TypeError) as exc:
        raise ValueError("snapshot_observation_or_primary_receipt_time_invalid") from exc
    old_codes=set();new_codes=set();historical=[]
    for idx,row in enumerate(rows,1):
        if not isinstance(row,dict):
            raise ValueError("unparseable_current_first_party_alias_row")
        old,new,symbol=row.get("old_code"),row.get("new_code"),row.get("symbol")
        if (not isinstance(old,str) or re.fullmatch(r"\d{6}",old) is None
            or not isinstance(new,str) or re.fullmatch(r"920\d{3}",new) is None
            or not isinstance(symbol,str) or not symbol
            or row.get("row_order")!=idx or old in old_codes or new in new_codes):
            raise ValueError("alias_code_or_unique_row_identity_drift")
        old_codes.add(old);new_codes.add(new)
        try:
            original_day=date.fromisoformat(row["source_listed_date_not_BSE_effective"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError("invalid_original_tier_listing_date") from exc
        if (original_day>observed_day
            or row.get("pre_BSE_market_open")!=(original_day<BSE_OPEN)
            or row.get("BSE_asof_old_or_new_code_validity")!="NOT VERIFIED"
            or row.get("share_class_and_issuer_lifecycle")!="NOT VERIFIED"):
            raise ValueError("anachronistic_or_promoted_original_listing_date")
        # This is an OBSERVED CURRENT mapping, not evidence of earlier
        # existence or historical old↔new code effectiveness.
        for raw_day in QUERY_DAYS:
            q=date.fromisoformat(raw_day)
            # Before Nov 15 2021 there is no BSE market, irrespective of the
            # original NEEQ Selected-tier挂牌 date printed in today's page.
            status="NOT_A_BSE_MARKET_DAY" if q<BSE_OPEN else "NOT VERIFIED"
            historical.append({
                "source_observed_as_of_utc":stamped,
                "source_raw_sha256":report["raw_sha256"],
                "issuer_name_in_current_mapping":symbol,
                "legacy_NEEQ_code":old,"present_mapping_920_code":new,
                "historical_day_query":raw_day,
                "source_initial_tier_listing_not_BSE_date":original_day.isoformat(),
                "historical_BSE_listing_and_code_alias_state":status,
                "asof_issuer_master_independent_source":"NOT VERIFIED",
                "historical_symbol_code_effective_day":"NOT VERIFIED",
                "actual_daily_ST_and_suspension_state":"NOT VERIFIED",
                "qualified_historical_PIT":"NOT VERIFIED",
            })
    if len(historical)!=FROZEN_COUNT*len(QUERY_DAYS):
        raise ValueError("historical_slice_denominator_missing")
    c=Counter(x["historical_BSE_listing_and_code_alias_state"] for x in historical)
    if (set(c).difference(QUALIFIED)
        or c.get("NOT_A_BSE_MARKET_DAY")!=2*FROZEN_COUNT
        or c.get("NOT VERIFIED")!=(len(QUERY_DAYS)-2)*FROZEN_COUNT):
        raise ValueError("unsupported_historical_asof_status_promoted")
    return {
        "schema":"stock-bse-current-248-asof-failclosed-v1",
        "current_first_party_url":SOURCE_URL,
        "current_first_party_raw_sha256":report["raw_sha256"],
        "source_observed_at_utc":stamped,
        "first_party_current_alias_rows":FROZEN_COUNT,
        "old_selected_tier_listing_before_BSE_open":PRE_OPEN_COUNT,
        "historical_asof_queries_per_alias":len(QUERY_DAYS),
        "historical_status_counts":dict(sorted(c.items())),
        "asof_slice_sha256":canonical(historical),
        "source_checked_issuer_alias_slices":historical,
        "adjudication":{
            "official_current_alias_raw_schema_and_248_count":"PASS",
            "market_pre_open_exclusion_no_future_920_alias":"PASS",
            "BSE_historical_effective_920_code_alias":"NOT VERIFIED",
            "BSE_historical_native_SecurityType_1_asof":"NOT VERIFIED",
            "SSE_SZSE_BSE_full_historical_ST_suspend_PIT":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }

def main():
    p=argparse.ArgumentParser()
    for k in ("input","raw","source_code","output"):
        p.add_argument("--"+k.replace("_","-"),dest=k,type=Path,required=True)
    a=p.parse_args()
    result=reject_false_asof(
        json.loads(a.input.read_text(encoding="utf-8")),
        a.raw.read_bytes(),
        source_module(a.source_code),
    )
    a.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "first_party_current_alias_rows":result["first_party_current_alias_rows"],
        "original_tier_dates_before_BSE_market_open":result["old_selected_tier_listing_before_BSE_open"],
        "asof_query_states":result["historical_status_counts"],
        "historical_PIT":"NOT VERIFIED",
        "final_gate":"FAIL",
    },sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
