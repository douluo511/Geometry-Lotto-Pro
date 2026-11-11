"""Falsification contract: complete wins, D2, past-only and negative controls."""
from copy import deepcopy
from pathlib import Path

import pytest

from research.inverse_formula import formula_bank
from research.inverse_formula.edge_gate import (
    audit_game, exact_upper_tail, independent_score,
)
from research.inverse_formula.probe import DLT, SSQ, Draw, load_history

BASE = Path(__file__).parents[1] / "research" / "inverse_formula"


@pytest.mark.parametrize("game,name,count", [
    (SSQ, "ssq_2026.txt", 70),
    (DLT, "dlt_2026.txt", 60),
])
def test_exact_full_ticket_and_d2_separately_scored_with_random_control(
        game, name, count):
    draws, _ = load_history(BASE / name, game)
    report = audit_game(draws, game)
    assert report["evaluated_issues"] == count
    assert len(report["per_issue_audit"]) == count
    assert report["full_ticket"]["fair_outcome_space"] == (
        17721088 if game.name == "SSQ" else 21425712
    )
    assert report["d2"]["fair_probability_per_pair"] == pytest.approx(
        game.front_pick * (game.front_pick - 1) /
        (game.front_max * (game.front_max - 1))
    )
    assert report["full_ticket"]["hits"] == sum(
        x["full_hit"] for x in report["per_issue_audit"])
    assert report["d2"]["hits"] == sum(
        x["d2_hit"] for x in report["per_issue_audit"])
    assert report["same_draw_paired_research_null"]["discordant"] == (
        report["same_draw_paired_research_null"]["wins"] +
        report["same_draw_paired_research_null"]["losses"]
    )
    assert report["status"] == "NO_EDGE"
    assert report["independent_prospective_draws"] == 0
    assert report["external_source_authenticated"] is False
    assert report["formal_promotion_allowed"] is False
    assert report["formal_v47_fixed_random_null_used"] is False


def test_research_null_only_accepts_issue_not_outcome_object():
    ticket, pair = formula_bank._research_null(2026130, SSQ)
    assert len(pair) == 2 and set(pair).issubset(ticket[0])
    assert (ticket, pair) == formula_bank._research_null(2026130, SSQ)
    with pytest.raises(ValueError, match="positive target issue"):
        formula_bank._research_null(0, SSQ)
    with pytest.raises(ValueError, match="positive target issue"):
        formula_bank._research_null(Draw(2026130, (1, 2, 3, 4, 5, 6), (7,)), SSQ)


def test_past_prediction_ignores_outcome_future_mutations():
    rows, _ = load_history(BASE / "ssq_2026.txt", SSQ)
    index = 31
    a = formula_bank.predict_with_bank(rows[:index], SSQ)
    modified = list(rows)
    modified[index] = Draw(rows[index].issue, (1, 2, 3, 4, 5, 6), (16,))
    b = formula_bank.predict_with_bank(modified[:index], SSQ)
    assert a["decision_sha256"] == b["decision_sha256"]
    assert formula_bank._research_null(a["target_issue"], SSQ) == (
        formula_bank._research_null(b["target_issue"], SSQ)
    )


def test_independent_scoring_rejects_missing_issue_and_score_tamper():
    rows, _ = load_history(BASE / "dlt_2026.txt", DLT)
    small = rows[:33]
    trials = formula_bank.walk_forward_bank(small, DLT, start=30)["per_issue_audit"]
    assert independent_score(small, DLT, trials, start=30)["evaluated_issues"] == 3
    with pytest.raises(ValueError, match="missing, truncated"):
        independent_score(small, DLT, trials[:-1], start=30)
    altered = deepcopy(trials)
    altered[0]["d2_hit"] = 1 - altered[0]["d2_hit"]
    with pytest.raises(ValueError, match="outcome score"):
        independent_score(small, DLT, altered, start=30)
    altered = deepcopy(trials)
    altered[0]["research_null"]["prediction"]["d2_pair"] = (1, 2)
    # If the unchanged research NULL happened to choose 1,2, select another
    # legal pair, without changing its complete front ticket.
    if tuple(altered[0]["research_null"]["prediction"]["d2_pair"]) == (
            tuple(trials[0]["research_null"]["prediction"]["d2_pair"])):
        altered[0]["research_null"]["prediction"]["d2_pair"] = (2, 3)
    with pytest.raises(ValueError):
        independent_score(small, DLT, altered, start=30)
    altered = deepcopy(trials)
    altered[0]["asof_issue"] = altered[0]["issue"]
    with pytest.raises(ValueError, match="cutoff"):
        independent_score(small, DLT, altered, start=30)


def test_exact_binomial_tail_sanity():
    assert exact_upper_tail(2, 2, 0.5) == pytest.approx(0.25)
    assert exact_upper_tail(1, 2, 0.5) == pytest.approx(0.75)
    assert exact_upper_tail(0, 20, 0.025) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="trial"):
        exact_upper_tail(3, 2, 0.1)
    with pytest.raises(ValueError, match="probability"):
        exact_upper_tail(0, 5, -0.1)
