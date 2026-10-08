"""Positive and adversarial checks for exact raw-byte 19-shard merge."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import stock_szse_bounded_shard as capture
import stock_szse_merge_shards as merge

checks = []

def assert_true(value):
    assert value

def check(name, fn):
    fn()
    checks.append(name)

def reject(fn):
    try:
        fn()
    except (ValueError, OSError):
        return
    raise AssertionError("invalid source evidence accepted")

class Response:
    def __init__(self, url, raw):
        self.url = url
        self.content = raw
        self.status_code = 200
        self.headers = {"Content-Type":"text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

def make_source():
    rows = [{
        "url":f"https://www.szse.cn/disclosure/notice/temp/t20200930_{i}.html",
        "date":"20200930", "identity_source":"literal_template_identifier",
    } for i in range(4)]
    return {
        "schema":"stock-szse-suspension-static-archive-v1",
        "frozen_window":{"start":"20180101","end":"20260930"},
        "corpus":{
            "event_rows":4,"unique_article_links":4,"canonical_sha256":capture.canonical(rows),
            "events":rows,
        },
        "adjudication":{"official_static_archive_pagination":"PASS"},
    }

def mock_response(url, **kwargs):
    i = int(url.split("_")[-1].split(".")[0])
    html=(f'<html><div class="news-detail-con"><div id="desContent" class="des-content">'
          f'证券代码00000{i}关于上市公司2020年9月30日开市起暂停交易的公告，'
          f'正式内容和明示时间。记录编号{i}。</div></div></html>')
    return Response(url,html.encode("utf-8"))

original = (
    capture.ARCHIVE_COUNT, capture.ARCHIVE_SHA256, capture.SHARD_SIZE,
    merge.ARCHIVE_COUNT, merge.ARCHIVE_SHA256, merge.SHARD_SIZE
)
source = make_source()
capture.ARCHIVE_COUNT=4
capture.ARCHIVE_SHA256=source["corpus"]["canonical_sha256"]
capture.SHARD_SIZE=2
merge.ARCHIVE_COUNT=4
merge.ARCHIVE_SHA256=source["corpus"]["canonical_sha256"]
merge.SHARD_SIZE=2
try:
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        parts=base/"parts"
        parts.mkdir()
        for i in range(2):
            folder=parts/f"shard-{i:02d}"
            folder.mkdir()
            previous=Path.cwd()
            os.chdir(folder)
            try:
                # Production records store relative artifact-root paths, never
                # a runner's absolute, ephemeral workspace path.
                report=capture.run(source,i,Path("szse_shard_raw"),getter=mock_response,sleep=lambda _:None)
            finally:
                os.chdir(previous)
            (folder/"szse_shard_report.json").write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")
        merged=merge.merge(source,parts)
        check("full raw and canonical first-party source accepted",lambda:(
            assert_true(len(merged["evidence"])==4),
            assert_true(merged["raw_response_sha256_unique"]==4),
            assert_true(merged["adjudication"]["sse_szse_bse_daily_st_suspension_pit"]=="NOT VERIFIED"),
        ))
        b=parts/"shard-01"
        b2=base/"shard-01.saved"
        b.rename(b2)
        check("missing shard rejects whole source",lambda:reject(lambda:merge.merge(source,parts)))
        b2.rename(b)
        manifest=b/"szse_shard_report.json"
        doc=json.loads(manifest.read_text(encoding="utf-8"))
        doc["adjudication"]["final_gate"]="PASS"
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        check("fake product final gate rejected",lambda:reject(lambda:merge.merge(source,parts)))
        doc["adjudication"]["final_gate"]="FAIL"
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        path=b/doc["records"][0]["raw_path"]
        original_bytes=path.read_bytes()
        path.write_bytes(original_bytes+b"tamper")
        check("tampered actual response bytes rejected",lambda:reject(lambda:merge.merge(source,parts)))
        path.write_bytes(original_bytes)
        doc["records"][0]["url"]="https://www.szse.cn/disclosure/notice/temp/t20200930_999.html"
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        check("false URL provenance rejected",lambda:reject(lambda:merge.merge(source,parts)))
        doc["records"][0]["url"]=source["corpus"]["events"][2]["url"]
        manifest.write_text(json.dumps(doc),encoding="utf-8")
        check("restored evidence validates independently",lambda:assert_true(merge.merge(source,parts)["raw_response_sha256_unique"]==4))
finally:
    (
        capture.ARCHIVE_COUNT,capture.ARCHIVE_SHA256,capture.SHARD_SIZE,
        merge.ARCHIVE_COUNT,merge.ARCHIVE_SHA256,merge.SHARD_SIZE,
    )=original

assert len(checks)==6,checks
print("STOCK SOURCE RAW MERGE 6/6 CONTRACTS PASS")
