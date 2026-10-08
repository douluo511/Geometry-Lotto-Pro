"""Reject inherited dated notice claims when new first-party raw bytes drift.

A matched URL alone is not matching source evidence. Matching raw bytes still
does not verify effective market state or historical security identity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

SHA=re.compile(r"^[0-9a-f]{64}$")

def digest_json(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()

def compare(old:dict,new:dict, *, expected=1849,expected_shards=19):
    rows=old.get("rows"); receipts=new.get("evidence")
    if (old.get("schema")!="szse-effective-event-diagnostic-v1" or
        new.get("schema")!="stock-szse-1849-fresh-raw-source-merge-v1" or
        old.get("source_frozen_denominator")!=expected or
        new.get("source_frozen_denominator")!=expected or
        new.get("shards_verified")!=expected_shards or
        new.get("raw_response_sha256_unique")!=expected or
        not isinstance(rows,list) or not isinstance(receipts,list) or
        len(rows)!=expected or len(receipts)!=expected):
        raise ValueError("frozen source/shard denominator inconsistent")
    if (new.get("adjudication",{}).get("full_1849_official_HTTP_and_scoped_primary_body")!="PASS" or
        new.get("adjudication",{}).get("final_gate")!="FAIL" or
        old.get("adjudication",{}).get("final_gate")!="FAIL"):
        raise ValueError("invalid current-source or final authority")
    if old.get("source_archive_sha256")!="589fddec93bb26e05a067824dbca352129e2dc5db3c2f0027abd3a1d54ffad6e":
        raise ValueError("different frozen official URL authority")
    before={}; after={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError("bad historical notice row")
        url=row.get("official_url")
        sha=row.get("official_response_sha256")
        if not isinstance(url,str) or url in before or not isinstance(sha,str) or not SHA.fullmatch(sha):
            raise ValueError("historical notice hash or URL missing/duplicate")
        before[url]=(sha,row.get("archive_date"))
    for row in receipts:
        if not isinstance(row,dict):raise ValueError("bad current source row")
        url=row.get("url"); sha=row.get("raw_sha256")
        if not isinstance(url,str) or url in after or not isinstance(sha,str) or not SHA.fullmatch(sha):
            raise ValueError("fresh source hash or URL missing/duplicate")
        after[url]=(sha,row.get("archive_date"))
    if set(before)!=set(after):
        raise ValueError("frozen official URL identities differ between source heads")
    drift=[{"url":u,"old_raw_sha256":before[u][0],"new_raw_sha256":after[u][0],
            "old_archive_date":before[u][1],"new_archive_date":after[u][1]}
           for u in sorted(before) if before[u]!=after[u]]
    report={
        "schema":"stock-szse-historical-vs-fresh-source-byte-drift-v1",
        "frozen_denominator":expected,"fresh_shards":expected_shards,
        "original_dated_notice_report_sha256":digest_json(old),
        "current_raw_source_report_sha256":digest_json(new),
        "records_checked":expected,
        "matched_receipts":expected-len(drift),
        "drifted_receipts":len(drift),
        "drift":drift,
        "adjudication":{
            "source_byte_equivalence":"PASS" if not drift else "NOT VERIFIED",
            "older_semantic_claims_applicable_to_current_raw":"SOURCE_BYTES_MATCH_ONLY" if not drift else "NOT VERIFIED",
            "actual_equity_lifecycle_asof":"NOT VERIFIED",
            "effective_stop_resume_actual":"NOT VERIFIED",
            "daily_st_suspend_sse_szse_bse":"NOT VERIFIED",
            "production_historical_st_pit":"NOT VERIFIED",
            "final_gate":"FAIL",
        }
    }
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--historical",type=Path,required=True)
    parser.add_argument("--fresh",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=Path("szse_source_drift.json"))
    a=parser.parse_args()
    rep=compare(json.loads(a.historical.read_text(encoding="utf-8")),
                json.loads(a.fresh.read_text(encoding="utf-8")))
    a.out.write_text(json.dumps(rep,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"records_checked":rep["records_checked"],"matched":rep["matched_receipts"],
                      "drifted":rep["drifted_receipts"],"adjudication":rep["adjudication"]},
                      sort_keys=True))
    return 0 if rep["drifted_receipts"]==0 else 2

if __name__=="__main__":
    raise SystemExit(main())
