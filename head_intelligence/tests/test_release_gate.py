import json
import hashlib
from pathlib import Path

from head_intelligence.release_gate import HARD_GATES, MARKERS, UPDATER_CHECKS, REAL_RELEASE_CHECKS, evaluate as _evaluate
from head_intelligence.repository_independence_gate import REQUIRED

def evaluate(*args, **kwargs):
    # These unit fixtures are not GitHub-run production evidence.
    return _evaluate(*args,check_untracked=False,**kwargs)

REQUIRED_MARKERS = [
    "unit_tests.pass","contract_tests.pass","integration_tests.pass","fault_injection.pass",
    "python_self_test.pass","real_network.pass","business_validation.pass",
    "counterexample_validation.pass","reversal_validation.pass","windows_build.pass",
    "exact_exe_self_test.pass","gui_smoke.pass","physical_gui_click.pass","same_hash.pass",
]

def make_gate_input(path: Path, override=None):
    gates={k:"PASS" for k in HARD_GATES}
    if override: gates.update(override)
    path.write_text(json.dumps({"status":"PASS","source_sha":"a"*40,"workflow_run":"10","workflow_attempt":"1","gates":gates}),encoding="utf-8")

def _fixture(tmp_path: Path):
    evidence=tmp_path/"evidence"; evidence.mkdir()
    for name in REQUIRED_MARKERS: (evidence/name).write_text("PASS",encoding="utf-8")
    candidate=tmp_path/"candidate.exe"; final=tmp_path/"final.exe"
    candidate.write_bytes(b"same-binary"); final.write_bytes(b"same-binary")
    updater=tmp_path/"HeadIntelligence_Updater.exe";updater.write_bytes(b"independent-updater")
    digest=hashlib.sha256(updater.read_bytes()).hexdigest()
    receipts=evidence/"process-gates";receipts.mkdir()
    for name in set(MARKERS)|{"architecture","business_content","updater_exact_exe","updater_build"}:
        bound_hash=digest if name.startswith("updater_") else hashlib.sha256(candidate.read_bytes()).hexdigest()
        (receipts/f"{name}.json").write_text(json.dumps({"schema":"head-intelligence-process-gate-v1","gate":name,"status":"PASS","source_sha":"a"*40,"workflow_run":"10","workflow_attempt":"1","exit_code":0,"command":["offline-unit-fixture"],"artifact_sha256":bound_hash}))
    (evidence/"updater_gate.json").write_text(json.dumps({"schema":"head-intelligence-updater-gate-v1","status":"PASS","github_sha":"a"*40,"checks":{name:{"status":"PASS"} for name in UPDATER_CHECKS}}),encoding="utf-8")
    (evidence/"updater_windows_gate.json").write_text(json.dumps({"schema":"head-intelligence-updater-windows-gate-v1","status":"PASS","github_sha":"a"*40,"updater_exact_exe":"PASS","updater_exe_sha256":digest,"final_updater_sha256":digest,"same_hash":True,"self_test":{"schema":"head-intelligence-updater-self-test-v1","status":"PASS","checks":{"version_parser":"PASS","https_trust":"PASS"}}}),encoding="utf-8")
    (evidence/"software_release_validation.json").write_text(json.dumps({"schema":"head-intelligence-real-software-release-validation-v1","status":"PASS","source_sha":"a"*40,"github_sha":"a"*40,"repository":"owner/HeadIntelligence","checks":{name:{"status":"PASS"} for name in REAL_RELEASE_CHECKS}}),encoding="utf-8")
    (evidence/"physical_gui_click.json").write_text(json.dumps({"schema":"head-intelligence-physical-gui-v2","status":"PASS","source_sha":"a"*40,"exe_sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"button_count":4,"operation_binding":"PASS","release_mode":"ConfiguredRelease"}),encoding="utf-8")
    (evidence/"repository_independence.json").write_text(json.dumps({"schema":"head-intelligence-repository-independence-v1","status":"PASS","source_sha":"a"*40,"workflow_run":"10","workflow_attempt":"1","repository":"owner/HeadIntelligence","files":[{"path":"head_intelligence/"+name} for name in REQUIRED]}))
    for filename in ("updater_gate.json","updater_windows_gate.json","software_release_validation.json","physical_gui_click.json"):
        path=evidence/filename;value=json.loads(path.read_text());value["workflow_run"]="10";value["workflow_attempt"]="1";path.write_text(json.dumps(value))
    return evidence,candidate,final

def test_release_gate_passes_only_with_all_markers_and_same_hash(tmp_path: Path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json"; make_gate_input(gate_input)
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["final_gate"]=="PASS"
    assert result["hard_fail_count"]==0

def test_release_gate_fails_on_non_pass_gate(tmp_path: Path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json"; make_gate_input(gate_input,{"risk_boundary":"WARNING"})
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["final_gate"]=="FAIL"
    assert result["failures"]["risk_boundary"]=="NOT VERIFIED"

def test_release_gate_fails_when_physical_gui_marker_missing(tmp_path: Path):
    evidence,candidate,final=_fixture(tmp_path)
    (evidence/"process-gates"/"physical_gui_click.json").unlink()
    gate_input=tmp_path/"gate.json"; make_gate_input(gate_input)
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["final_gate"]=="FAIL"
    assert result["failures"]["physical_gui_click"]=="NOT VERIFIED"

def test_forged_pass_input_cannot_override_missing_updater_evidence(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    (evidence/"updater_gate.json").unlink()
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["final_gate"]=="FAIL"
    assert result["failures"]["updater_process"]=="FAIL"
    assert result["failures"]["updater_atomic_rollback"]=="FAIL"

def test_updater_tamper_and_wrong_head_fail_closed(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    (tmp_path/"HeadIntelligence_Updater.exe").write_bytes(b"tampered")
    record=json.loads((evidence/"updater_gate.json").read_text())
    record["github_sha"]="b"*40
    (evidence/"updater_gate.json").write_text(json.dumps(record),encoding="utf-8")
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["failures"]["updater_exact_exe"]=="FAIL"
    assert result["failures"]["updater_same_hash"]=="FAIL"
    assert result["failures"]["updater_atomic_rollback"]=="FAIL"

def test_missing_real_release_stays_blocked(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    (evidence/"software_release_validation.json").unlink()
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    assert evaluate(evidence,candidate,final,gate_input)["failures"]["updater_real_network"]=="BLOCKED"

def test_arbitrary_pass_check_names_cannot_satisfy_updater(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json"; make_gate_input(gate_input)
    value=json.loads((evidence/"updater_gate.json").read_text())
    value["checks"]={str(i):{"status":"PASS"} for i in range(15)}
    (evidence/"updater_gate.json").write_text(json.dumps(value))
    assert evaluate(evidence,candidate,final,gate_input)["failures"]["updater_atomic_rollback"]=="FAIL"

def test_arbitrary_real_release_check_names_and_blocked_gui_cannot_pass(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json"; make_gate_input(gate_input)
    value=json.loads((evidence/"software_release_validation.json").read_text())
    value["checks"]={"anything":{"status":"PASS"}}
    (evidence/"software_release_validation.json").write_text(json.dumps(value))
    physical=json.loads((evidence/"physical_gui_click.json").read_text())
    physical["release_mode"]="BlockedRelease"
    (evidence/"physical_gui_click.json").write_text(json.dumps(physical))
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["final_gate"]=="FAIL"
    assert result["failures"]["updater_real_network"]=="FAIL"
    assert result["failures"]["physical_gui_click"]=="BLOCKED"

def test_cli_style_pass_cannot_override_shared_repository(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    path=evidence/"repository_independence.json";value=json.loads(path.read_text());value["repository"]="douluo511/Geometry-Lotto-Pro";path.write_text(json.dumps(value))
    assert evaluate(evidence,candidate,final,gate_input)["failures"]["repository_independence"]=="BLOCKED"

def test_old_run_receipt_and_marker_only_cannot_pass(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    path=evidence/"process-gates"/"unit_test.json";value=json.loads(path.read_text());value["workflow_run"]="9";path.write_text(json.dumps(value))
    assert evaluate(evidence,candidate,final,gate_input)["failures"]["unit_test"]=="NOT VERIFIED"
    path.unlink()
    assert (evidence/"unit_tests.pass").exists()
    assert evaluate(evidence,candidate,final,gate_input)["failures"]["unit_test"]=="NOT VERIFIED"

def test_previous_attempt_cannot_supply_repository_gui_or_updater_evidence(tmp_path):
    evidence,candidate,final=_fixture(tmp_path)
    gate_input=tmp_path/"gate.json";make_gate_input(gate_input)
    for name in ("repository_independence.json","physical_gui_click.json","updater_gate.json","updater_windows_gate.json"):
        path=evidence/name;value=json.loads(path.read_text());value["workflow_attempt"]="0";path.write_text(json.dumps(value))
    result=evaluate(evidence,candidate,final,gate_input)
    assert result["failures"]["repository_independence"]=="NOT VERIFIED"
    assert result["failures"]["physical_gui_click"]=="FAIL"
    assert result["failures"]["updater_atomic_rollback"]=="FAIL"
    assert result["failures"]["updater_exact_exe"]=="FAIL"
