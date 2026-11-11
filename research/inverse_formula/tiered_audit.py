"""Independently replay deterministic parts of a tiered GPT council.

No model's private chain-of-thought is requested or revealed. This
audit can verify formulas, shortlist selection, Astra verdict processing,
number voting and provenance claims, not whether the formulas predict
random future lottery draws.
"""
from __future__ import annotations

import json

from research.inverse_formula.live_models import (
    part, parse_proposal, formula_ticket, sha, parse_agents,
)
from research.inverse_formula.live_council_v2 import _parse_review, _ranked_weight_votes
from research.inverse_formula.tiered_council import (
    PROPOSER_ROLES, REVIEW_ROLE, complexity, reduce_review, shortlist,
    verify_tiered_agents,
)
from research.inverse_formula.probe import Draw, Game, compare
from research.inverse_formula.formula_bank import walk_forward_bank



def independent_bank_and_descriptive_formula_diagnostic(
        prefix: list[Draw], game: Game, proposals: list[dict],
        window: int = 10) -> dict:
    """No-cost Python replay with explicit selection-time boundary.

    Fixed deterministic bank: each prediction at issue i used only earlier
    draws (past-only). Newly GPT-proposed formulas: fixed formulas are applied
    using earlier inputs but were selected AFTER seeing ALL these outcomes.
    Their retrospective success is post-selection diagnostics, NOT independent
    held-out evidence or a predictive superiority claim.
    """
    start = max(30, len(prefix) - window)
    bank = walk_forward_bank(prefix, game, start=start)
    reference = {key: bank[key] for key in (
        "game", "replay_start_issue", "replay_end_issue",
        "evaluated_issues", "exact_hits", "d2_hits",
        "research_null_d2_hits", "theoretical_d2_rate",
    )}
    diagnostics = []
    seen = set()
    for row in proposals:
        if row["formula_id"] in seen:
            continue
        seen.add(row["formula_id"])
        exact = d2 = 0
        for i in range(start, len(prefix)):
            ticket = formula_ticket(prefix[:i], game, row["formula"])
            comparison = compare(
                (tuple(ticket["front"]), tuple(ticket["back"])), prefix[i])
            exact += comparison["full"]
            d2 += int(set(ticket["front"][:2]).issubset(prefix[i].front))
        diagnostics.append({
            "formula_id": row["formula_id"],
            "observed_earlier_issues": len(prefix) - start,
            "retrospective_exact": exact,
            "retrospective_d2": d2,
            "interpretation": "POST_SELECTION_DESCRIPTIVE_NOT_INDEPENDENT",
            "prospective_issues_scored": 0,
            "used_for_current_formula_selection": False,
        })
    return {
        "independent_past_only_deterministic_bank": reference,
        "gpt_formula_retrospective_descriptive_only": diagnostics,
        "model_formula_independent_validation": "NOT_PERFORMED",
        "fixed_random_null_formal_v47_used": False,
    }


def distill_tiered_decision(receipt: dict, prefix: list[Draw],
                            game: Game) -> dict:
    if (receipt.get("revision") != "TIERED_REVIEWED_DAN_SHA_V3"
            or receipt.get("protocol") != "MULTI_PROVIDER_FORMULA_COUNCIL_V1"
            or receipt.get("game") != game.name
            or receipt.get("decision") != "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION"
            or receipt.get("asof_issue") != prefix[-1].issue
            or receipt.get("target_issue") != prefix[-1].issue + 1
            or len(prefix) < 30
            or any(prefix[i].issue != prefix[i-1].issue + 1
                   for i in range(1, len(prefix)))):
        raise ValueError("invalid council protocol / future cutoff")
    if receipt.get("sha256") != sha({
            k: v for k, v in receipt.items() if k != "sha256"}):
        raise ValueError("council receipt hash mismatch")
    guard = receipt.get("guards", {})
    if (guard.get("unknown_target_used") is not False
            or guard.get("model_generated_code_executed") is not False
            or guard.get("formal_v47_modified") is not False
            or guard.get("trusted_timestamp_established") is not False):
        raise ValueError("research isolation boundary failed")
    agents = parse_agents(receipt.get("role_assignments"))
    verify_tiered_agents(agents)
    roles = {a.role: a for a in agents}
    proposals = receipt.get("independent_proposals")
    reviews = receipt.get("cross_reviews")
    if (not isinstance(proposals, list) or len(proposals) != 5
            or [x.get("role") for x in proposals] != list(PROPOSER_ROLES)
            or not isinstance(reviews, list) or len(reviews) != 1
            or reviews[0].get("role") != REVIEW_ROLE):
        raise ValueError("specialist stages incomplete")
    validated = []
    for row in proposals:
        role = row["role"]
        if row.get("game") != game.name or row.get("model") != roles[role].model:
            raise ValueError("proposal model identity mismatch")
        f = row.get("formula")
        if not isinstance(f, dict):
            raise ValueError("malformed formula")
        validated_formula = parse_proposal(
            json.dumps(f, ensure_ascii=False), game)
        if validated_formula != f:
            raise ValueError("formula canonical schema mismatch")
        identity = sha({"front": f["front"], "back": f["back"]})[:24]
        if row.get("formula_id") != identity:
            raise ValueError("proposal ID mismatch")
        if row.get("ticket") != formula_ticket(prefix, game, f):
            # JSON artifact roundtrips tuples -> lists, so comparison is
            # normalized structurally instead of relying on tuple equality.
            normalized = {k: list(v) for k, v in
                          formula_ticket(prefix, game, f).items()}
            if row.get("ticket") != normalized:
                raise ValueError("proposal ticket mismatch")
        validated.append(row)
    filtered, trace = shortlist(validated)
    if trace != receipt.get("structural_shortlist_audit"):
        raise ValueError("shortlist was altered")
    reviewer = reviews[0]
    if reviewer.get("model") != roles[REVIEW_ROLE].model:
        raise ValueError("wrong Astra reviewer identity")
    parsed = _parse_review(
        json.dumps(reviewer.get("review")),
        {x["formula_id"] for x in filtered},
    )
    if parsed != reviewer["review"]:
        raise ValueError("review changed after parsing")
    accepted = reduce_review(filtered, parsed["reviews"])
    if receipt.get("accepted_formula_ids") != [
            x["formula_id"] for x in accepted]:
        raise ValueError("accepted formula list altered")
    if accepted:
        if receipt.get("meeting_status") != "RESEARCH_CANDIDATE_ONLY":
            raise ValueError("invalid candidate status")
        tally = _ranked_weight_votes(accepted, game)
        for name in ("proposed_ticket", "research_dan_sha",
                     "vote_order", "vote_counts"):
            if receipt.get(name) != tally[name]:
                raise ValueError("number vote mismatch: " + name)
    elif (receipt.get("meeting_status") != "BLOCKED_ALL_FORMULAS_VETOED"
          or "proposed_ticket" in receipt):
        raise ValueError("all vetoes must prohibit prediction output")
    if receipt.get("execution") == "LIVE_PROVIDER_CALLS":
        ids = [r.get("provider_response_id") for r in proposals + reviews]
        if len(ids) != 6 or any(
                not isinstance(x, str) or not x.startswith("resp_")
                for x in ids) or len(set(ids)) != 6:
            raise ValueError("six unique live response IDs required")
    else:
        if receipt.get("execution") != "INJECTED_MOCK_TRANSPORT_TEST_ONLY":
            raise ValueError("unknown execution identity")
    trace_body = {
        "protocol": "SIX_SPECIALIST_TIERED_EVIDENCE_GRAPH_V1",
        "source_council_sha256": receipt["sha256"],
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "specialists": [
            {"role": a.role, "model": a.model,
             "phase": ("EXPENSIVE_ASTRA_REVIEW" if a.role == REVIEW_ROLE
                       else "LOW_COST_FORMULA_PROPOSAL"),
             "effort": a.reasoning_effort}
            for a in agents
        ],
        "independently_called_low_cost_proposers": len(proposals),
        "reviewers": 1,
        "proposal_catalog": [{
            "formula_id": r["formula_id"],
            "owner_role": r["role"],
            "model": r["model"],
            "hypothesis_summary": r["formula"]["hypothesis"],
            "bounded_formula": {
                "front": r["formula"]["front"], "back": r["formula"]["back"]
            },
            "complexity": complexity(r["formula"]),
            "proposed_after_issue": prefix[-1].issue,
            "first_eligible_prospective_issue": prefix[-1].issue+1,
            "independent_historical_hit_rate": None,
        } for r in proposals],
        "shortlist": trace,
        "astra_review": parsed["reviews"],
        "rejected_by_astra": [
            x["formula_id"] for x in parsed["reviews"]
            if x["recommendation"] == "reject"
        ],
        "accepted_formula_ids": receipt["accepted_formula_ids"],
        "selected_research_ticket": receipt.get("proposed_ticket"),
        "selected_dan_sha": receipt.get("research_dan_sha"),
        "decision": "UNPROVEN_PREDICTIVE_ADVANTAGE_NO_EDGE",
        "prospective_results_count": 0,
        "classification": (
            "No retrospective score of newly GPT-proposed formulas may be "
            "called independent. Officially sourced future draws are needed."
        ),
        "python_deterministic_calculation": True,
        "python_historical_audit": independent_bank_and_descriptive_formula_diagnostic(
            prefix, game, validated),
        "raw_private_model_reasoning_included": False,
        "formal_v47_modified": False,
        "trusted_predraw_timestamp": False,
    }
    trace_body["sha256"] = sha(trace_body)
    return trace_body
