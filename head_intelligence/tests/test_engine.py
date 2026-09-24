from pathlib import Path

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
