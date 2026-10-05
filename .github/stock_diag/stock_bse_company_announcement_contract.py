from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
OUT = Path("stock_bse_company_announcement_contract.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockAI BSE contract validator"
NEED_FIELDS = [
    "companyCd","companyName","disclosureTitle","disclosurePostTitle",
    "destFilePath","publishDate","xxfcbj","destFilePath","fileExt","xxzrlx",
]
SAMPLES = [
    {
        "code": "920575",
        "keyword": "退市风险警示",
        "start": "2026-04-01",
        "end": "2026-06-30",
        "expected_title_tokens": ["退市风险警示"],
        "expected_date_prefix": "2026-04-29",
    },
    {
        "code": "920305",
        "keyword": "退市风险警示",
        "start": "2025-04-01",
        "end": "2026-06-30",
        "expected_title_tokens": ["退市风险警示"],
        "expected_date_prefix": "2025-",
    },
    {
        "code": "920023",
        "keyword": "退市风险警示",
        "start": "2025-04-01",
        "end": "2026-06-30",
        "expected_title_tokens": ["退市风险警示"],
        "expected_date_prefix": "2025-",
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_bse(url: str) -> bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="bse.cn" or host.endswith(".bse.cn")


def parse_jsonp(payload: str):
    text=payload.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        pass
    m=re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not m:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(m.group(1))


def find_records(obj):
    records=[]
    def walk(x):
        if isinstance(x, dict):
            keys=set(x)
            if {"companyCd","publishDate"} <= keys and (
                "disclosureTitle" in keys or "destFilePath" in keys
            ):
                records.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    # deterministic de-duplication
    unique={}
    for r in records:
        key=(str(r.get("companyCd")),str(r.get("publishDate")),
             str(r.get("disclosureTitle")),str(r.get("destFilePath")))
        unique[key]=r
    return [unique[k] for k in sorted(unique)]


def request_variant(session, label: str, method: str, params):
    kwargs={
        "headers":{
            "User-Agent":UA,
            "Accept":"application/javascript,application/json,text/plain,*/*",
            "Referer":"https://www.bse.cn/disclosure/announcement.html",
        },
        "timeout":(10,30),
        "allow_redirects":True,
    }
    if method=="GET":
        r=session.get(ENDPOINT,params=params,**kwargs)
    else:
        r=session.post(ENDPOINT,data=params,**kwargs)
    meta={
        "variant":label,
        "method":method,
        "status":r.status_code,
        "resolved_url":r.url,
        "content_type":r.headers.get("content-type"),
        "bytes":len(r.content),
        "sha256":sha256(r.content),
        "same_official_host":same_bse(r.url),
    }
    if r.status_code != 200 or not r.content or not same_bse(r.url):
        return None,meta
    try:
        obj=parse_jsonp(r.content.decode(r.encoding or "utf-8",errors="strict"))
        meta["parse"]="PASS"
        return obj,meta
    except Exception as exc:
        meta["parse"]="FAIL"
        meta["parse_error"]=f"{type(exc).__name__}: {exc}"
        meta["prefix"]=r.text[:300]
        return None,meta


def main():
    session=requests.Session()
    results=[]
    all_sample_pass=True

    for sample in SAMPLES:
        base={
            "callback":"stockAiBseCb",
            "disclosureType":"",
            "disclosureSubtype":"",
            "page":0,
            "companyCd":sample["code"],
            "isNewThree":1,
            "startTime":sample["start"],
            "endTime":sample["end"],
            "keyword":sample["keyword"],
            "hyType":"",
        }
        # The official BSE page passes xxfcbj:["2"] and needFields:H into
        # jQuery. Default jQuery serialization emits bracket-suffixed array
        # keys. Test that exact contract first; scalar/repeated variants are
        # controls only and cannot weaken any downstream gate.
        jquery_pairs=list(base.items()) + [("xxfcbj[]","2")] + [
            ("needFields[]",field) for field in NEED_FIELDS
        ]
        repeated_pairs=list(base.items()) + [("xxfcbj","2")] + [
            ("needFields",field) for field in NEED_FIELDS
        ]
        legacy={**base,"xxfcbj":"2","needFields":",".join(NEED_FIELDS)}
        request_variants=[
            ("official_jquery_brackets_post","POST",jquery_pairs),
            ("official_jquery_brackets_get","GET",jquery_pairs),
            ("repeated_keys_post","POST",repeated_pairs),
            ("legacy_scalar_post","POST",legacy),
        ]
        variants=[]
        winning=None
        for label,method,params in request_variants:
            obj,meta=request_variant(session,label,method,params)
            records=find_records(obj) if obj is not None else []
            exact=[r for r in records if str(r.get("companyCd","")).strip()==sample["code"]]
            matching=[]
            for r in exact:
                title=(str(r.get("disclosureTitle") or "")+str(r.get("disclosurePostTitle") or ""))
                date=str(r.get("publishDate") or "")
                path=str(r.get("destFilePath") or "")
                if (
                    all(tok in title for tok in sample["expected_title_tokens"])
                    and date.startswith(sample["expected_date_prefix"])
                    and path
                    and (path.startswith("/") or same_bse(path))
                ):
                    matching.append({
                        "companyCd":r.get("companyCd"),
                        "companyName":r.get("companyName"),
                        "title":title,
                        "publishDate":r.get("publishDate"),
                        "destFilePath":path,
                        "fileExt":r.get("fileExt"),
                        "xxzrlx":r.get("xxzrlx"),
                    })
            item={
                "transport":meta,
                "record_count":len(records),
                "exact_code_record_count":len(exact),
                "matching_count":len(matching),
                "matching_sample":matching[:10],
            }
            variants.append(item)
            if winning is None and matching:
                winning=item
        status="PASS" if winning is not None else "NOT VERIFIED"
        all_sample_pass=all_sample_pass and status=="PASS"
        results.append({"sample":sample,"status":status,"variants":variants})

    report={
        "schema":"stock-bse-company-announcement-contract-v2",
        "endpoint":ENDPOINT,
        "endpoint_discovered_from":{
            "pr":219,
            "artifact":11359927321,
            "script":"https://www.bse.cn/template/6/bluewise/_files/js/disclosure/list_company_2.min.js",
            "script_sha256":"bf39ce71871a21a785155f004a34c3b3f1c8eb412c568e3565c36f9eeadf0827",
        },
        "request_contract":{
            "source":"official BSE list_company_2.min.js",
            "official_ajax_type":"post",
            "official_data_type":"jsonp",
            "array_fields":["xxfcbj","needFields"],
            "array_encoding_under_test":"jquery bracket-suffixed keys",
            "no_gate_reduction":True,
        },
        "sample_results":results,
        "adjudication":{
            "bse_company_announcement_machine_contract":"SUPPORTED_SAMPLE" if all_sample_pass else "NOT VERIFIED",
            "bse_risk_warning_event_source":"SUPPORTED_SAMPLE" if all_sample_pass else "NOT VERIFIED",
            "bse_historical_st_pit":"NOT VERIFIED",
            "bse_historical_suspension_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":(
            "Known-sample query semantics only. Even PASS does not establish exhaustive event "
            "pagination, full BSE historical coverage, daily ST identity, suspension state, or PIT."
        ),
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "sample_statuses":[r["status"] for r in results],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
