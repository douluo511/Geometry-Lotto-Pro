from pathlib import Path

from head_intelligence.domain import Source
from head_intelligence.engine import InformationEngine
from head_intelligence.storage import AtomicStorage


class MixedNet:
    def __init__(self, fail_id: str | None = None):
        self.fail_id=fail_id
    def fetch(self, source):
        if source.id==self.fail_id:
            raise RuntimeError("counterexample injected source failure")
        import hashlib
        from head_intelligence.domain import RawDocument
        payload=(
            "<rss><channel><item>"
            f"<title>{source.name} policy update</title>"
            f"<link>https://example.test/{source.id}</link>"
            "<description>policy regulation market risk</description>"
            "</item></channel></rss>"
        ).encode()
        return RawDocument(
            source_id=source.id,source_name=source.name,url=source.url,
            requested_url=source.url,final_url=source.url,
            fetched_at="2026-09-29T00:00:00+00:00",http_status=200,
            content_type="application/rss+xml",payload_hash=hashlib.sha256(payload).hexdigest(),
            payload=payload,attempts=[{"attempt":1,"endpoint_index":1,"outcome":"HTTP_RESPONSE","status_code":200}]
        )


def _sources():
    return [
        Source(id="a",name="A",url="https://example.test/a",quality=1.0),
        Source(id="b",name="B",url="https://example.test/b",quality=0.8),
    ]


def test_business_core_information_score_is_explainable_not_truth_probability(tmp_path: Path):
    engine=InformationEngine(storage=AtomicStorage(tmp_path),sources=_sources(),net_client=MixedNet())
    report=engine.one_click_update()
    assert report.status=="PASS"
    assert report.items
    assert all(0 <= item.score <= 100 for item in report.items)
    assert all(item.evidence_status in {"PRIMARY_SOURCE","MULTI_SOURCE_CATEGORY"} for item in report.items)


def test_counterexample_one_failed_enabled_source_blocks_live_pass_and_preserves_good_snapshot(tmp_path: Path):
    storage=AtomicStorage(tmp_path)
    good=InformationEngine(storage=storage,sources=_sources(),net_client=MixedNet()).one_click_update()
    assert good.status=="PASS"
    before=storage.read_json("latest_snapshot.json")
    bad=InformationEngine(storage=storage,sources=_sources(),net_client=MixedNet(fail_id="b")).one_click_update()
    assert bad.status=="FAIL"
    assert storage.read_json("latest_snapshot.json")==before


def test_reversal_lower_source_quality_reverses_score_without_changing_truth_label(tmp_path: Path):
    engine=InformationEngine(storage=AtomicStorage(tmp_path))
    hi=engine._make_item(Source(id="hi",name="HI",url="https://example.test/hi",quality=1.0),"Policy market update","", "2026-09-29T00:00:00+00:00","policy market risk")
    lo=engine._make_item(Source(id="lo",name="LO",url="https://example.test/lo",quality=0.1),"Policy market update","", "2026-09-29T00:00:00+00:00","policy market risk")
    assert hi.score > lo.score
    assert hi.evidence_status=="PRIMARY_SOURCE"
    assert lo.evidence_status=="PRIMARY_SOURCE"
