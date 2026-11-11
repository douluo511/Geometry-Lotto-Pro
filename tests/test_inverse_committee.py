"""Tests for deterministic committee: no independent multi-LLM claim or edge."""
from pathlib import Path

import pytest

from research.inverse_formula.committee import (
    ROLE_NAMES, audit_recent_past, canonical_hash, research_null,
    run_committee,
)
from research.inverse_formula.probe import DLT, SSQ, load_history

BASE = Path(__file__).parents[1] / "research" / "inverse_formula"


@pytest.mark.parametrize("game,file", [
    (SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")
])
def test_six_roles_meeting_receipt_and_no_promotion(game, file):
    draws, _ = load_history(BASE / file, game)
    meeting = run_committee(draws[:33], game, evaluation_window=3)
    assert tuple(x["role"] for x in meeting["transcript"]) == ROLE_NAMES
    assert meeting["implementation"] == (
        "DETERMINISTIC_ROLE_SIMULATION_NOT_INDEPENDENT_LLM_AGENTS"
    )
    assert meeting["asof_issue"] == draws[32].issue
    assert meeting["target_issue"] == draws[32].issue + 1
    assert meeting["decision"]["status"] == "NO_EDGE"
    assert meeting["decision"]["promote_to_formal_v47"] is False
    assert meeting["guards"]["official_v47_modified"] is False
    assert meeting["guards"]["future_outcome_available_to_committee"] is False
    assert meeting["guards"]["historical_replay_is_independent"] is False
    ticket = meeting["decision"]["proposal"]
    assert len(set(ticket["front"])) == game.front_pick
    assert len(set(ticket["back"])) == game.back_pick
    assert set(ticket["d2_pair"]).issubset(set(ticket["front"]))
    digest = meeting.pop("receipt_sha256")
    assert digest == canonical_hash(meeting)


def test_committee_is_deterministic_and_future_outcome_cannot_affect_it():
    draws, _ = load_history(BASE / "ssq_2026.txt", SSQ)
    cutoff = 34
    left = run_committee(draws[:cutoff], SSQ, evaluation_window=2)
    altered = list(draws)
    altered[cutoff] = draws[cutoff + 1]
    right = run_committee(altered[:cutoff], SSQ, evaluation_window=2)
    assert left == right
    assert left["receipt_sha256"] == right["receipt_sha256"]
    assert left["internal_replay"]["last_evaluated_issue"] == draws[cutoff - 1].issue


def test_broken_history_and_invalid_windows_fail_closed():
    draws, _ = load_history(BASE / "dlt_2026.txt", DLT)
    with pytest.raises(ValueError, match="at least 31"):
        run_committee(draws[:30], DLT)
    broken = list(draws[:32])
    broken[-1] = broken[-2]
    with pytest.raises(ValueError, match="strictly consecutive"):
        run_committee(broken, DLT)
    with pytest.raises(ValueError, match="positive"):
        audit_recent_past(draws[:35], DLT, window=0)


def test_fixed_control_never_accepts_actual_numbers():
    a = research_null(2026130, SSQ)
    b = research_null(2026130, SSQ)
    assert a == b
    assert a != research_null(2026131, SSQ)
    assert set(a["d2_pair"]).issubset(set(a["front"]))
    with pytest.raises(TypeError):
        research_null(2026130, SSQ, (1, 2, 3))
