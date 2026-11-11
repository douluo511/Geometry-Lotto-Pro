"""Six-role decision graph/trace tests; all provider responses are mocked."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research.inverse_formula.live_council_v2 import run_reviewed_council
from research.inverse_formula.live_models import parse_agents, sha
from research.inverse_formula.neural_audit import (
    distill_decision, verify_independent_response_ids,
)
from research.inverse_formula.probe import SSQ, DLT, load_history

DATA = Path(__file__).resolve().parents[1] / "research" / "inverse_formula"
AGENTS = parse_agents(json.loads(
    (DATA / "multi_provider_agents.example.json").read_text(encoding="utf-8")
))
ROLE = {a.role: i for i, a in enumerate(AGENTS)}


def offline_model(agent, _system, prompt):
    body = json.loads(prompt)
    if body["task"].startswith("independently propose"):
        i = ROLE[agent.role]
        return json.dumps({
            "hypothesis": f"role {i}: bounded, falsifiable lagged recurrence",
            "front": {"lags": [1], "coefficients": [1],
                      "bias": i, "issue_coefficient": 0},
            "back": {"lags": [1], "coefficients": [1],
                     "bias": i, "issue_coefficient": 0},
            "limitation": "This proposal was created after observing past data.",
        })
    assert body["task"].startswith("independently scrutinize")
    return json.dumps({
        "reviews": [{
            "formula_id": item["formula_id"],
            "recommendation": (
                "reject" if item["role"] == "engineer" else "needs_evidence"),
            "concerns": "Post-hoc model selection and no prospective evidence.",
        } for item in body["untrusted_peer_formulas"]],
        "cannot_certify_edge": True,
    })


@pytest.mark.parametrize("game,name", ((SSQ, "ssq"), (DLT, "dlt")))
def test_research_trace_is_computable_and_no_private_thoughts(game, name):
    all_draws, _ = load_history(DATA / (name + "_2026.txt"), game)
    prefix = all_draws[:40]
    decision = run_reviewed_council(
        prefix, game, AGENTS, transport=offline_model)
    trace = distill_decision(decision, prefix, game, replay_window=5)
    assert trace["protocol"] == "SIX_ROLE_EVIDENCE_GRAPH_V1"
    assert len(trace["nodes"]) == 6
    assert trace["edges"]["independent_proposal_edges"] == 6
    assert trace["edges"]["cross_review_edges"] == 30
    assert trace["edges"]["vetoed_formulas"] == 1
    assert len(trace["formula_registry"]) == 6
    assert all(x["first_eligible_prospective_issue"] == prefix[-1].issue + 1
               for x in trace["formula_registry"])
    assert all(x["prospective_observation_count"] == 0
               and x["retrospective_accuracy_is_independent"] is False
               for x in trace["formula_registry"])
    assert trace["past_only_deterministic_bank_reference"]["evaluated_issues"] == 5
    assert "NOT a genuine historical validation" in trace["backtest_boundary"]
    assert "private" not in json.dumps(trace).lower() or (
        trace["decision_summary"]["raw_private_model_reasoning_included"] is False)
    assert trace["decision_summary"]["selected_ticket"] == decision["proposed_ticket"]
    assert sha({k: v for k, v in trace.items() if k != "sha256"}) == trace["sha256"]
    # Later unknown outcome changes without altering the already-sealed prefix.
    modified = list(all_draws)
    modified[40] = modified[41]
    assert distill_decision(decision, modified[:40], game, replay_window=5) == trace


@pytest.fixture(scope="module")
def fixture_receipt():
    prefix, _ = load_history(DATA / "ssq_2026.txt", SSQ)
    prior = prefix[:40]
    return prior, run_reviewed_council(prior, SSQ, AGENTS,
                                       transport=offline_model)


@pytest.mark.parametrize("mutation,expected", [
    ("formula", "formula identity tampered"),
    ("reviews", "incomplete, duplicated"),
    ("decision", "decision outcome mismatch"),
    ("future", "isolation guards"),
    ("sha", "tampered"),
])
def test_corrupt_trace_rejected_even_with_rehashed_receipt(
        fixture_receipt, mutation, expected):
    prefix, original = fixture_receipt
    row = copy.deepcopy(original)
    if mutation == "formula":
        row["independent_proposals"][0]["formula_id"] = "bad-id"
    elif mutation == "reviews":
        row["cross_reviews"][0]["review"]["reviews"].pop()
    elif mutation == "decision":
        row["proposed_ticket"]["front"] = [1, 2, 3, 4, 5, 6]
    elif mutation == "future":
        row["guards"]["unknown_target_used"] = True
    else:
        row["sha256"] = "0"*64
    if mutation != "sha":
        row["sha256"] = sha({k: v for k, v in row.items() if k != "sha256"})
    with pytest.raises(ValueError, match=expected):
        distill_decision(row, prefix, SSQ, replay_window=3)


def test_real_execution_receipt_requires_twelve_unique_provider_ids(
        fixture_receipt):
    _, mock = fixture_receipt
    record = copy.deepcopy(mock)
    record["execution"] = "LIVE_PROVIDER_CALLS"
    with pytest.raises(ValueError, match="12 distinct"):
        verify_independent_response_ids(record)
    ids = [item for group in ("independent_proposals", "cross_reviews")
           for item in record[group]]
    for i, row in enumerate(ids):
        row["provider_response_id"] = "resp-unique-%04d" % i
    verify_independent_response_ids(record)
    ids[-1]["provider_response_id"] = ids[0]["provider_response_id"]
    with pytest.raises(ValueError, match="12 distinct"):
        verify_independent_response_ids(record)


def test_receipt_history_cutoff_checked(fixture_receipt):
    prefix, decision = fixture_receipt
    with pytest.raises(ValueError, match="contiguous past-only history"):
        distill_decision(decision, prefix[:-1], SSQ)
    with pytest.raises(ValueError, match="contiguous past-only history"):
        distill_decision(decision, prefix[:-2] + [prefix[-1]], SSQ)
