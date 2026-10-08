"""Cross-check *current live 1849 SZSE primary documents* against frozen source URLs.

Output is only notice and A/B-share candidate provenance, never qualified
historical daily ST, issuer listing master, effective halt or realized resume.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

SHARDS=13
TOTAL=1849
ARCHIVE_SHA="589fddec93bb26e05a067824dbca352129e2dc5db3c2f0027abd3a1d54ffad6e"
HEX=re.compile(r"^[0-9a-f]{64}$")
NAMED_DOM={".news-detail-con #desContent",".news-detail-con .des-content"}


def canonical(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()


def live_record_ok(row):
    tr=row.get("transport") if isinstance(row.get("transport"),dict) else {}
    source=row.get("url")
    if not isinstance(source,str):
        return False
    p=urlparse(source)
    actual=urlparse(str(tr.get("resolved_url") or ""))
    sample=row.get("semantic_sample")
    return (
        row.get("status")=="PASS"
        and p.scheme=="https" and p.hostname=="www.szse.cn"
        and p.path.startswith("/disclosure/notice/temp/") and p.path.endswith(".html")
        and not p.query and not p.fragment
        and tr.get("status")=="PASS" and tr.get("http_status")==200
        and tr.get("same_official_host") is True
        and actual.scheme=="https" and actual.hostname in ("szse.cn","www.szse.cn")
        and isinstance(tr.get("sha256"),str) and HEX.fullmatch(tr["sha256"])
        and row.get("article_body_status")=="PASS" and row.get("article_source") in NAMED_DOM
        and isinstance(row.get("body_text_sha256"),str) and HEX.fullmatch(row["body_text_sha256"])
        and int(row.get("body_text_chars") or 0)>=25
        and isinstance(sample,str)
        and canonical_sample(sample)==row.get("semantic_sample_sha256")
        and isinstance(row.get("security_codes"),list)
        and all(re.fullmatch(r"\d{6}",code) for code in row["security_codes"])
    )


def canonical_sample(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def rebind(frozen, docs, *, expected_total=TOTAL):
    if frozen.get("schema")!="stock-szse-suspension-detail-corpus-v1":
        raise ValueError("frozen first-party schema missing")
    if frozen.get("source_archive",{}).get("canonical_sha256")!=ARCHIVE_SHA:
        raise ValueError("official archive link hash changed")
    if frozen["source_archive"].get("event_rows")!=expected_total:
        raise ValueError("frozen denominator drift")
    original=frozen.get("records")
    if not isinstance(original,list) or len(original)!=expected_total:
        raise ValueError("frozen source rows incomplete")
    old={}
    for row in original:
        key=(row.get("archive_date"),row.get("url"))
        if key in old:
            raise ValueError("duplicate frozen archive source row")
        old[key]=row
    if not isinstance(docs,dict) or len(docs)!=SHARDS:
        raise ValueError("missing live shard")
    live=[]
    ordered_links=sorted(old,key=lambda x:(x[0],x[1]))
    for i in range(SHARDS):
        d=docs.get(i)
        if not isinstance(d,dict):
            raise ValueError(f"missing_shard_{i}")
        if (d.get("schema"),d.get("shard_total"),d.get("shard_index"),
            d.get("frozen_total"),d.get("source_archive_sha256"))!=(
            "szse-1849-shard-live-v1",SHARDS,i,expected_total,ARCHIVE_SHA
        ):
            raise ValueError(f"wrong_shard_contract_{i}")
        rows=d.get("records")
        if not isinstance(rows,list) or len(rows)!=d.get("selected") or len(rows)!=d.get("pass") or d.get("nonpass")!=0:
            raise ValueError(f"incomplete_live_shard_{i}")
        expected_shard_keys=set(ordered_links[i::SHARDS])
        actual_shard_keys={(row.get("archive_date"),row.get("url")) for row in rows if isinstance(row,dict)}
        if len(rows)!=len(actual_shard_keys) or actual_shard_keys!=expected_shard_keys:
            raise ValueError(f"wrong_current_live_shard_assignment_{i}")
        if d.get("adjudication",{}).get("daily_st_suspension_pit")!="NOT VERIFIED" or d.get("adjudication",{}).get("final_gate")!="FAIL":
            raise ValueError("unearned_daily_pit_promotion")
        live.extend(rows)

    keys={(row.get("archive_date"),row.get("url")) for row in live if isinstance(row,dict)}
    if len(live)!=expected_total or len(keys)!=expected_total or keys!=set(old):
        raise ValueError("full_live_source_url_denominator_mismatch")
    live.sort(key=lambda x:(x["archive_date"],x["url"]))
    sha_changed=[]
    code_changed=[]
    for row in live:
        if not live_record_ok(row):
            raise ValueError("unqualified_live_official_response_or_named_body")
        k=(row["archive_date"],row["url"])
        before=old[k]
        if row["transport"]["sha256"]!=before.get("transport",{}).get("sha256"):
            sha_changed.append({"url":row["url"],"prior_response_sha256":before.get("transport",{}).get("sha256"),"live_response_sha256":row["transport"]["sha256"]})
        if sorted(row["security_codes"])!=sorted(before.get("security_codes") or []):
            code_changed.append({"url":row["url"],"prior_codes":before.get("security_codes"),"live_codes":row["security_codes"]})
    semantic_view=[{
        "archive_date":row["archive_date"],
        "url":row["url"],"title":row.get("title"),
        "security_codes":row.get("security_codes"),
        "stop_terms":row.get("stop_terms"),
        "resume_terms":row.get("resume_terms"),
        "body_text_sha256":row.get("body_text_sha256"),
        "article_body_status":row.get("article_body_status"),
        "article_source":row.get("article_source"),
    } for row in live]
    # Existing stock_szse_effective_event_audit and A/B intake consume this
    # compatibility record. Each of its 1849 notice rows comes from the
    # distinct exact-head LIVE shard run, not from old notice text.
    report={
        "schema":"stock-szse-suspension-detail-corpus-v1",
        "source_archive":frozen["source_archive"],
        "summary":{
            "selected_detail_pages":expected_total,
            "transport_pass":expected_total,
            "transport_nonpass":0,
            "body_text_extracted":expected_total,
            "semantic_view_sha256":canonical(semantic_view),
        },
        "records":live,
        "source_lineage":{
            "live_network_shard_count":SHARDS,
            "source_url_registry_sha256":ARCHIVE_SHA,
            "live_records_sha256":canonical(live),
            "prior_frozen_records_sha256":canonical(original),
            "official_html_response_sha_changed_count":len(sha_changed),
            "security_code_semantics_changed_count":len(code_changed),
            "official_html_response_sha_changes":sha_changed,
            "security_code_semantics_changes":code_changed,
            "daily_asof_claim":"NOT VERIFIED",
        },
        "adjudication":{
            "live_official_notice_primary_body":"PASS",
            "cross_snapshot_semantics":"PASS" if not code_changed else "NOT VERIFIED",
            "independent_historical_listing_delisting_lifecycle":"NOT VERIFIED",
            "three_market_ST_suspension_daily_PIT":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }
    return report


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--shards",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("stock_szse_current_live_rebound_corpus.json"))
    args=p.parse_args()
    frozen=json.loads(args.original.read_text(encoding="utf-8"))
    docs={}
    for i in range(SHARDS):
        src=args.shards/f"shard-{i:02d}.json"
        if not src.is_file():
            raise RuntimeError(f"missing official live shard file {i}")
        docs[i]=json.loads(src.read_text(encoding="utf-8"))
    result=rebind(frozen,docs)
    args.out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "live_first_party_notice_rows":1849,
        "live_response_sha_changed":result["source_lineage"]["official_html_response_sha_changed_count"],
        "live_security_code_changed":result["source_lineage"]["security_code_semantics_changed_count"],
        "live_primary_body":result["adjudication"]["live_official_notice_primary_body"],
        "historical_daily_PIT":result["adjudication"]["three_market_ST_suspension_daily_PIT"],
    },ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
