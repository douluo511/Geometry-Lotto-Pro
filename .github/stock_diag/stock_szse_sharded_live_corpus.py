"""Shard 1849 official SZSE notice pages across bounded independent CI workers.

This is a first-party *transport/body* revalidation, NOT daily ST/suspension
state; no missing page may be synthesized from the prior successful snapshot.
"""
from __future__ import annotations
import argparse
import concurrent.futures
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlparse

HERE=Path(__file__).resolve().parent
DETAIL=HERE/"stock_szse_suspension_detail_corpus.py"
FULL=1849
SHARDS=13
OFFICIAL="589fddec93bb26e05a067824dbca352129e2dc5db3c2f0027abd3a1d54ffad6e"
HEX=re.compile(r"^[0-9a-f]{64}$")

def _module():
    spec=importlib.util.spec_from_file_location("szse_primary_detail",DETAIL)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _official(url):
    p=urlparse(url)
    return (p.scheme=="https" and p.netloc=="www.szse.cn"
        and p.path.startswith("/disclosure/notice/temp/") and p.path.endswith(".html")
        and not p.query and not p.fragment)

def frozen_links(obj):
    if obj.get("schema")!="stock-szse-suspension-detail-corpus-v1":
        raise ValueError("wrong frozen source schema")
    if obj.get("source_archive",{}).get("event_rows")!=FULL:
        raise ValueError("official frozen denominator mutated")
    if obj["source_archive"].get("canonical_sha256")!=OFFICIAL:
        raise ValueError("official source link archive SHA mutated")
    if obj.get("summary",{}).get("transport_pass")!=FULL:
        raise ValueError("frozen source lacked complete first-party transport")
    if obj.get("summary",{}).get("body_text_extracted")!=FULL:
        raise ValueError("frozen source lacked complete first-party body")
    records=obj.get("records")
    if not isinstance(records,list) or len(records)!=FULL:
        raise ValueError("incomplete frozen rows")
    urls=set()
    links=[]
    for row in records:
        url=row.get("url")
        day=row.get("archive_date")
        if not isinstance(url,str) or not _official(url) or url in urls:
            raise ValueError("bad or duplicate official source URL")
        if not isinstance(day,str) or re.fullmatch(r"20\d{6}",day) is None:
            raise ValueError("source archive date metadata")
        if row.get("status")!="PASS" or not HEX.fullmatch(row.get("transport",{}).get("sha256") or ""):
            raise ValueError("frozen source not primary response-bound")
        urls.add(url)
        links.append({"date":day,"url":url,"identity_source":row.get("archive_identity_source")})
    links.sort(key=lambda x:(x["date"],x["url"]))
    if len(links)!=FULL:
        raise ValueError("wrong link count")
    return links

def select(links,index,total=SHARDS):
    if not isinstance(index,int) or not 0<=index<total or total!=SHARDS:
        raise ValueError("bad shard assignment")
    return [item for i,item in enumerate(links) if i%total==index]

def positive(row,detail):
    t=row.get("transport") or {}
    return (
        row.get("status")=="PASS" and t.get("status")=="PASS"
        and _official(row.get("url") or "")
        and isinstance(t.get("sha256"),str) and HEX.fullmatch(t["sha256"])
        and row.get("article_body_status")=="PASS"
        and isinstance(row.get("article_source"),str)
        and bool(row["article_source"])
        and int(row.get("body_text_chars") or 0)>=25
        and isinstance(row.get("body_text_sha256"),str)
        and HEX.fullmatch(row["body_text_sha256"])
        and bool(row.get("title"))
    )

def fetch_shard(input_obj,index,out,fetcher=None):
    links=frozen_links(input_obj)
    part=select(links,index)
    if not part:
        raise RuntimeError("empty shard")
    source=_module() if fetcher is None else None
    get=fetcher or source.fetch_one
    # Exactly 2 concurrent first-party requests per worker; never bypass
    # response, DOM or hash validation, retries bounded by the source helper.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(get,part))
    expected={(item["date"],item["url"]) for item in part}
    actual={(item.get("archive_date"),item.get("url")) for item in results}
    if len(expected)!=len(part) or expected!=actual or len(results)!=len(actual):
        raise RuntimeError("shard input/output coverage mismatch")
    ok=sum(positive(x,None) for x in results)
    payload={
        "schema":"szse-1849-shard-live-v1",
        "source_archive_sha256":OFFICIAL,
        "shard_index":index,"shard_total":SHARDS,
        "frozen_total":FULL,
        "selected":len(part),"pass":ok,"nonpass":len(part)-ok,
        "records":sorted(results,key=lambda x:(x["archive_date"],x["url"])),
        "adjudication":{
            "source_body":"PASS" if ok==len(part) else "NOT VERIFIED",
            "daily_st_suspension_pit":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }
    Path(out).write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"shard":index,"selected":len(part),"pass":ok,"nonpass":len(part)-ok},sort_keys=True))
    return 0 if ok==len(part) else 2

def aggregate(frozen,source_dir,out):
    links=frozen_links(frozen)
    all_rows=[]
    errors=[]
    for i in range(SHARDS):
        path=Path(source_dir)/f"shard-{i:02d}.json"
        if not path.is_file():
            errors.append(f"missing_shard:{i}")
            continue
        doc=json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema")!="szse-1849-shard-live-v1" or doc.get("shard_index")!=i or doc.get("shard_total")!=SHARDS:
            errors.append(f"bad_shard_header:{i}")
            continue
        if doc.get("source_archive_sha256")!=OFFICIAL or doc.get("frozen_total")!=FULL:
            errors.append(f"unbound_source_shard:{i}")
            continue
        rows=doc.get("records")
        if not isinstance(rows,list):
            errors.append(f"not_rows:{i}")
            continue
        expected={(x["date"],x["url"]) for x in select(links,i)}
        got={(x.get("archive_date"),x.get("url")) for x in rows if isinstance(x,dict)}
        if len(rows)!=len(expected) or len(got)!=len(rows) or expected!=got:
            errors.append(f"shard_coverage_mismatch:{i}")
            continue
        valid=sum(positive(x,None) for x in rows)
        if doc.get("selected")!=len(expected) or doc.get("pass")!=valid or doc.get("nonpass")!=len(rows)-valid:
            errors.append(f"shard_count_mismatch:{i}")
            continue
        if doc.get("adjudication",{}).get("daily_st_suspension_pit")!="NOT VERIFIED" or doc.get("adjudication",{}).get("final_gate")!="FAIL":
            errors.append(f"false_promotion:{i}")
            continue
        all_rows.extend(rows)
    all_rows.sort(key=lambda x:(x["archive_date"],x["url"]))
    expected_all={(x["date"],x["url"]) for x in links}
    actual_all={(x["archive_date"],x["url"]) for x in all_rows}
    if len(all_rows)!=FULL or len(actual_all)!=FULL or actual_all!=expected_all:
        errors.append("global_frozen_denominator_or_url_coverage_incomplete")
    passed=sum(positive(x,None) for x in all_rows)
    status="PASS" if not errors and passed==FULL else "NOT VERIFIED"
    body_sha=hashlib.sha256(json.dumps(all_rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
    report={
        "schema":"szse-1849-sharded-live-aggregate-v1",
        "source_archive_sha256":OFFICIAL,
        "full_frozen_denominator":FULL,
        "observed_records":len(all_rows),
        "live_primary_body_pass":passed,
        "not_verified":max(0,FULL-passed),
        "errors":errors,
        "live_records_sha256":body_sha,
        "adjudication":{
            "full_official_page_and_primary_body":status,
            "effective_event_daily_state":"NOT VERIFIED",
            "three_market_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "final_gate":"FAIL",
        },
    }
    Path(out).write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"full_official_page_and_primary_body":status,
       "live_primary_body_pass":passed,"frozen_denominator":FULL,"errors":errors},sort_keys=True))
    return 0 if status=="PASS" else 2

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--frozen",required=True,type=Path)
    p.add_argument("--shard-index",type=int)
    p.add_argument("--source-dir",type=Path)
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    obj=json.loads(args.frozen.read_text(encoding="utf-8"))
    if args.shard_index is not None and args.source_dir is None:
        return fetch_shard(obj,args.shard_index,args.out)
    if args.shard_index is None and args.source_dir is not None:
        return aggregate(obj,args.source_dir,args.out)
    raise SystemExit("choose exactly one of --shard-index or --source-dir")

if __name__=="__main__":
    raise SystemExit(main())
