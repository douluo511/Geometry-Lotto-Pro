"""Offline closure regression tests: no API key, network call, or V4.7 writes."""
import json
import sys
from pathlib import Path

import pytest

from research.inverse_formula.closure import (
    AGENT_FILE, _write_once, digest, freeze, preflight, score, verify_digest
)
from research.inverse_formula.committee import run_committee
from research.inverse_formula.probe import DLT, SSQ, load_history

DATA = Path(__file__).resolve().parents[1] / "research" / "inverse_formula"


@pytest.fixture(scope="module")
def ssq_documents():
    rows, source_sha = load_history(DATA / "ssq_2026.txt", SSQ)
    report = preflight(DATA / "ssq_2026.txt", AGENT_FILE, SSQ)
    committee = run_committee(rows, SSQ, evaluation_window=1)
    archive = {"SSQ": {"source_sha256": source_sha, "committee": committee}}
    return rows, report, archive


def test_preflight_is_offline_and_does_not_require_secret(monkeypatch):
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    def no_network(*args, **kwargs):
        raise AssertionError("preflight must not request the network")
    monkeypatch.setattr("urllib.request.urlopen", no_network)
    for game, filename in ((SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")):
        record = preflight(DATA / filename, AGENT_FILE, game)
        verify_digest(record)
        assert record["network_requests"] == record["model_requests"] == 0
        assert record["paid_authorization"] is False
        assert record["checks"]["live_model_entitlements"] == "UNVERIFIED"
        assert record["checks"]["official_source_authentication"] == "UNVERIFIED"
        assert record["formal_v47_promotion"] is False


def test_existing_committee_receipt_can_be_content_sealed(ssq_documents):
    rows, prior, archive = ssq_documents
    frozen = freeze(prior, archive, SSQ)
    verify_digest(frozen)
    assert frozen["game"] == "SSQ"
    assert frozen["asof_issue"] == rows[-1].issue
    assert frozen["target_issue"] == rows[-1].issue + 1
    assert frozen["ticket"]["d2_pair"]
    assert frozen["candidate_execution"] == "DETERMINISTIC_SIMULATION"
    assert frozen["trusted_predraw_timestamp"] is False
    assert frozen["status"].startswith("NO_EDGE")


def test_result_arithmetic_is_separate_and_does_not_mutate_seal(ssq_documents):
    _, prior, archive = ssq_documents
    frozen = freeze(prior, archive, SSQ)
    snapshot = json.dumps(frozen, sort_keys=True)
    candidate = frozen["ticket"]
    result = {
        "game": "SSQ", "issue": frozen["target_issue"],
        "front": candidate["front"], "back": candidate["back"],
        "source_url": "https://example.invalid/synthetic-unverified-test",
    }
    scored = score(frozen, result, SSQ)
    verify_digest(scored)
    assert scored["metrics"] == {
        "full_hit": 1, "front_hits": 6, "back_hits": 1, "d2_hit": 1,
    }
    assert scored["result_source_authenticated"] is False
    assert scored["frozen_sha256"] == frozen["sha256"]
    assert json.dumps(frozen, sort_keys=True) == snapshot
    result["front"] = [1, 2, 3, 4, 5, 6]
    different = score(frozen, result, SSQ)
    assert different["metrics"]["front_hits"] <= 6
    assert different["frozen_sha256"] == frozen["sha256"]


def test_tampered_preflight_candidate_and_seal_are_rejected(ssq_documents):
    _, prior, archive = ssq_documents
    fake = json.loads(json.dumps(prior))
    fake["history_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        freeze(fake, archive, SSQ)
    fake = json.loads(json.dumps(archive))
    fake["SSQ"]["committee"]["decision"]["proposal"]["front"][0] = 999
    with pytest.raises(ValueError, match="digest mismatch"):
        freeze(prior, fake, SSQ)
    frozen = freeze(prior, archive, SSQ)
    frozen["ticket"]["d2_pair"] = [1, 1]
    with pytest.raises(ValueError, match="digest mismatch"):
        score(frozen, {"game": "SSQ", "issue": prior["target_issue"],
                       "front": [1, 2, 3, 4, 5, 6], "back": [1],
                       "source_url": "https://example.invalid"}, SSQ)


def test_mismatched_cutoff_game_result_and_mocked_live_are_rejected(ssq_documents):
    _, prior, archive = ssq_documents
    changed = json.loads(json.dumps(archive))
    changed["SSQ"]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="not derived"):
        freeze(prior, changed, SSQ)
    with pytest.raises(ValueError, match="preflight is not valid"):
        freeze(prior, archive, DLT)
    frozen = freeze(prior, archive, SSQ)
    wrong = {
        "game": "SSQ", "issue": frozen["target_issue"] + 1,
        "front": [1, 2, 3, 4, 5, 6], "back": [1],
        "source_url": "https://example.invalid/synthetic",
    }
    with pytest.raises(ValueError, match="target issue"):
        score(frozen, wrong, SSQ)
    wrong["issue"] -= 1
    wrong["source_url"] = "http://example.invalid"
    with pytest.raises(ValueError, match="HTTPS"):
        score(frozen, wrong, SSQ)
    fake_live = {
        "protocol": "MULTI_PROVIDER_FORMULA_COUNCIL_V1",
        "game": "SSQ", "asof_issue": prior["asof_issue"],
        "target_issue": prior["target_issue"],
        "source_sha256": prior["history_sha256"],
        "execution": "INJECTED_MOCK_TRANSPORT_TEST_ONLY",
        "proposed_ticket": frozen["ticket"],
    }
    fake_live["sha256"] = digest(fake_live)
    with pytest.raises(ValueError, match="mock council"):
        freeze(prior, fake_live, SSQ)


def test_exclusive_file_output_prevents_overwrite_and_cli_is_no_charge(
        tmp_path, monkeypatch, ssq_documents):
    _, prior, archive = ssq_documents
    history = DATA / "ssq_2026.txt"
    preflight_file = tmp_path / "preflight.json"
    frozen_file = tmp_path / "sealed.json"
    archive_file = tmp_path / "candidate.json"
    result_file = tmp_path / "result.json"
    score_file = tmp_path / "score.json"
    archive_file.write_text(json.dumps(archive), encoding="utf-8")
    from research.inverse_formula.closure import main
    def invoke(*argv):
        monkeypatch.setattr(sys, "argv", ["closure"] + list(argv))
        main()
    invoke("preflight", "--game", "ssq", "--history", str(history),
           "--out", str(preflight_file))
    assert json.loads(preflight_file.read_text())["sha256"] == prior["sha256"]
    invoke("freeze", "--game", "ssq", "--preflight", str(preflight_file),
           "--candidate", str(archive_file), "--out", str(frozen_file))
    frozen = json.loads(frozen_file.read_text(encoding="utf-8"))
    result_file.write_text(json.dumps({
        "game": "SSQ", "issue": frozen["target_issue"],
        "front": frozen["ticket"]["front"], "back": frozen["ticket"]["back"],
        "source_url": "https://example.invalid/not-verified",
    }), encoding="utf-8")
    invoke("score", "--game", "ssq", "--frozen", str(frozen_file),
           "--actual", str(result_file), "--out", str(score_file))
    assert json.loads(score_file.read_text())["metrics"]["d2_hit"] == 1
    with pytest.raises(FileExistsError):
        invoke("score", "--game", "ssq", "--frozen", str(frozen_file),
               "--actual", str(result_file), "--out", str(score_file))
    with pytest.raises(FileExistsError):
        _write_once(frozen_file, {"unexpected": True})
    verify_digest(json.loads(frozen_file.read_text()))


def test_past_only_cutoff_cannot_consume_next_draw(tmp_path):
    rows, _ = load_history(DATA / "ssq_2026.txt", SSQ)
    prefix = rows[:99]
    def encode(row):
        front = "".join(f"{i:02d}" for i in row.front)
        back = "".join(f"{i:02d}" for i in row.back)
        return f"{row.issue}:{front}+{back}"
    path = tmp_path / "past-only.txt"
    path.write_text(";".join(map(encode, prefix)), encoding="utf-8")
    before = preflight(path, AGENT_FILE, SSQ)
    assert before["asof_issue"] == prefix[-1].issue
    assert before["target_issue"] == rows[99].issue
    # Later outcome mutated in memory; no code path in this test can access it.
    modified_future = {"front": [1, 2, 3, 4, 5, 6]}
    assert modified_future["front"] != list(rows[-1].front)
    assert preflight(path, AGENT_FILE, SSQ)["sha256"] == before["sha256"]
