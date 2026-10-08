"""Fail-closed, source-bound diagnostics of SZSE suspension effective-event claims.

Do not convert this output into historical_st_pit.json or infer daily market state.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

SHA = re.compile(r"^[0-9a-f]{64}$")
DATE_STOP = re.compile(
    r"(?P<year>20\d\d)年(?P<month>0?[1-9]|1[0-2])月"
    r"(?P<day>0?[1-9]|[12]\d|3[01])日"
    r"(?P<context>.{0,32}?)"
    r"(?:开市起|交易日起|起|开始)(?:.{0,14}?)(?:临时)?停牌"
)
INTRADAY = re.compile(r"盘中|[上下]午\d{1,2}时|(?:\d{1,2}时\d{1,2}分)|(?:\d{1,2}:\d{2})")
PROSPECTIVE = re.compile(r"拟.{0,40}停牌|计划.{0,40}停牌|预计.{0,40}停牌")
CONTINUING = re.compile(r"继续停牌|仍将停牌|继续实施停牌")
NOT_EFFECTIVE_CONTEXT = re.compile(r"发布|披露|明年|未来|决定|是否|拟|预计|计划|可能|待|公告后")
CONDITIONAL_RESUME = re.compile(r"待.{0,80}?(?:复牌|恢复交易)|(?:披露|公告|完成|申请).{0,40}后.{0,15}复牌")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def explicit_start(text: str):
    """Return only an effective-date candidate explicitly tied to stop phrasing."""
    results = []
    for match in DATE_STOP.finditer(text):
        near = text[max(0, match.start()-24):match.end()]
        if PROSPECTIVE.search(near) or CONTINUING.search(near) or NOT_EFFECTIVE_CONTEXT.search(match['context']):
            continue
        try:
            day = date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError:
            continue
        results.append(day.isoformat())
    return sorted(set(results))


EQUITY_PREFIXES = ("000","001","002","003","200","201","300","301")
CONVERTIBLE_PREFIXES = ("123","127","128")

def instrument_scope(row, source_valid):
    """Partition all notices without removing them from the frozen denominator."""
    codes=row.get("security_codes")
    if not source_valid or not isinstance(codes,list) or any(
        not isinstance(c,str) or not re.fullmatch(r"\d{6}",c) for c in codes
    ):
        return "SOURCE_OR_IDENTITY_UNVERIFIED",[],[]
    codes=sorted(set(codes))
    equities=sorted(c for c in codes if c.startswith(EQUITY_PREFIXES))
    converts=sorted(c for c in codes if c.startswith(CONVERTIBLE_PREFIXES))
    unknown=sorted(set(codes)-set(equities)-set(converts))
    title=str(row.get("title") or "")
    sample=str(row.get("semantic_sample") or "")
    if unknown: category="UNRECOGNIZED_SECURITY_CODE"
    elif equities and converts: category="MIXED_EQUITY_AND_CONVERTIBLE_NOTICE"
    elif len(equities)>1: category="MULTI_CLASS_EQUITY_NOTICE"
    elif len(equities)==1: category="SINGLE_EQUITY_CODE_NOTICE"
    elif converts:
        category=("CONVERTIBLE_BOND_NOTICE" if (
            "转债" in title or "转债" in sample or "可转换公司债券" in sample or "该债券" in sample
        ) else "UNVERIFIED_CONVERTIBLE_CONTEXT")
    elif not codes and "基金" in title: category="FUND_NOTICE"
    elif not codes and ("该债券" in sample or "上市债券" in sample
        or ("国开" in title and re.search(r"(?<!\d)108\d{3}(?!\d)",sample))):
        category="OTHER_BOND_NOTICE"
    else: category="ASSET_TYPE_NOT_VERIFIED"
    # A scope label is not a historically qualified stock identity or daily state.
    return category,equities,converts


def classify(row: dict) -> dict:
    url = str(row.get("url") or "")
    transport = row.get("transport") if isinstance(row.get("transport"), dict) else {}
    raw_sha = str(transport.get("sha256") or "")
    sample = row.get("semantic_sample")
    errors = []
    if (urlparse(url).hostname or "").lower() not in ("szse.cn", "www.szse.cn"):
        errors.append("official_host")
    if row.get("status") != "PASS" or transport.get("status") != "PASS":
        errors.append("source_transport")
    if not SHA.fullmatch(raw_sha):
        errors.append("source_sha256")
    if row.get("article_body_status") != "PASS" or not row.get("article_source"):
        errors.append("primary_article")
    if not isinstance(sample, str) or not sample:
        errors.append("primary_excerpt")
    elif row.get("semantic_sample_sha256") != digest(sample):
        errors.append("excerpt_hash")
    codes = row.get("security_codes")
    if not isinstance(codes, list) or any(not isinstance(v, str) for v in codes):
        errors.append("identity_format")
        codes = []
    codes = sorted(set(codes))
    if len(codes) != 1:
        errors.append("unambiguous_instrument_identity")

    title = str(row.get("title") or "")
    valid_sample = sample if isinstance(sample, str) and not errors else ""
    intraday = bool(INTRADAY.search(title + valid_sample)) if valid_sample else False
    future = bool(PROSPECTIVE.search(valid_sample)) if valid_sample else False
    continuing = bool(CONTINUING.search(valid_sample)) if valid_sample else False
    conditional_resume = bool(CONDITIONAL_RESUME.search(valid_sample)) if valid_sample else False
    candidates = explicit_start(valid_sample) if valid_sample else []
    scope,equity_codes,bond_codes=instrument_scope(row,not(set(errors)-{"unambiguous_instrument_identity"}))
    if not valid_sample:
        kind = "SOURCE_NOT_VERIFIED"
    elif intraday:
        kind = "INTRADAY_NOT_FULL_DAY"
    elif future:
        kind = "PROSPECTIVE_NOT_REALIZED"
    elif continuing:
        kind = "CONTINUATION_NOT_NEW_STOP"
    elif len(candidates) != 1:
        kind = "EFFECTIVE_DATE_UNRESOLVED"
    else:
        kind = "EXPLICIT_STOP_CANDIDATE_ONLY"

    return {
        "archive_date": row.get("archive_date"),
        "official_url": url,
        "official_response_sha256": raw_sha or None,
        "primary_article_selector": row.get("article_source"),
        "semantic_excerpt_sha256": row.get("semantic_sample_sha256"),
        "code": codes[0] if len(codes) == 1 else None,
        "identity_candidates": codes,
        "classification": kind,
        "explicit_effective_stop_date_candidates": candidates,
        "intraday": intraday,
        "prospective_stop": future,
        "continuing_stop": continuing,
        "conditional_resumption": conditional_resume,
        "missing_evidence": sorted(set(errors)),
        "instrument_scope": scope,
        "equity_code_candidates": equity_codes,
        "convertible_code_candidates": bond_codes,
        "instrument_qualification": "NOT VERIFIED",
        # Even a literal date & identity is a candidate, never a qualified daily state.
        "qualified_daily_st_or_suspension": "NOT VERIFIED",
        "qualified_actual_resumption": "NOT VERIFIED",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("stock_szse_effective_event_audit.json"))
    args = parser.parse_args()
    obj = json.loads(args.source.read_text(encoding="utf-8"))
    if obj.get("schema") != "stock-szse-suspension-detail-corpus-v1":
        raise RuntimeError("unexpected source schema")
    frozen = int(obj["source_archive"]["event_rows"])
    if frozen != 1849:
        raise RuntimeError(f"frozen official denominator changed: {frozen}")
    records = obj.get("records")
    if not isinstance(records, list) or len(records) != frozen:
        raise RuntimeError("source coverage denominator not complete")
    keys = [(row.get("archive_date"), row.get("url")) for row in records]
    if len(set(keys)) != frozen:
        raise RuntimeError("duplicate first-party source record")
    if obj["summary"].get("selected_detail_pages") != frozen:
        raise RuntimeError("summary/source count mismatch")
    audit = [classify(row) for row in records]
    counts = dict(sorted(Counter(row["classification"] for row in audit).items()))
    evidence_bound = sum(1 for row in audit if not row["missing_evidence"])
    scopes=dict(sorted(Counter(row["instrument_scope"] for row in audit).items()))
    equity_notice_rows=sum(bool(row["equity_code_candidates"]) for row in audit)
    equity_notice_code_candidates=sum(len(row["equity_code_candidates"]) for row in audit)
    equity_candidate_bindings=[
        {
            "official_url":row["official_url"],
            "official_response_sha256":row["official_response_sha256"],
            "semantic_excerpt_sha256":row["semantic_excerpt_sha256"],
            "archive_date_not_effective_date":row["archive_date"],
            "equity_code_candidate":code,
            "multi_instrument_notice":len(row["equity_code_candidates"])+len(row["convertible_code_candidates"])>1,
            "actual_stock_lifecycle_qualified":"NOT VERIFIED",
            "actual_daily_suspension_qualified":"NOT VERIFIED",
        }
        for row in audit for code in row["equity_code_candidates"]
    ]
    if len(equity_candidate_bindings)!=equity_notice_code_candidates:
        raise RuntimeError("equity candidate count mismatch")

    if sum(scopes.values())!=frozen: raise RuntimeError("instrument scope lost source records")
    report = {
        "schema": "szse-effective-event-diagnostic-v1",
        "source_archive_sha256": obj["source_archive"].get("canonical_sha256"),
        "source_semantic_view_sha256": obj["summary"].get("semantic_view_sha256"),
        "source_frozen_denominator": frozen,
        "source_records_sha256": digest(json.dumps(records,sort_keys=True,ensure_ascii=False,separators=(",",":"))),
        "classification_counts": counts,
        "instrument_scope_counts": scopes,
        "equity_notice_rows": equity_notice_rows,
        "equity_notice_code_candidates": equity_notice_code_candidates,
        "equity_candidate_bindings": equity_candidate_bindings,
        "unambiguously_identified_and_source_bound": evidence_bound,
        "rows": audit,
        "adjudication": {
            "source_record_denominator": "PASS",
            "diagnostic_classification": "PASS",
            "stock_instrument_lifecycle_qualified": "NOT VERIFIED",
            "effective_dates_complete": "NOT VERIFIED",
            "actual_full_day_suspension": "NOT VERIFIED",
            "actual_resumption_state": "NOT VERIFIED",
            "historical_daily_st_suspension_pit_sse_szse_bse": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "Only a source-bound notice-level diagnostic, never a daily state. "
            "No archive posting-day inference. No conditional resume promotion. "
            "Intraday notices cannot be converted into all-day trading suspension. "
            "No missing record can be synthesized as a normal trading day."
        ),
    }
    args.out.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "denominator": frozen, "source_and_identity_bound": evidence_bound,
        "classification_counts": counts, "instrument_scope_counts": scopes,
        "equity_notice_rows": equity_notice_rows,
        "equity_notice_code_candidates": equity_notice_code_candidates,
        "adjudication": report["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
