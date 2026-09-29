from pathlib import Path

from head_intelligence.domain import Source
from head_intelligence.engine import InformationEngine


def test_self_test(tmp_path: Path):
    engine = InformationEngine(data_dir=tmp_path)
    result = engine.self_test()
    assert result["status"] == "PASS"
    assert result["checks"]["deduplication"] is True
    assert result["checks"]["storage_round_trip"] is True
    assert result["checks"]["health"] is True


def test_atomic_snapshot_health(tmp_path: Path):
    engine = InformationEngine(data_dir=tmp_path)
    health = engine.health_check()
    assert health["status"] == "PASS"
    assert health["checks"]["data_dir_writable"] is True


def test_bls_api_contract(tmp_path: Path):
    engine = InformationEngine(data_dir=tmp_path)
    source = Source(
        id="bls_latest",
        name="BLS",
        url="https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000",
        source_type="bls_api",
    )
    payload = b'{"status":"REQUEST_SUCCEEDED","Results":{"series":[{"seriesID":"LNS14000000","data":[{"year":"2026","period":"M08","periodName":"August","value":"4.1"}]}]}}'
    items = engine._parse_bls_api(source, payload, "2026-09-29T00:00:00+00:00")
    assert len(items) == 1
    assert "4.1%" in items[0].title
    assert items[0].source_id == "bls_latest"
