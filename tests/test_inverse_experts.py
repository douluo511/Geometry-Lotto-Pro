"""Independent zero-cost expert contracts and adversarial leakage checks."""
from copy import deepcopy
from pathlib import Path

import pytest

from research.inverse_formula.independent_experts import (
    ROLES, combination_research, digest, engineer, formula_discovery,
    guarded_prefix, mathematician, simulate_experts, skeptical_reviewer,
    statistician, verify_evidence, wilson95,
)
from research.inverse_formula.probe import SSQ, DLT, Draw, load_history

BASE = Path(__file__).parents[1] / "research" / "inverse_formula"


def history(game, filename, size=34):
    rows, _ = load_history(BASE / filename, game)
    return rows, tuple(rows[:size])


@pytest.mark.parametrize("game,filename", [
    (SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")
])
def test_all_six_independent_pure_functions_and_replay(game, filename):
    rows, prefix = history(game, filename)
    model = mathematician(prefix, game)
    formulas = formula_discovery(prefix, game, lookback=5)
    combinations = combination_research(prefix, game, formulas)
    stats = statistician(prefix, game, model, window=2)
    review = skeptical_reviewer(model, formulas, combinations, stats)
    eng = engineer(prefix, game, combinations, review)
    assert model["d2_probability"] == pytest.approx(
        game.front_pick * (game.front_pick - 1) /
        (game.front_max * (game.front_max - 1))
    )
    assert formulas["candidate_count"] == len(formulas["catalogue"])
    assert set(combinations["d2_pair_research_only"]).issubset(
        combinations["full_ticket"]["front"])
    assert len(combinations["unselected_front_not_verified_kills"]) == (
        game.front_max - game.front_pick)
    assert stats["latest_scored_issue"] == prefix[-1].issue
    assert all(x["asof_issue"] < x["target_issue"] for x in stats["trials"])
    assert review["veto"] is True
    assert eng["deployment"] == "BLOCKED_BY_REVIEW_VETO"
    assert eng["paid_model_calls"] == 0
    assert eng["externally_timestamped_prediction"] is False
    assert eng == engineer(prefix, game, combinations, review)


@pytest.mark.parametrize("game,filename", [
    (SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")
])
def test_six_evidence_chain_determinism_and_future_isolation(game, filename):
    rows, prefix = history(game, filename)
    a = simulate_experts(prefix, game, cutoff_issue=prefix[-1].issue,
                         replay_window=2)
    b = simulate_experts(prefix, game, cutoff_issue=prefix[-1].issue,
                         replay_window=2)
    assert a == b
    assert [x["role"] for x in a["records"]] == list(ROLES)
    assert verify_evidence(a["records"]) is True
    assert a["formal_promotion_allowed"] is False
    assert a["implementation"] == "SIX_PURE_FUNCTIONS_ZERO_API_CALLS_NOT_SIX_LLMS"
    # Mutating a not-yet-known next issue cannot affect a pre-cutoff decision.
    modified = list(rows)
    modified[len(prefix)] = Draw(
        rows[len(prefix)].issue,
        tuple(range(1, game.front_pick + 1)),
        tuple(range(1, game.back_pick + 1)),
    )
    other = simulate_experts(
        modified[:len(prefix)], game,
        cutoff_issue=prefix[-1].issue, replay_window=2)
    assert other["receipt_sha256"] == a["receipt_sha256"]


def test_rejects_future_suffix_invalid_balls_and_nonconsecutive_issues():
    draws, prefix = history(SSQ, "ssq_2026.txt")
    with pytest.raises(ValueError, match="future suffix"):
        simulate_experts(draws[:35], SSQ, cutoff_issue=prefix[-1].issue)
    tampered = list(prefix)
    tampered[-1] = Draw(prefix[-1].issue, (1, 2, 3, 4, 5, 5), (1,))
    with pytest.raises(ValueError, match="invalid historical"):
        guarded_prefix(tampered, SSQ, cutoff_issue=prefix[-1].issue)
    tampered[-1] = Draw(prefix[-2].issue + 2, prefix[-1].front, prefix[-1].back)
    with pytest.raises(ValueError, match="consecutive"):
        guarded_prefix(tampered, SSQ, cutoff_issue=tampered[-1].issue)


def test_evidence_tampering_and_reordering_rejected():
    _, prefix = history(SSQ, "ssq_2026.txt")
    records = simulate_experts(
        prefix, SSQ, cutoff_issue=prefix[-1].issue, replay_window=2)["records"]
    corrupt = deepcopy(records)
    corrupt[2]["payload"]["full_ticket"]["front"] = [1, 2]
    with pytest.raises(ValueError, match="payload hash"):
        verify_evidence(corrupt)
    with pytest.raises(ValueError, match="linkage"):
        verify_evidence([records[1], records[0], *records[2:]])


def test_skeptic_vetoes_future_formula_and_engineer_cannot_override():
    _, prefix = history(SSQ, "ssq_2026.txt")
    m = mathematician(prefix, SSQ)
    f = formula_discovery(prefix, SSQ, lookback=5)
    c = combination_research(prefix, SSQ, f)
    s = statistician(prefix, SSQ, m, window=2)
    altered_f = deepcopy(f)
    altered_c = deepcopy(c)
    altered_f["catalogue"][0]["validation_last_issue"] = prefix[-1].issue + 1
    altered_f["catalogue_sha256"] = digest(altered_f["catalogue"])
    altered_c["formula_catalogue_sha256"] = altered_f["catalogue_sha256"]
    veto = skeptical_reviewer(m, altered_f, altered_c, s)
    assert "FORMULA_FUTURE_LEAKAGE" in veto["veto_reasons"]
    assert veto["promotion_allowed"] is False
    no_veto = deepcopy(veto)
    no_veto["veto"] = False
    with pytest.raises(ValueError, match="review veto"):
        engineer(prefix, SSQ, c, no_veto)


def test_wilson_interval_and_bad_counts():
    ci = wilson95(0, 10)
    assert ci["low"] == 0.0
    assert ci["high"] > 0.0
    assert ci["rate"] == 0.0
    with pytest.raises(ValueError, match="invalid"):
        wilson95(11, 10)
    with pytest.raises(ValueError, match="invalid"):
        wilson95(0, 0)
