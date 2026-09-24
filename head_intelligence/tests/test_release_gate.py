from pathlib import Path

from head_intelligence.release_gate import REQUIRED_MARKERS, evaluate


def test_release_gate_passes_only_with_all_markers_and_same_hash(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in REQUIRED_MARKERS:
        (evidence / name).write_text("PASS", encoding="utf-8")

    candidate = tmp_path / "candidate.exe"
    final = tmp_path / "final.exe"
    candidate.write_bytes(b"same-binary")
    final.write_bytes(b"same-binary")

    result = evaluate(evidence, candidate, final)
    assert result["final_gate"] == "PASS"
    assert result["candidate_final_same_hash"] if "candidate_final_same_hash" in result else result["checks"]["candidate_final_same_hash"]


def test_release_gate_fails_when_any_required_marker_is_missing(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in REQUIRED_MARKERS[:-1]:
        (evidence / name).write_text("PASS", encoding="utf-8")

    candidate = tmp_path / "candidate.exe"
    final = tmp_path / "final.exe"
    candidate.write_bytes(b"same-binary")
    final.write_bytes(b"same-binary")

    result = evaluate(evidence, candidate, final)
    assert result["final_gate"] == "FAIL"
    assert result["checks"][REQUIRED_MARKERS[-1]] is False
