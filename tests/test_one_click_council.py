"""No-cost tests for official-source synchronization and two-round review."""
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from research.inverse_formula.probe import SSQ, DLT, load_history
from research.inverse_formula.live_models import parse_agents
from research.inverse_formula.live_council_v2 import (
    run_reviewed_council, _parse_review,
)
from research.inverse_formula.fresh_history import (
    parse_official_rows, sync_fixture, expected_last_published_date,
)
from research.inverse_formula.closure import preflight, freeze, verify_digest
from research.inverse_formula.one_click import main, prepare_all

ROOT = Path(__file__).parents[1] / "research" / "inverse_formula"
AGENTS = parse_agents(json.loads((ROOT / "multi_provider_agents.example.json").read_text()))
CHINA = ZoneInfo("Asia/Shanghai")
SSQ_HTML = """
<table><tr><th>期号</th></tr>
<tr><td>2026129</td><td>2026-11-10(二)</td><td>030916202530</td><td>05</td></tr>
<tr><td>2026128</td><td>2026-11-08(日)</td><td>050610252730</td><td>11</td></tr>
</table>
"""
DLT_HTML = """
<table><tr><th>发布日期</th><th>期号</th></tr>
<tr><td>2026-11-09</td><td>26128</td><td>03 13 20 25 34 09 12</td></tr>
<tr><td>2026-11-07</td><td>26127</td><td>05 06 17 18 27 03 12</td></tr>
</table>
"""


@pytest.mark.parametrize("game,html,expected", [
    (SSQ, SSQ_HTML, 2026129),
    (DLT, DLT_HTML, 26128),
])
def test_official_parsing_matches_known_current_rows(game, html, expected):
    found = parse_official_rows(html, game)
    assert found[-1]["issue"] == expected
    assert len(found) == 2


def test_source_sync_validates_last_published_and_staleness(tmp_path):
    now = datetime(2026, 11, 11, 12, tzinfo=CHINA)
    for game, name, html, target in (
        (SSQ, "ssq", SSQ_HTML, 2026130),
        (DLT, "dlt", DLT_HTML, 26129),
    ):
        dest = tmp_path / (name + ".txt")
        audit = sync_fixture(ROOT / f"{name}_2026.txt", game, dest,
                             html=html, now=now)
        assert audit["target_issue"] == target
        assert audit["new_issues"] == 0
        assert audit["verified_overlap_count"] == 2
        assert load_history(dest, game)[0][-1].issue == target - 1
        with pytest.raises(FileExistsError):
            sync_fixture(ROOT / f"{name}_2026.txt", game, dest,
                         html=html, now=now)
    future = datetime(2026, 11, 13, 12, tzinfo=CHINA)
    with pytest.raises(ValueError, match="stale"):
        sync_fixture(ROOT / "ssq_2026.txt", SSQ, tmp_path / "stale.txt",
                     html=SSQ_HTML, now=future)


def test_contiguous_append_rejects_gaps_and_conflicts(tmp_path):
    new_ssq = SSQ_HTML.replace("</table>", (
        "<tr><td>2026130</td><td>2026-11-12(四)</td>"
        "<td>010203041122</td><td>13</td></tr></table>"))
    now = datetime(2026, 11, 12, 23, tzinfo=CHINA)
    dest = tmp_path / "appended.txt"
    info = sync_fixture(ROOT / "ssq_2026.txt", SSQ, dest,
                        html=new_ssq, now=now)
    assert info["asof_issue"] == 2026130
    assert info["new_issues"] == 1
    conflict = SSQ_HTML.replace("030916202530", "010203041122")
    with pytest.raises(ValueError, match="conflicts"):
        sync_fixture(ROOT / "ssq_2026.txt", SSQ, tmp_path / "bad.txt",
                     html=conflict, now=datetime(2026, 11, 11, 12, tzinfo=CHINA))
    gap = new_ssq.replace("2026130", "2026131").replace("2026-11-12", "2026-11-15")
    with pytest.raises(ValueError, match="missing consecutive"):
        sync_fixture(ROOT / "ssq_2026.txt", SSQ, tmp_path / "gap.txt",
                     html=gap, now=datetime(2026, 11, 15, 23, tzinfo=CHINA))


def mock_transport(review_mode="normal"):
    calls = []
    def transport(agent, system, prompt):
        body = json.loads(prompt)
        calls.append((agent.role, body))
        if body["task"].startswith("independently propose"):
            index = [a.role for a in AGENTS].index(agent.role)
            return json.dumps({
                "hypothesis": "bounded role-specific lag recurrence",
                "front": {"lags": [1], "coefficients": [1],
                          "bias": index, "issue_coefficient": 0},
                "back": {"lags": [1], "coefficients": [1],
                         "bias": index % 12, "issue_coefficient": 0},
                "limitation": "no proof of out-of-sample predictive advantage",
            })
        assert body["task"].startswith("independently scrutinize")
        assert len(body["untrusted_peer_formulas"]) == 5
        seen = {}
        for p in body["untrusted_peer_formulas"]:
            # Reject the engineer's formula through independent cross-reviews.
            recommendation = ("reject" if (
                review_mode == "all_reject" or p["role"] == "engineer"
            ) else "needs_evidence")
            seen[p["formula_id"]] = {
                "formula_id": p["formula_id"],
                "recommendation": recommendation,
                "concerns": "no valid independent prospective holdout",
            }
        return json.dumps({"reviews": list(seen.values()),
                           "cannot_certify_edge": True})
    return transport, calls


def test_six_gpt_propose_review_veto_and_dan_sha_seal():
    rows, sha = load_history(ROOT / "ssq_2026.txt", SSQ)
    mock, calls = mock_transport()
    report = run_reviewed_council(rows, SSQ, AGENTS, transport=mock)
    assert len(calls) == 12
    assert len(report["independent_proposals"]) == 6
    assert len(report["cross_reviews"]) == 6
    assert report["meeting_status"] == "RESEARCH_CANDIDATE_ONLY"
    engineer = next(c for c in report["candidates_with_reviewer_vetoes"]
                    if "engineer" in c["owners"])
    assert engineer["vetoed"] is True
    assert len(report["accepted_formula_ids"]) == 5
    rec = report["research_dan_sha"]
    p = report["proposed_ticket"]
    assert set(rec["front_dan"]).issubset(p["front"])
    assert not (set(rec["front_sha"]) & set(p["front"]))
    assert not (set(rec["back_sha"]) & set(p["back"]))
    live_claim = copy.deepcopy(report)
    live_claim["execution"] = "LIVE_PROVIDER_CALLS"
    live_claim["source_sha256"] = sha
    from research.inverse_formula.live_models import sha as canonical
    live_claim["sha256"] = canonical({
        k: v for k, v in live_claim.items() if k != "sha256"})
    pre = preflight(ROOT / "ssq_2026.txt",
                    ROOT / "multi_provider_agents.example.json", SSQ)
    seal = freeze(pre, live_claim, SSQ)
    verify_digest(seal)
    assert seal["research_dan_sha"]["front_dan"] == rec["front_dan"]


def test_vetoes_block_unfounded_ticket():
    rows, _ = load_history(ROOT / "dlt_2026.txt", DLT)
    mock, _ = mock_transport("all_reject")
    decision = run_reviewed_council(rows, DLT, AGENTS, transport=mock)
    assert decision["meeting_status"] == "BLOCKED_ALL_FORMULAS_VETOED"
    assert "proposed_ticket" not in decision
    assert "research_dan_sha" not in decision


def test_no_keys_no_paid_calls_and_bad_reviews_fail_closed(
        monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SSQDLT_PAID_APPROVED", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "one_click", "--live", "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert not (tmp_path / "out").exists()
    with pytest.raises(ValueError, match="review"):
        _parse_review('{"reviews":[],"cannot_certify_edge":true}', {"abc"})


def test_both_game_prechecks_before_any_provider_call(tmp_path, monkeypatch):
    from research.inverse_formula import fresh_history
    def fake_fetch(game):
        return (SSQ_HTML if game.name == "SSQ" else DLT_HTML), "f" * 64
    monkeypatch.setattr(fresh_history, "fetch_official_html", fake_fetch)
    monkeypatch.setattr(fresh_history, "expected_last_published_date",
                        lambda game, now: datetime(
                            2026, 11, 9 if game.name == "DLT" else 10,
                            tzinfo=CHINA).date())
    prepared = prepare_all(tmp_path)
    assert set(prepared) == {"ssq", "dlt"}
    assert all((tmp_path / f"{g}-preflight.json").exists()
               for g in ("ssq", "dlt"))
    assert all(x["preflight"]["model_requests"] == 0 for x in prepared.values())
