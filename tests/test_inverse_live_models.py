"""No network, no API charges: deterministic contract tests for LIVE adapter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.inverse_formula.live_models import (
    Agent, consensus, formula_ticket, parse_agents, parse_proposal,
    parse_review, provider_call, require_keys, run_council, sha,
)
from research.inverse_formula.probe import DLT, SSQ, load_history

DATA = Path(__file__).parents[1] / "research" / "inverse_formula"
AGENTS = parse_agents([
    {"role": "mathematician", "provider": "openai", "model": "model-a"},
    {"role": "formula_discovery", "provider": "anthropic", "model": "model-b"},
    {"role": "skeptical_reviewer", "provider": "gemini", "model": "model-c"},
])


def proposal_for(role: str, game) -> str:
    offsets = {"mathematician": 0, "formula_discovery": 1,
               "skeptical_reviewer": 2}
    k = offsets[role]
    return json.dumps({
        "hypothesis": "Try an explicit bounded recurrence for historical comparison",
        "front": {"lags": [1], "coefficients": [1], "bias": k,
                  "issue_coefficient": 0},
        "back": {"lags": [2], "coefficients": [-1], "bias": k,
                 "issue_coefficient": 0},
        "limitation": "No prospective edge is demonstrated.",
    })


def fake_transport(game, calls):
    def transmit(agent, _system, prompt):
        obj = json.loads(prompt)
        calls.append((agent.role, obj))
        if obj["task"].startswith("independently"):
            assert "untrusted_peer_data" not in obj
            assert obj["role"] == agent.role
            assert "draws" in obj["past_only"]
            assert len(obj["past_only"]["draws"]) <= 30
            return proposal_for(agent.role, game)
        assert obj["task"].startswith("independent skeptical review")
        assert len(obj["untrusted_peer_data"]) == len(AGENTS) - 1
        assert all(x["role"] != agent.role for x in obj["untrusted_peer_data"])
        return json.dumps({
            "concerns": "No preregistration and no independent future holdout",
            "recommendation": "needs_evidence",
            "cannot_certify_edge": True,
        })
    return transmit


@pytest.mark.parametrize("game,filename", [
    (SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")
])
def test_separate_provider_calls_two_rounds_and_auditable_consensus(game, filename):
    draws, _ = load_history(DATA / filename, game)
    calls = []
    first = run_council(draws[:35], game, AGENTS,
                        transport=fake_transport(game, calls))
    assert first["execution"] == "INJECTED_MOCK_TRANSPORT_TEST_ONLY"
    assert first["asof_issue"] == draws[34].issue
    assert first["target_issue"] == draws[34].issue + 1
    assert len(calls) == 6
    assert len(first["independent_proposals"]) == 3
    assert len(first["cross_reviews"]) == 3
    assert first["unique_formulas"] == 3
    assert len(first["candidate_tickets"]) == 3
    assert first["decision"] == "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION"
    assert first["guards"]["formal_v47_modified"] is False
    assert first["guards"]["trusted_timestamp_established"] is False
    vote = first["proposed_ticket"]
    assert len(vote["front"]) == game.front_pick
    assert len(vote["back"]) == game.back_pick
    assert set(vote["d2_pair"]).issubset(vote["front"])
    checksum = first.pop("sha256")
    assert checksum == sha(first)
    assert all(c[1]["target_issue"] == draws[34].issue + 1
               if c[1]["task"].startswith("independent skeptical")
               else c[1]["past_only"]["target_issue"] == draws[34].issue + 1
               for c in calls)
    calls2 = []
    changed = list(draws)
    changed[35] = draws[36]  # mutate unknown target after the cutoff
    same = run_council(changed[:35], game, AGENTS,
                       transport=fake_transport(game, calls2))
    assert same["sha256"] == checksum


def test_invalid_agent_configs_or_missing_credentials_fail_closed(monkeypatch):
    with pytest.raises(ValueError, match="3..6"):
        parse_agents([])
    with pytest.raises(ValueError, match="duplicate model"):
        parse_agents([
            {"role": "mathematician", "provider": "openai", "model": "same"},
            {"role": "formula_discovery", "provider": "openai", "model": "same"},
            {"role": "engineer", "provider": "gemini", "model": "diff"},
        ])
    with pytest.raises(ValueError, match="distinct providers"):
        parse_agents([
            {"role": "mathematician", "provider": "openai", "model": "a"},
            {"role": "formula_discovery", "provider": "openai", "model": "b"},
            {"role": "engineer", "provider": "openai", "model": "c"},
        ])
    for field in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(field, raising=False)
    with pytest.raises(RuntimeError, match="missing required API"):
        require_keys(AGENTS)
    draws, _ = load_history(DATA / "ssq_2026.txt", SSQ)
    with pytest.raises(RuntimeError, match="missing required API"):
        run_council(draws[:35], SSQ, AGENTS)


def test_bad_generated_formula_and_reviews_are_rejected():
    wrong = json.loads(proposal_for("mathematician", SSQ))
    wrong["front"]["coefficients"] = [999]
    with pytest.raises(ValueError, match="lag or coefficient"):
        parse_proposal(json.dumps(wrong), SSQ)
    wrong["front"]["coefficients"] = [1]
    wrong["front"]["lags"] = [0]
    with pytest.raises(ValueError, match="lag or coefficient"):
        parse_proposal(json.dumps(wrong), SSQ)
    wrong["front"]["lags"] = [1]
    wrong["front"]["code"] = "__import__('os').system('echo dangerous')"
    with pytest.raises(ValueError, match="invalid structured formula"):
        parse_proposal(json.dumps(wrong), SSQ)
    with pytest.raises(ValueError, match="review must"):
        parse_review(json.dumps({
            "concerns": "test", "recommendation": "test",
            "cannot_certify_edge": False,
        }))


def test_parallel_failure_cannot_silently_replace_with_fake_result():
    draws, _ = load_history(DATA / "dlt_2026.txt", DLT)
    def broken(agent, system, prompt):
        if agent.provider == "anthropic":
            raise RuntimeError("intentionally unavailable")
        return fake_transport(DLT, [])(agent, system, prompt)
    with pytest.raises(RuntimeError, match="intentionally unavailable"):
        run_council(draws[:35], DLT, AGENTS, transport=broken)


@pytest.mark.parametrize("provider,payload", [
    ("openai", {"output": [{"type": "message",
                   "content": [{"type": "output_text", "text": "{\"ok\":true}"}]}]}),
    ("anthropic", {"content": [{"type": "text", "text": "{\"ok\":true}"}]}),
    ("gemini", {"candidates": [{"content": {
                   "parts": [{"text": "{\"ok\":true}"}]}}]}),
])
def test_real_adapter_formats_three_official_provider_requests(
        provider, payload, monkeypatch):
    captured = []
    def fake_post(url, headers, body):
        captured.append((url, headers, body))
        return payload
    payload["responseId" if provider == "gemini" else "id"] = "test-response-123"
    monkeypatch.setattr(
        "research.inverse_formula.live_models.post_json", fake_post)
    env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "gemini": "GEMINI_API_KEY"}[provider]
    monkeypatch.setenv(env, "not-a-real-key")
    a = Agent("mathematician", provider, "configured-model")
    result = provider_call(a, "system", "user")
    assert result == '{"ok":true}'
    assert result.provider_response_id == "test-response-123"
    assert len(captured) == 1
    url, headers, body = captured[0]
    assert url.startswith("https://")
    assert body["model"] == "configured-model" if provider != "gemini" else (
        "configured-model" in url)
    assert "not-a-real-key" in json.dumps(headers)
    assert "not-a-real-key" not in json.dumps(body)


def test_consensus_and_formula_are_safe_limited_math():
    draws, _ = load_history(DATA / "ssq_2026.txt", SSQ)
    formula = parse_proposal(proposal_for("mathematician", SSQ), SSQ)
    ticket = formula_ticket(draws[:35], SSQ, formula)
    assert len(ticket["front"]) == 6
    assert len(ticket["back"]) == 1
    out = consensus([ticket], SSQ)
    assert set(out["d2_pair"]).issubset(out["front"])
