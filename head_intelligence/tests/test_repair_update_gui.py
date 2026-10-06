import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from head_intelligence.engine import InformationEngine
from head_intelligence.domain import Source
from head_intelligence.repair import repair_data
from head_intelligence.service import InformationService
from head_intelligence.tests.test_integration import FixtureNet


def seeded_engine(root):
    sources = [Source(id="fed", name="Federal Reserve", url="https://example.test/fed"), Source(id="sec", name="SEC", url="https://example.test/sec")]
    engine = InformationEngine(data_dir=root, sources=sources, net_client=FixtureNet())
    assert engine.one_click_update().status == "PASS"
    return engine


def test_repair_corrupt_and_missing_snapshot_with_bound_archive(tmp_path):
    engine = seeded_engine(tmp_path / "data")
    main = tmp_path / "HeadIntelligence.exe"
    main.write_bytes(b"MZ-main")
    snapshot = engine.load_latest_snapshot()
    path = engine.data_dir / "latest_snapshot.json"
    raw_hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (engine.data_dir / "raw").iterdir()}
    path.write_bytes(b"corrupt-json")
    result = repair_data(engine, main_exe=main)
    assert result["status"] == "BLOCKED"
    assert result["local_integrity_status"] == "PASS"
    assert set(result["checks"]) == {"database", "index", "missing_files", "cache", "configuration", "network_configuration", "version", "data_integrity"}
    assert result["checks"]["network_configuration"]["status"] == "BLOCKED"
    assert engine.load_latest_snapshot() == snapshot
    assert "RESTORED_VERIFIED_SNAPSHOT" in result["actions"]
    assert any(p.read_bytes() == b"corrupt-json" for p in (engine.data_dir / "repair_backups").iterdir())
    path.unlink()
    assert repair_data(engine, main_exe=main)["local_integrity_status"] == "PASS"
    assert engine.load_latest_snapshot() == snapshot
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (engine.data_dir / "raw").iterdir()} == raw_hashes


def test_raw_tamper_cannot_be_repaired_with_fabrication(tmp_path):
    engine = seeded_engine(tmp_path / "data")
    main = tmp_path / "HeadIntelligence.exe"
    main.write_bytes(b"MZ-main")
    raw = next((engine.data_dir / "raw").iterdir())
    raw.write_bytes(b"tampered-raw")
    before = (engine.data_dir / "latest_snapshot.json").read_bytes()
    result = repair_data(engine, main_exe=main)
    assert result["status"] == "FAIL"
    assert result["checks"]["data_integrity"]["status"] == "FAIL"
    assert (engine.data_dir / "latest_snapshot.json").read_bytes() == before
    assert raw.read_bytes() == b"tampered-raw"


def test_source_configuration_and_version_cannot_be_synthesized(tmp_path):
    engine = seeded_engine(tmp_path / "data")
    engine.sources = [Source(id="bad", name="Bad", url="http://example.test/feed")]
    main = tmp_path / "HeadIntelligence.exe"
    main.write_bytes(b"MZ-main")
    result = repair_data(engine, main_exe=main)
    assert result["status"] == "FAIL"
    assert result["checks"]["configuration"]["status"] == "FAIL"
    assert not main.with_name("HeadIntelligence_Update_Config.json").exists()


def test_service_software_update_handoff_is_independent_of_data_refresh(tmp_path):
    engine = InformationEngine(data_dir=tmp_path)
    service = InformationService(engine)
    with patch("head_intelligence.service.launch_independent_updater", return_value={"status":"PASS", "action":"UPDATER_HANDOFF", "requires_parent_exit":True}) as launch:
        result = service.software_update()
    assert result["action"] == "UPDATER_HANDOFF"
    assert launch.call_args.kwargs["data_root"] == engine.data_dir


def test_gui_update_does_not_claim_blocker_is_pass():
    from head_intelligence.app import HeadIntelligenceApp
    class Var:
        def set(self, value): self.value = value
    class UI:
        status_var = Var()
        text = ""
        scheduled = []
        def _set_text(self, value): self.text = value
        def after(self, ms, callback): self.scheduled.append((ms, callback))
        def destroy(self): pass
        def _audit_gui(self, operation, result): pass
    ui = UI()
    ui.service = type("Service", (), {"software_update": lambda self: (_ for _ in ()).throw(RuntimeError("missing real independent release config"))})()
    HeadIntelligenceApp.one_click_update(ui)
    assert "BLOCKED" in ui.text and not ui.scheduled
    ui.service = type("Service", (), {"software_update": lambda self: {"status":"PASS", "action":"UPDATER_HANDOFF"}})()
    HeadIntelligenceApp.one_click_update(ui)
    assert ui.scheduled and "UPDATER_HANDOFF" in ui.text
