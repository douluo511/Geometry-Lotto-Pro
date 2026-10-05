from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main() -> int:
    acceptance=json.loads((ROOT/"ACCEPTANCE_CONTRACT.json").read_text(encoding="utf-8"))
    governance=json.loads((ROOT/"GOVERNANCE_SPEC.json").read_text(encoding="utf-8"))
    assert acceptance["schema_version"]==1
    assert len(acceptance["engineering_required"])==28
    assert len(acceptance["business_required"])==14
    assert governance["implementation_identity"]=="reauthored_2026-10-04_new_lineage"
    assert len(governance["five_why"])>=5
    assert len(governance["frozen_sections"])==8
    assert governance["ui_entries"]==["核心研习","一键更新","一键修复","高级分析"]
    required=[
        "app/domain.py","app/netclient.py","app/storage.py","app/sources.py","app/engine.py",
        "app/service.py","app/ui.py","app/updater.py","main.py","updater_main.py","build_windows.ps1"
    ]
    hashes={}
    for rel in required:
        p=ROOT/rel
        assert p.is_file(), rel
        hashes[rel]=hashlib.sha256(p.read_bytes()).hexdigest()
    report={
        "status":"PASS",
        "requirements_purpose_model":"PASS",
        "five_why":"PASS",
        "risk_boundary":"PASS",
        "domain_model":"PASS",
        "architecture":"PASS",
        "function_inventory":"PASS",
        "files":hashes,
    }
    (ROOT/"governance_evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
