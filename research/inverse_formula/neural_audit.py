"""Verifiable six-role public decision trace, NOT private model chain-of-thought.

This research-only 'neural chain' is an explicit directed evidence graph:
independent hypothesis -> peer reviews -> veto -> formula bank -> proposed
ticket -> future eligible scoring. It does not emulate biological neurons.
A formula proposed after observing a draw is never represented as a
pre-draw historical prediction of that draw.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from research.inverse_formula.formula_bank import walk_forward_bank
from research.inverse_formula.live_council_v2 import _ranked_weight_votes
from research.inverse_formula.live_models import (
    ROLES, formula_ticket, sha, parse_agents, verify_six_gpt6_agents,
)
from research.inverse_formula.probe import Draw, Game


def verify_independent_response_ids(receipt: dict) -> None:
    """For real runs require twelve *separate* provider response identifiers.

    Response IDs are not independent cryptographic attestation of billing,
    timestamp, model identity or model reasoning. They are correlation handles.
    """
    if receipt.get("execution") != "LIVE_PROVIDER_CALLS":
        return
    ids = [item.get("provider_response_id") for group in
           ("independent_proposals", "cross_reviews")
           for item in receipt.get(group, [])]
    if (len(ids) != 12 or
            any(not isinstance(x, str) or len(x.strip()) < 6 for x in ids) or
            len(set(ids)) != 12):
        raise ValueError("live council requires 12 distinct provider response IDs")


def _check_history(prefix: list[Draw], game: Game, asof: int) -> None:
    if (len(prefix) < 31 or prefix[-1].issue != asof
            or any(prefix[i].issue != prefix[i-1].issue + 1
                   for i in range(1, len(prefix)))):
        raise ValueError("decision trace requires contiguous past-only history")


def distill_decision(receipt: dict, prefix: list[Draw], game: Game,
                     *, replay_window: int = 10) -> dict:
    """Validate the full decision graph and publish only observable evidence.

    Reviews are summaries and model-produced objections, not hidden reasoning.
    The replay below is for a PRE-EXISTING deterministic bank; it is not an
    evaluation of newly proposed models on data they have already seen.
    """
    if (replay_window < 1 or replay_window > 30
            or not isinstance(receipt, dict)
            or receipt.get("revision") != "REVIEWED_DAN_SHA_V2"
            or receipt.get("game") != game.name
            or receipt.get("target_issue") != receipt.get("asof_issue", -100) + 1
            or receipt.get("decision") != "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION"):
        raise ValueError("unsupported or invalid council decision")
    expected_sha = sha({k: v for k, v in receipt.items() if k != "sha256"})
    if receipt.get("sha256") != expected_sha:
        raise ValueError("council receipt tampered")
    _check_history(prefix, game, receipt["asof_issue"])
    if (receipt.get("guards", {}).get("formal_v47_modified") is not False
            or receipt.get("guards", {}).get("unknown_target_used") is not False
            or receipt.get("guards", {}).get("trusted_timestamp_established") is not False):
        raise ValueError("formal or future-outcome isolation guards failed")
    assignments = parse_agents(receipt.get("role_assignments"))
    verify_six_gpt6_agents(assignments)
    proposals, reviews = (receipt.get("independent_proposals"),
                          receipt.get("cross_reviews"))
    if not isinstance(proposals, list) or not isinstance(reviews, list):
        raise ValueError("missing council stages")
    if (len(proposals) != 6 or len(reviews) != 6
            or {x.get("role") for x in proposals} != set(ROLES)
            or {x.get("role") for x in reviews} != set(ROLES)):
        raise ValueError("committee is not six independently recorded roles")
    verify_independent_response_ids(receipt)
    model_for_role = {a.role: a.model for a in assignments}
    by_formula: dict[str, dict] = {}
    for p in proposals:
        role = p["role"]
        if p.get("model") != model_for_role[role] or p.get("game") != game.name:
            raise ValueError("proposal identity does not match assigned specialist")
        formula = p.get("formula")
        if not isinstance(formula, dict):
            raise ValueError("missing formula")
        identity = sha({"front": formula.get("front"), "back": formula.get("back")})[:24]
        if p.get("formula_id") != identity:
            raise ValueError("formula identity tampered")
        # The bounded interpreter is a validation boundary; no generated code.
        ticket = formula_ticket(prefix, game, formula)
        row = by_formula.setdefault(identity, {
            "formula_id": identity, "owners": [], "formula": formula,
            "ticket": ticket,
        })
        if row["formula"] != formula:
            raise ValueError("formula identity collision")
        row["owners"].append(role)
    if any(r.get("model") != model_for_role[r["role"]] for r in reviews):
        raise ValueError("review model identity mismatch")
    edge_count = 0
    per_formula_reviews = {key: [] for key in by_formula}
    for review in reviews:
        role = review["role"]
        expected = {key for key, row in by_formula.items()
                    if role not in row["owners"]}
        actual_rows = review.get("review", {}).get("reviews")
        if not isinstance(actual_rows, list):
            raise ValueError("missing structured review")
        ids = [x.get("formula_id") for x in actual_rows]
        if len(ids) != len(expected) or set(ids) != expected:
            raise ValueError("incomplete, duplicated or self-addressed peer review")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate peer review")
        if review["review"].get("cannot_certify_edge") is not True:
            raise ValueError("unproven edge must be acknowledged")
        for item in actual_rows:
            if item.get("recommendation") not in ("test", "reject", "needs_evidence"):
                raise ValueError("invalid peer recommendation")
            if not isinstance(item.get("concerns"), str):
                raise ValueError("missing peer objection")
            per_formula_reviews[item["formula_id"]].append({
                "reviewer": role,
                "decision": item["recommendation"],
                "concern": item["concerns"][:700],
            })
            edge_count += 1
    computed = []
    for key, row in sorted(by_formula.items()):
        objections = per_formula_reviews[key]
        counts = Counter(x["decision"] for x in objections)
        candidate = {
            **row,
            "review_counts": {
                "test": counts["test"],
                "needs_evidence": counts["needs_evidence"],
                "reject": counts["reject"],
            },
            "vetoed": counts["reject"] >= 3,
            "weight": max(1, 3 + 2*counts["test"] - 2*counts["reject"]),
        }
        computed.append(candidate)
    if receipt.get("candidates_with_reviewer_vetoes") != computed:
        raise ValueError("candidate decision does not match independently replayed reviews")
    accepted = [r for r in computed if not r["vetoed"]]
    if receipt.get("accepted_formula_ids") != [r["formula_id"] for r in accepted]:
        raise ValueError("accepted candidate set tampered")
    if accepted:
        if receipt.get("meeting_status") != "RESEARCH_CANDIDATE_ONLY":
            raise ValueError("candidate status mismatch")
        vote = _ranked_weight_votes(accepted, game)
        for field in ("proposed_ticket", "research_dan_sha", "vote_order",
                      "vote_counts"):
            if receipt.get(field) != vote[field]:
                raise ValueError(f"decision outcome mismatch for {field}")
    elif (receipt.get("meeting_status") != "BLOCKED_ALL_FORMULAS_VETOED"
          or "proposed_ticket" in receipt):
        raise ValueError("all-vetoed meeting must not issue a ticket")

    # This backtest uses only independently pre-defined deterministic bank
    # rules and a separate research null, not the newly proposed LLM formulas.
    start = max(30, len(prefix) - replay_window)
    baseline = walk_forward_bank(prefix, game, start=start)
    bank_summary = {k: baseline[k] for k in (
        "replay_start_issue", "replay_end_issue", "evaluated_issues",
        "exact_hits", "d2_hits", "research_null_d2_hits",
        "theoretical_d2_rate",
    )}
    registry = []
    for row in computed:
        opinions = per_formula_reviews[row["formula_id"]]
        registry.append({
            "formula_id": row["formula_id"],
            "proposed_after_issue": prefix[-1].issue,
            "first_eligible_prospective_issue": prefix[-1].issue + 1,
            "owning_experts": row["owners"],
            "hypothesis_summary": row["formula"].get("hypothesis", "")[:700],
            "bounded_formula": {k: row["formula"][k] for k in ("front", "back")},
            "peer_review_summaries": opinions,
            "review_count": len(opinions),
            "vetoed": row["vetoed"],
            "research_vote_weight": row["weight"],
            "retrospective_accuracy_is_independent": False,
            "prospective_observation_count": 0,
            "eligible_for_formal_v47": False,
        })
    trace = {
        "protocol": "SIX_ROLE_EVIDENCE_GRAPH_V1",
        "source_council_sha256": receipt["sha256"],
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "nodes": [
            {"id": agent.role, "model": agent.model,
             "function": agent.role, "reasoning_effort": agent.reasoning_effort,
             "evidence_kind": "role-specific public proposals and critiques"}
            for agent in assignments
        ],
        "edges": {
            "independent_proposal_edges": 6,
            "cross_review_edges": edge_count,
            "vetoed_formulas": sum(x["vetoed"] for x in computed),
            "accepted_formulas": len(accepted),
        },
        "formula_registry": registry,
        "decision_summary": {
            "meeting_status": receipt["meeting_status"],
            "selected_ticket": receipt.get("proposed_ticket"),
            "dan_sha": receipt.get("research_dan_sha"),
            "rules": "3 distinct external rejections veto; rest deterministic weighted vote",
            "untrusted_model_text_executed_as_code": False,
            "raw_private_model_reasoning_included": False,
        },
        "past_only_deterministic_bank_reference": bank_summary,
        "backtest_boundary": (
            "Only a pre-existing deterministic formula bank has true "
            "one-step past-only replay here. GPT formulas were generated AFTER "
            "the model saw the current data; fitting them to any earlier "
            "draw is descriptive, NOT a genuine historical validation."
        ),
        "post_draw_scoring": "ONLY for target issue after independently checked result",
        "trusted_predraw_timestamp": False,
        "claim": "RESEARCH_ONLY_NO_EDGE_UNPROVEN",
        "formal_v47_modified": False,
    }
    trace["sha256"] = sha(trace)
    return trace
