"""Official BSE current code-mapping intake, NEVER historical identity proof.

The BSE code-mapping page includes old NEEQ codes and initial listing dates,
some BEFORE the BSE opened 2021-11-15. A present-day 920xxx mapping cannot
justify substituting 920xxx into historical records or upgrading NEEQ to BSE.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

URL = "https://www.bse.cn/service/code_mapping.html"
BSE_OPEN = date(2021, 11, 15)
MAX_BYTES = 3_000_000


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _official(url: str) -> bool:
    p=urlparse(url)
    return (p.scheme=="https" and p.hostname in ("www.bse.cn","bse.cn")
            and p.port is None and not p.username and not p.password
            and p.path=="/service/code_mapping.html" and not p.query and not p.fragment)


def _date(raw: str) -> date:
    s=raw.strip().replace("-","/")
    m=re.fullmatch(r"(20\d{2})/(\d{1,2})/(\d{1,2})",s)
    if not m:
        raise ValueError("malformed official code map listing date")
    try:
        return date(int(m[1]),int(m[2]),int(m[3]))
    except ValueError as exc:
        raise ValueError("impossible original listing date") from exc


def _decode(raw:bytes, content_type:str) -> str:
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError("empty or oversized official HTML")
    try:
        return raw.decode("utf-8",errors="strict")
    except UnicodeDecodeError as exc:
        xml=re.search(rb"charset\s*=\s*['\"]?\s*([A-Za-z0-9_-]+)",raw[:8192],re.I)
        h=re.search(r"charset\s*=\s*['\"]?\s*([A-Za-z0-9_-]+)",content_type,re.I)
        labels=[xml.group(1).decode("ascii").lower() if xml else "",
                h.group(1).lower() if h else ""]
        if not any(x in ("gbk","gb2312","gb18030","cp936") for x in labels):
            raise ValueError("untrusted charset on non-UTF8 source") from exc
        try:
            return raw.decode("gb18030",errors="strict")
        except UnicodeDecodeError as exc2:
            raise ValueError("invalid declared GB bytes") from exc2


def parse(raw:bytes,content_type:str="text/html") -> dict:
    soup=BeautifulSoup(_decode(raw,content_type),"html.parser")
    table_candidates=[]
    for table in soup.find_all("table"):
        trs=table.find_all("tr")
        if not trs:
            continue
        cols=["".join(cell.stripped_strings) for cell in trs[0].find_all(["td","th"])]
        if cols[:5]==["序号","证券简称","上市日期","旧代码","新代码"]:
            table_candidates.append(table)
    if len(table_candidates)!=1:
        raise ValueError("missing or duplicated official code-mapping header/table")
    rows=[]
    old_codes=set();new_codes=set()
    native_footnotes=[]
    for tr in table_candidates[0].find_all("tr")[1:]:
        cols=["".join(cell.stripped_strings) for cell in tr.find_all(["td","th"])]
        if not cols:
            continue
        if len(cols)==1 and cols[0].startswith("注："):
            native_footnotes.append(cols[0])
            continue
        if len(cols)!=5:
            raise ValueError(f"malformed official code mapping row {len(rows)+1}; columns={len(cols)}, sample={cols[:6]!r}")
        i=len(rows)+1
        order,symbol,listing_raw,old,new=cols
        if not order.isdecimal() or int(order)!=i or not symbol:
            raise ValueError("non-contiguous official table ordinal or missing issuer")
        if not re.fullmatch(r"\d{6}",old) or not re.fullmatch(r"920\d{3}",new):
            raise ValueError("invalid legacy/new BSE alias code")
        if old in old_codes or new in new_codes:
            raise ValueError("duplicate legacy or new alias")
        old_codes.add(old);new_codes.add(new)
        listed=_date(listing_raw)
        rows.append({
            "row_order":i,"symbol":symbol,"old_code":old,"new_code":new,
            "source_listed_date_not_BSE_effective":listed.isoformat(),
            "pre_BSE_market_open":listed<BSE_OPEN,
            "BSE_asof_old_or_new_code_validity":"NOT VERIFIED",
            "share_class_and_issuer_lifecycle":"NOT VERIFIED",
        })
    if not rows:
        raise ValueError("official code mapping no rows")
    required_note="注：由全国股转系统原精选层平移进入北交所的上市公司，上表中上市日期字段为其在原精选层的挂牌日期。"
    if native_footnotes != [required_note]:
        raise ValueError("official original-selected-tier transfer date footnote missing or changed")
    return {"rows":rows,"rows_count":len(rows),
            "official_date_column_qualification_note":required_note,
            "official_date_column_note_sha256":digest(required_note.encode("utf-8")),
            "pre_BSE_original_listing_count":sum(x["pre_BSE_market_open"] for x in rows)}


def fetch_and_review(session=None) -> tuple[dict,bytes|None]:
    session=session or requests.Session()
    attempts=[];received=None
    for n in range(1,4):
        attempt={"attempt":n,"at_utc":datetime.now(timezone.utc).isoformat()}
        attempts.append(attempt)
        try:
            if not _official(URL):
                raise RuntimeError("untrusted source URL")
            response=session.get(URL,timeout=(8,25),allow_redirects=True,
                                 headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"})
            final=str(response.url)
            raw=response.content
            attempt.update({"status_code":response.status_code,"final_url":final,
                            "sha256":digest(raw),"raw_bytes":len(raw),
                            "content_type":response.headers.get("Content-Type","")})
            if not _official(final) or response.status_code!=200:
                raise RuntimeError("off-host redirect or non-200 source")
            if not 0<len(raw)<=MAX_BYTES:
                raise RuntimeError("invalid source byte length")
            observed=parse(raw,attempt["content_type"])
            received=raw
            attempt["status"]="PASS"
            return ({
                "schema":"stock-bse-current-code-alias-diagnostic-v1",
                "source":URL, "actual_http_receipt":"PASS",
                "raw_sha256":digest(raw),"retrieved_at_utc":attempt["at_utc"],
                "attempts":attempts,
                "observed":observed,
                "adjudication":{
                    "current_official_alias_table":"PASS",
                    "historical_920_alias_effective_dates":"NOT VERIFIED",
                    "pre_BSE_original_listing_means_BSE_listing":"NOT VERIFIED",
                    "asof_native_SecurityType_1":"NOT VERIFIED",
                    "BSE_historical_listing_delisting":"NOT VERIFIED",
                    "historical_full_SSE_SZSE_BSE_ST_suspension":"NOT VERIFIED",
                    "production_historical_st_pit":"NOT VERIFIED",
                    "final_gate":"FAIL",
                },
            },received)
        except Exception as exc:
            attempt["error"]=f"{type(exc).__name__}: {exc}"
    return ({
        "schema":"stock-bse-current-code-alias-diagnostic-v1","source":URL,
        "actual_http_receipt":"NOT VERIFIED","attempts":attempts,
        "adjudication":{"current_official_alias_table":"NOT VERIFIED",
                         "historical_full_SSE_SZSE_BSE_ST_suspension":"NOT VERIFIED",
                         "production_historical_st_pit":"NOT VERIFIED",
                         "final_gate":"FAIL"}
    },received)


if __name__=="__main__":
    from pathlib import Path
    result,raw=fetch_and_review()
    Path("stock_bse_current_code_alias_evidence.json").write_text(
        json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    if raw is not None:
        Path("stock_bse_current_code_alias_raw.html").write_bytes(raw)
    print(json.dumps({
        "official_source":URL, "status":result["actual_http_receipt"],
        "rows_count":result.get("observed",{}).get("rows_count"),
        "pre_BSE_original_listing_count":result.get("observed",{}).get("pre_BSE_original_listing_count"),
        "attempt_errors":[str(v.get("error",""))[:350] for v in result["attempts"]],
        "http_statuses":[v.get("status_code") for v in result["attempts"]],
        "resolved_hosts":[urlparse(v.get("final_url",URL)).hostname for v in result["attempts"]],
        "adjudication":result["adjudication"]
    },sort_keys=True))
    raise SystemExit(0 if result["actual_http_receipt"]=="PASS" else 2)
