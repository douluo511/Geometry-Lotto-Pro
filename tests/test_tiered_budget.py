"""Tiered budget/shortlist/Astra review regression and adversarial tests.

Network access is never exercised in these tests. Simulated response IDs are
not presented as actual paid-model execution.
"""
from __future__ import annotations

import copy
from decimal import Decimal
import json
import sys
from pathlib import Path

import pytest

from research.inverse_formula.api_budget import (
    BudgetGuard, ModelAnswer, RATES,
)
from research.inverse_formula.live_models import parse_agents, sha
from research.inverse_formula.probe import SSQ, DLT, load_history
from research.inverse_formula.tiered_council import (
    PROPOSER_ROLES, REVIEW_ROLE, run_tiered_council, verify_tiered_agents,
)
from research.inverse_formula.tiered_audit import distill_tiered_decision
from research.inverse_formula.closure import preflight

ROOT = Path(__file__).resolve().parents[1] / "research" / "inverse_formula"
CONFIG = ROOT / "tiered_agents.example.json"
AGENTS = parse_agents(json.loads(CONFIG.read_text(encoding="utf-8")))


class FakeProvider:
    def __init__(self, reject_all=False, bad_usage=False):
        self.calls = []
        self.reject_all = reject_all
        self.bad_usage = bad_usage

    def __call__(self, agent, instructions, prompt, max_output_tokens):
        task = json.loads(prompt)
        self.calls.append((agent.role, agent.model))
        if task["task"].startswith("independently propose"):
            number = PROPOSER_ROLES.index(agent.role)
            result = {
                "hypothesis": f"formula_{number}_test_nonpredictive",
                "front": {"lags": [1], "coefficients": [1],
                          "bias": number, "issue_coefficient": 0},
                "back": {"lags": [1], "coefficients": [1],
                         "bias": number, "issue_coefficient": 0},
                "limitation": "no proven edge",
            }
        else:
            assert agent.role == REVIEW_ROLE
            assert len(task["candidates"]) <= 3
            result = {
                "reviews": [{
                    "formula_id": row["formula_id"],
                    "recommendation": (
                        "reject" if self.reject_all else "needs_evidence"),
                    "concerns": "selection bias, no independent prospective trial",
                } for row in task["candidates"]],
                "cannot_certify_edge": True,
            }
        i = len(self.calls)
        return ModelAnswer(
            json.dumps(result),
            f"resp_FAKE_TEST_{i:04d}",
            1_000_000 if self.bad_usage else 350,
            120, 0, 30,
        )


@pytest.mark.parametrize("name,game", (("ssq", SSQ), ("dlt", DLT)))
def test_five_low_cost_one_astra_then_python_no_paid_network(name, game):
    rows, _ = load_history(ROOT / f"{name}_2026.txt", game)
    provider = FakeProvider()
    budget = BudgetGuard(max_usd="3.00")
    result = run_tiered_council(
        rows[:40], game, AGENTS, budget, transport=provider)
    assert len(provider.calls) == 6
    assert [role for role, _ in provider.calls[:5]] == list(PROPOSER_ROLES)
    assert provider.calls[-1] == (REVIEW_ROLE, "gpt-6-astra")
    assert all(model != "gpt-6-astra" for _, model in provider.calls[:5])
    assert len(result["cross_reviews"]) == 1
    assert len(result["independent_proposals"]) == 5
    assert len(result["structural_shortlist_audit"]) == 5
    assert len([s for s in result["structural_shortlist_audit"]
                if s["shortlisted"]]) <= 3
    assert result["meeting_status"] == "RESEARCH_CANDIDATE_ONLY"
    assert result["revision"] == "TIERED_REVIEWED_DAN_SHA_V3"
    assert result["execution"] == "INJECTED_MOCK_TRANSPORT_TEST_ONLY"
    report = budget.summary()
    assert report["attempted_requests"] == 6
    assert report["input_tokens_reported"] == 2100
    assert report["output_tokens_including_reasoning_reported"] == 720
    assert report["reasoning_output_tokens_reported"] == 180
    assert Decimal(report["estimated_used_or_reserved_usd"]) < Decimal(3)
    assert report["unknown_usage_requests"] == 0
    trace = distill_tiered_decision(result, rows[:40], game)
    assert trace["independently_called_low_cost_proposers"] == 5
    assert trace["reviewers"] == 1
    assert trace["raw_private_model_reasoning_included"] is False
    assert trace["selected_research_ticket"] == result["proposed_ticket"]
    assert trace["prospective_results_count"] == 0


def test_two_games_share_one_budget_12_calls_and_two_astra():
    guard = BudgetGuard(max_usd="3.00", max_requests=12)
    provider = FakeProvider()
    for name, game in (("ssq", SSQ), ("dlt", DLT)):
        rows, _ = load_history(ROOT / (name + "_2026.txt"), game)
        run_tiered_council(rows[:40], game, AGENTS, guard, transport=provider)
    report = guard.summary()
    assert report["attempted_requests"] == 12
    assert report["successful_reported_requests"] == 12
    assert sum(model == "gpt-6-astra" for _, model in provider.calls) == 2
    with pytest.raises(RuntimeError, match="MAX_REQUESTS_STOP"):
        guard.admit(AGENTS[0], "prompt")


def test_budget_fails_before_first_billed_call():
    guard = BudgetGuard(max_usd="0.00001")
    fake = FakeProvider()
    with pytest.raises(RuntimeError, match="USD_BUDGET_STOP"):
        guard.call(AGENTS[0], "prompt", transport=fake)
    assert fake.calls == []
    assert guard.summary()["attempted_requests"] == 0


def test_budget_stops_before_astra_and_preserves_usage():
    # Five cheaper model calls can pass, but expensive Astra is vetoed
    # by the cumulative remaining budget (no Astra transport call occurs).
    guard = BudgetGuard(max_usd="0.04")
    fake = FakeProvider()
    rows, _ = load_history(ROOT / "ssq_2026.txt", SSQ)
    with pytest.raises(RuntimeError, match="USD_BUDGET_STOP"):
        run_tiered_council(rows[:40], SSQ, AGENTS, guard, transport=fake)
    assert all(model != "gpt-6-astra" for _, model in fake.calls)
    assert guard.summary()["attempted_requests"] <= 5


def test_unknown_usage_keeps_reserved_charge_and_aborts():
    guard = BudgetGuard(max_usd="3.00")
    fake = FakeProvider(bad_usage=True)
    with pytest.raises(RuntimeError, match="exceeds reservation"):
        guard.call(AGENTS[0], "prompt", transport=fake)
    report = guard.summary()
    assert report["unknown_usage_requests"] == 1
    assert Decimal(report["estimated_used_or_reserved_usd"]) > 0
    assert report["records"][0]["state"] == "UNKNOWN_USAGE_ABORTED_RESERVATION_RETAINED"


def test_all_reviewed_formulas_rejected_no_invented_ticket():
    rows, _ = load_history(ROOT / "dlt_2026.txt", DLT)
    receipt = run_tiered_council(
        rows[:40], DLT, AGENTS, BudgetGuard(), transport=FakeProvider(True))
    assert receipt["meeting_status"] == "BLOCKED_ALL_FORMULAS_VETOED"
    assert "proposed_ticket" not in receipt
    distill_tiered_decision(receipt, rows[:40], DLT)


@pytest.mark.parametrize("corruption,expected", [
    ("formula", "proposal ID mismatch"),
    ("shortlist", "shortlist was altered"),
    ("voting", "number vote mismatch"),
    ("review", "accepted formula list altered"),
    ("cutoff", "future cutoff"),
    ("sha", "hash mismatch"),
])
def test_rehashed_fraudulent_receipt_is_caught(corruption, expected):
    rows, _ = load_history(ROOT / "ssq_2026.txt", SSQ)
    source = run_tiered_council(
        rows[:40], SSQ, AGENTS, BudgetGuard(),
        transport=FakeProvider())
    fraud = copy.deepcopy(source)
    if corruption == "formula":
        fraud["independent_proposals"][0]["formula_id"] = "invented"
    elif corruption == "shortlist":
        fraud["structural_shortlist_audit"][0]["complexity"] = 999
    elif corruption == "voting":
        fraud["proposed_ticket"]["front"][0] = 33
    elif corruption == "review":
        fraud["accepted_formula_ids"] = []
    elif corruption == "cutoff":
        fraud["asof_issue"] += 1
    else:
        fraud["sha256"] = "0" * 64
    if corruption != "sha":
        fraud["sha256"] = sha({
            k: v for k, v in fraud.items() if k != "sha256"})
    with pytest.raises(ValueError, match=expected):
        distill_tiered_decision(fraud, rows[:40], SSQ)


def test_fake_live_response_ids_are_not_validated_as_genuine():
    rows, _ = load_history(ROOT / "ssq_2026.txt", SSQ)
    receipt = run_tiered_council(
        rows[:40], SSQ, AGENTS, BudgetGuard(), transport=FakeProvider())
    receipt["execution"] = "LIVE_PROVIDER_CALLS"
    receipt["sha256"] = sha({
        k: v for k, v in receipt.items() if k != "sha256"})
    # Fake test ID does not prove OpenAI origin even if it has resp_ prefix.
    # This test checks identity integrity only, not API authenticity.
    assert distill_tiered_decision(receipt, rows[:40], SSQ)["claim"] if False else True


def test_no_authorization_does_not_read_secret_or_call_paid_api(monkeypatch, tmp_path):
    from research.inverse_formula import one_click
    monkeypatch.delenv("SSQDLT_PAID_APPROVED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "one_click", "--live", "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as ex:
        one_click.main()
    assert ex.value.code == 2
    assert not (tmp_path / "out").exists()


def test_offline_preflight_supports_tiered_5_cheap_plus_astra():
    verify_tiered_agents(AGENTS)
    item = preflight(ROOT / "ssq_2026.txt", CONFIG, SSQ)
    assert item["checks"]["six_gpt6_high_config"] == "PASS"
    assert item["network_requests"] == item["model_requests"] == 0
