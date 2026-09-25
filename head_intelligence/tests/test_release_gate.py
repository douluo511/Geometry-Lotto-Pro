import json
from pathlib import Path

from head_intelligence.release_gate import HARD_GATES, evaluate

REQUIRED_MARKERS = [
    "unit_tests.pass",
    "contract_tests.pass",
    "fault_injection.pass",
    "python_self_test.pass",
    "real_network.pass",
    "windows_build.pass",
    "exact_exe_self_test.pass",
    "gui_smoke.pass",
    "same_hash.pass",
    "final_exe_self_test.pass",
    "final_gui_smoke.pass",
]

def make_gate_input(path: Path, override=None):
    gates = {k: "PASS" for k in HARD_GATES}
    if override:
        gates.update(override)
    path.write_text(json.dumps({"gates": gates}), encoding="utf-8")

def _fixture(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in REQUIRED_MARKERS:
        (evidence / name).write_text("PASS", encoding="utf-8")
    candidate = tmp_path / "candidate.exe"
    final = tmp_path / "final.exe"
    candidate.write_bytes(b"same-binary")
    final.write_bytes(b"same-binary")
    return evidence, candidate, final

def test_release_gate_passes_only_with_all_markers_and_same_hash(tmp_path: Path):
    evidence, candidate, final = _fixture(tmp_path)
    gate_input = tmp_path / "gate.json"
    make_gate_input(gate_input)
    result = evaluate(evidence, candidate, final, gate_input)
    assert result["final_gate"] == "PASS"
    assert result["hard_fail_count"] == 0

def test_release_gate_fails_on_non_pass_gate(tmp_path: Path):
    evidence, candidate, final = _fixture(tmp_path)
    gate_input = tmp_path / "gate.json"
    make_gate_input(gate_input, {"risk_boundary": "WARNING"})
    result = evaluate(evidence, candidate, final, gate_input)
    assert result["final_gate"] == "FAIL"
    assert result["failures"]["risk_boundary"] == "WARNING"
