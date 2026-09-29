from pathlib import Path

from head_intelligence.domain import RawDocument, Source
from head_intelligence.engine import InformationEngine
from head_intelligence.storage import AtomicStorage


class FixtureNet:
    def fetch(self, source: Source) -> RawDocument:
        payload = (
            "<rss><channel><item>"
            f"<title>{source.name} official update</title>"
            f"<link>https://example.test/{source.id}</link>"
            "<description>policy market employment capital risk</description>"
            "</item></channel></rss>"
        ).encode("utf-8")
        import hashlib
        return RawDocument(
            source_id=source.id,
            source_name=source.name,
            url=source.url,
            requested_url=source.url,
            final_url=source.url,
            fetched_at="2026-09-29T00:00:00+00:00",
            http_status=200,
            content_type="application/rss+xml",
            payload_hash=hashlib.sha256(payload).hexdigest(),
            payload=payload,
            attempts=[{"attempt":1,"endpoint_index":1,"outcome":"HTTP_RESPONSE","status_code":200,"requested_url":source.url,"final_url":source.url,"retry_delay":0.0}],
        )


def test_full_service_storage_engine_integration(tmp_path: Path):
    sources=[
        Source(id="fed",name="Federal Reserve",url="https://example.test/fed"),
        Source(id="sec",name="SEC",url="https://example.test/sec"),
        Source(id="bls",name="BLS",url="https://example.test/bls"),
        Source(id="bea",name="BEA",url="https://example.test/bea"),
    ]
    storage=AtomicStorage(tmp_path)
    engine=InformationEngine(storage=storage,sources=sources,net_client=FixtureNet())
    report=engine.one_click_update(limit_per_source=5)
    assert report.status=="PASS"
    assert report.deduped_count==4
    snapshot=storage.read_json("latest_snapshot.json")
    assert snapshot is not None
    assert snapshot["status"]=="PASS"
    assert len(snapshot["source_health"])==4
    assert all(x["status"]=="PASS" for x in snapshot["source_health"])
