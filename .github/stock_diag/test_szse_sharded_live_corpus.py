"""Synthetic offline adversarial checks; never count these as real-network PASS."""
from pathlib import Path
import copy,hashlib,importlib.util,json,tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("szse_live",HERE/"stock_szse_sharded_live_corpus.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SHA="a"*64
def item(i):
    url=f"https://www.szse.cn/disclosure/notice/temp/t20180102_{500000+i}.html"
    sample=f"深圳证券交易所公告：{i}号临时停牌，相关交易所公告内容以发布为准。"
    return {"url":url,"archive_date":"20180102","archive_identity_source":"real_source_archive",
        "status":"PASS","transport":{
            "status":"PASS","sha256":hashlib.sha256(url.encode()).hexdigest(),
            "http_status":200,"same_official_host":True,"resolved_url":url,
        },
        "title":"深交所关于临时停牌的公告",
        "article_body_status":"PASS","article_source":".news-detail-con #desContent",
        "body_text_chars":len(sample),"body_text_sha256":hashlib.sha256(sample.encode()).hexdigest(),
        "semantic_sample":sample,
        "semantic_sample_sha256":hashlib.sha256(sample.encode()).hexdigest(),
    }
frozen={
    "schema":"stock-szse-suspension-detail-corpus-v1",
    "source_archive":{"event_rows":m.FULL,"canonical_sha256":m.OFFICIAL},
    "summary":{"transport_pass":m.FULL,"body_text_extracted":m.FULL},
    "records":[item(i) for i in range(m.FULL)],
}
tests=[]
links=m.frozen_links(frozen)
assert len(links)==1849
counts=[len(m.select(links,i)) for i in range(m.SHARDS)]
assert len(counts)==13 and sum(counts)==1849 and min(counts)>=140 and max(counts)<=143
assert len({(x["date"],x["url"]) for i in range(m.SHARDS) for x in m.select(links,i)})==1849
tests.append("all shards partition exactly 1849 unique source URLs")

def should_error(name,func):
    try: func()
    except (ValueError,RuntimeError,KeyError):
        tests.append(name)
        return
    raise AssertionError(f"FAILED TO REJECT {name}")

bad=copy.deepcopy(frozen);bad["source_archive"]["event_rows"]=1848
should_error("frozen total may not drop",lambda:m.frozen_links(bad))
bad=copy.deepcopy(frozen);bad["source_archive"]["canonical_sha256"]="f"*64
should_error("source archive SHA binding mandatory",lambda:m.frozen_links(bad))
bad=copy.deepcopy(frozen);bad["records"][1]["url"]=bad["records"][0]["url"]
should_error("duplicate original URL rejects",lambda:m.frozen_links(bad))
bad=copy.deepcopy(frozen);bad["records"][0]["url"]="https://evil.example/disclosure/notice/temp/t20180102_500000.html"
should_error("cross-host source injection rejects",lambda:m.frozen_links(bad))
bad=copy.deepcopy(frozen);bad["summary"]["body_text_extracted"]=1848
should_error("old body total 1848 rejects",lambda:m.frozen_links(bad))
should_error("invalid shard number rejects",lambda:m.select(links,13))
should_error("negative shard number rejects",lambda:m.select(links,-1))

assert m.positive(frozen["records"][0],None)
tests.append("positive named actual-SZSE primary container contract")
def not_positive(name,fn):
    q=copy.deepcopy(frozen["records"][0])
    fn(q)
    assert not m.positive(q,None),name
    tests.append(name)
not_positive("non-official redirect rejects",lambda x:x["transport"].update(resolved_url="https://elsewhere.example/redirect"))
not_positive("HTTP 404 rejects",lambda x:x["transport"].update(http_status=404))
not_positive("no same official host rejects",lambda x:x["transport"].update(same_official_host=False))
not_positive("generic page navigation false body rejects",lambda x:x.update(article_source=".content"))
not_positive("semantic sample hash corruption rejects",lambda x:x.update(semantic_sample_sha256="0"*64))
not_positive("missing body content rejects",lambda x:x.update(body_text_chars=0))
not_positive("missing raw response SHA rejects",lambda x:x["transport"].update(sha256="invalid"))
not_positive("transport NOT VERIFIED rejects",lambda x:x["transport"].update(status="NOT VERIFIED"))

with tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp)
    docs=d/"records"
    docs.mkdir()
    def fake_fetch(i):
        n=int(i["url"].split("_")[-1].split(".")[0])-500000
        return copy.deepcopy(frozen["records"][n])
    for index in range(m.SHARDS):
        target=docs/f"shard-{index:02d}.json"
        assert m.fetch_shard(frozen,index,target,fetcher=fake_fetch)==0
    complete=d/"full.json"
    assert m.aggregate(frozen,docs,complete)==0
    out=json.loads(complete.read_text())
    assert (out["observed_records"],out["live_primary_body_pass"],out["adjudication"]["full_official_page_and_primary_body"])==(1849,1849,"PASS")
    assert out["adjudication"]["three_market_historical_st_pit"]=="NOT VERIFIED"
    assert out["adjudication"]["final_gate"]=="FAIL"
    tests.append("offline synthetic 1849 shard merge is deterministically complete")
    broken=docs/"shard-04.json"
    j=json.loads(broken.read_text())
    j["records"].pop()
    broken.write_text(json.dumps(j))
    assert m.aggregate(frozen,docs,complete)==2
    result=json.loads(complete.read_text())
    assert result["adjudication"]["full_official_page_and_primary_body"]=="NOT VERIFIED"
    assert result["adjudication"]["final_gate"]=="FAIL"
    tests.append("one dropped source row fails entire frozen sum")
    broken.unlink()
    assert m.aggregate(frozen,docs,complete)==2
    tests.append("one entirely missing shard fails entire source corpus")
assert len(tests)==20,(len(tests),tests)
print("STOCK SZSE SOURCE SHARD FAIL-CLOSED OFFLINE SYNTHETIC 20/20 PASS")
