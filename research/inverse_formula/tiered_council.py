"""Cost-tiered six-specialist research decision flow.

Five cheaper specialist proposal calls -> deterministic syntax/complexity/
diversity filter -> ONE Astra peer review of shortlisted formulas -> pure
Python vote, dan/sha. No LLM is used to compute or seal final numbers.
Astra never receives unfiltered, invalid model-generated code.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from research.inverse_formula.api_budget import BudgetGuard, ModelAnswer
from research.inverse_formula.live_models import (
    Agent, ROLES, parse_agents, parse_proposal, proposal_prompt,
    formula_ticket, sha, verify_six_gpt6_agents,
)
from research.inverse_formula.live_council_v2 import (
    _parse_review, _ranked_weight_votes,
)
from research.inverse_formula.probe import Draw, Game

PROPOSER_ROLES = (
    "mathematician", "formula_discovery", "ensemble_researcher",
    "statistician", "engineer",
)
REVIEW_ROLE = "skeptical_reviewer"
MAX_SHORTLIST = 3
MAX_TOTAL_CALLS_TWO_GAMES = 12


def verify_tiered_agents(agents: tuple[Agent, ...]) -> None:
    verify_six_gpt6_agents(agents)
    by_role = {a.role: a for a in agents}
    if by_role[REVIEW_ROLE].model != "gpt-6-astra":
        raise ValueError("Astra must be reserved for skeptical reviewer")
    if any(by_role[role].model == "gpt-6-astra" for role in PROPOSER_ROLES):
        raise ValueError("expensive Astra cannot propose in first round")
    if any(a.reasoning_effort != "high" for a in agents):
        raise ValueError("research roles must use high reasoning effort")
    if len({a.role for a in agents}) != 6:
        raise ValueError("six unique specialist roles required")


def complexity(formula: dict) -> int:
    """Deterministic non-predictive complexity penalty; never uses outcomes."""
    return sum(
        len(formula[side]["lags"])
        + sum(abs(x) for x in formula[side]["coefficients"])
        + abs(formula[side]["issue_coefficient"])
        for side in ("front", "back")
    )


def shortlist(proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use structural validity and complexity, not selected historical wins."""
    found: dict[str, dict] = {}
    for row in proposals:
        k = row["formula_id"]
        if k in found:
            found[k]["owners"].append(row["role"])
        else:
            found[k] = {
                "formula_id": k, "formula": row["formula"],
                "ticket": row["ticket"], "owners": [row["role"]],
                "complexity": complexity(row["formula"]),
            }
    ranked = sorted(found.values(), key=lambda x: (
        x["complexity"], x["formula_id"]))
    admitted = ranked[:MAX_SHORTLIST]
    trace = [
        {"formula_id": r["formula_id"], "owners": r["owners"],
         "complexity": r["complexity"], "shortlisted": i < MAX_SHORTLIST,
         "filter_reason": ("STRUCTURAL_COMPLEXITY_TOP_K" if i < MAX_SHORTLIST
                           else "EXCLUDED_TOP_K_LIMIT"),
         "past_outcomes_used_to_rank": False}
        for i, r in enumerate(ranked)
    ]
    return admitted, trace


def astra_prompt(prefix: list[Draw], game: Game,
                 candidates: list[dict]) -> str:
    return json.dumps({
        "task": "review shortlisted formulas, rejecting unsupported hypotheses",
        "reviewer": REVIEW_ROLE,
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue+1,
        "candidates": [
            {"formula_id": c["formula_id"], "owners": c["owners"],
             "formula": {side: c["formula"][side]
                         for side in ("front", "back")},
             "hypothesis": c["formula"]["hypothesis"],
             "complexity": c["complexity"],
             "ticket": c["ticket"]}
            for c in candidates
        ],
        "instruction": (
            "Apply skeptical, adversarial standards to all shortlisted IDs. "
            "Assess data leakage, arbitrary formula choices, selection bias, "
            "inadequate prospective evidence. Return one verdict per ID. "
            "No prediction advantage is proven. Output JSON only."
        ),
        "JSON_only_example": {
            "reviews": [{
                "formula_id": "copy ID exactly",
                "recommendation": "needs_evidence",
                "concerns": "specific independent test needed",
            }],
            "cannot_certify_edge": True,
        },
        "valid_recommendations": ["test", "needs_evidence", "reject"],
    }, ensure_ascii=False)


def reduce_review(candidates: list[dict], reviews: list[dict]) -> list[dict]:
    by_id = {row["formula_id"]: row for row in reviews}
    accepted: list[dict] = []
    for row in candidates:
        verdict = by_id[row["formula_id"]]["recommendation"]
        if verdict == "reject":
            continue
        accepted.append({
            **row, "review_counts": {
                "test": int(verdict == "test"),
                "needs_evidence": int(verdict == "needs_evidence"),
                "reject": 0,
            },
            "vetoed": False,
            "weight": (3 if verdict == "test" else 1),
        })
    return accepted


def run_tiered_council(prefix: list[Draw], game: Game,
                       agents: tuple[Agent, ...], budget: BudgetGuard, *,
                       transport=None) -> dict:
    """Each external response consumes one guarded budget slot, no retries."""
    agents = parse_agents([asdict(a) for a in agents])
    verify_tiered_agents(agents)
    if (len(prefix) < 30 or
            any(prefix[i].issue != prefix[i-1].issue+1
                for i in range(1, len(prefix)))):
        raise ValueError("requires past-only contiguous draw prefix")
    assigned = {a.role: a for a in agents}
    real = transport is None
    proposals: list[dict] = []
    # No parallel requests: a budget check takes place after each reported
    # usage and before the next billable call.
    for role in PROPOSER_ROLES:
        agent = assigned[role]
        answer = budget.call(agent, proposal_prompt(agent, prefix, game),
                             transport=transport)
        formula = parse_proposal(answer.text, game)
        proposals.append({
            "role": role, "model": agent.model, "game": game.name,
            "formula_id": sha({"front": formula["front"],
                               "back": formula["back"]})[:24],
            "formula": formula,
            "ticket": formula_ticket(prefix, game, formula),
            "provider_response_id": answer.response_id,
            "response_sha256": hashlib.sha256(answer.text.encode()).hexdigest(),
        })
    filtered, filtering = shortlist(proposals)
    if not filtered:
        raise RuntimeError("no structurally eligible formula")
    astra = assigned[REVIEW_ROLE]
    review_reply = budget.call(astra, astra_prompt(prefix, game, filtered),
                               transport=transport)
    parsed = _parse_review(
        review_reply.text, {x["formula_id"] for x in filtered})
    reviewer = {
        "role": REVIEW_ROLE, "model": astra.model,
        "review": parsed,
        "provider_response_id": review_reply.response_id,
        "response_sha256": hashlib.sha256(
            review_reply.text.encode()).hexdigest(),
    }
    accepted = reduce_review(filtered, parsed["reviews"])
    receipt = {
        "protocol": "MULTI_PROVIDER_FORMULA_COUNCIL_V1",
        "revision": "TIERED_REVIEWED_DAN_SHA_V3",
        "execution": ("LIVE_PROVIDER_CALLS" if real
                      else "INJECTED_MOCK_TRANSPORT_TEST_ONLY"),
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "history_shown": min(len(prefix), 30),
        "role_assignments": [asdict(a) for a in agents],
        "independent_proposals": proposals,
        "structural_shortlist_audit": filtering,
        "cross_reviews": [reviewer],
        "accepted_formula_ids": [x["formula_id"] for x in accepted],
        "veto_rule": "Astra rejects a shortlisted formula; no paid reruns",
        "selection_rule": "complexity_top_3 then Astra verdict then Python vote",
        "decision": "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION",
        "guards": {
            "unknown_target_used": False,
            "model_generated_code_executed": False,
            "formal_v47_modified": False,
            "trusted_timestamp_established": False,
        },
    }
    if accepted:
        receipt["meeting_status"] = "RESEARCH_CANDIDATE_ONLY"
        receipt.update(_ranked_weight_votes(accepted, game))
    else:
        receipt["meeting_status"] = "BLOCKED_ALL_FORMULAS_VETOED"
    receipt["sha256"] = sha(receipt)
    return receipt
