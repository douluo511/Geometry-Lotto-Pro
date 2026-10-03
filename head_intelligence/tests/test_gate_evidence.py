import json
from unittest.mock import patch
from head_intelligence.gate_evidence import read_receipt, receipt_valid
from head_intelligence.repository_independence_gate import REQUIRED, evaluate_inventory


def receipt():
    return {"schema":"head-intelligence-process-gate-v1","gate":"unit_test","status":"PASS","exit_code":0,
            "source_sha":"a"*40,"workflow_run":"10","command":["offline-fixture"]}


def test_receipt_rejects_stale_head_run_and_nonzero_exit():
    value=receipt()
    assert receipt_valid(value,gate="unit_test",source_sha="a"*40,workflow_run="10")
    for field,changed in (("source_sha","b"*40),("workflow_run","9"),("exit_code",1)):
        wrong={**value,field:changed}
        assert not receipt_valid(wrong,gate="unit_test",source_sha="a"*40,workflow_run="10")


def test_tracked_receipt_is_never_authoritative(tmp_path):
    path=tmp_path/"receipt.json";path.write_text(json.dumps(receipt()))
    with patch("head_intelligence.gate_evidence.untracked",return_value=False):
        assert not read_receipt(path,gate="unit_test",source_sha="a"*40,workflow_run="10")


def test_shared_repo_seed_does_not_satisfy_independence():
    files=["head_intelligence/"+name for name in REQUIRED]
    assert evaluate_inventory("douluo511/Geometry-Lotto-Pro",files)[0]=="BLOCKED"
    assert evaluate_inventory("owner/HeadIntelligence",files)[0]=="PASS"
    assert evaluate_inventory("owner/HeadIntelligence",files+["psychology_insight_pro/app.py"])[0]=="FAIL"
