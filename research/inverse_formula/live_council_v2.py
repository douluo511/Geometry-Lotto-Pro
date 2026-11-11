"""Two-round, six independently called GPT-6 specialist council with vetoes.

Research-only, no forecasting-edge assertion and no V4.7 writes. The model
produces bounded declarative formulas; Python validates them. Reviews affect
eligibility and weights BEFORE any next-issue recommendation is produced.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from typing import Callable

from research.inverse_formula.live_models import (
    Agent, ROLES, parallel, parse_agents, parse_json, parse_proposal,
    formula_ticket, proposal_prompt, provider_call, require_keys,
    verify_six_gpt6_agents, sha,
)
from research.inverse_formula.probe import Draw, Game

Transport = Callable[[Agent, str, str], str]


def _review_prompt(agent: Agent, prefix: list[Draw], proposals: list[dict]) -> str:
    peers = [
        {"role": p["role"], "formula_id": p["formula_id"],
         "hypothesis": p["formula"]["hypothesis"],
         "front": p["formula"]["front"], "back": p["formula"]["back"]}
        for p in proposals if p["role"] != agent.role
    ]
    return json.dumps({
        "task": "independently scrutinize each peer formula; one assessment per formula_id",
        "role": agent.role,
        "game": proposals[0]["game"],
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "untrusted_peer_formulas": peers,
        "instruction": ("Examine leakage, overfitting, validity and baseline."
                        " The recommendation 'test' is not proof of edge."
                        " Return JSON only. Review every other distinct formula ID."),
        "JSON_only_shape": {
            "reviews": [{"formula_id": "copy each peer formula_id",
                         "recommendation": "needs_evidence",
                         "concerns": "one concise falsifiable objection"}],
            "cannot_certify_edge": True,
        },
        "options": ["test", "needs_evidence", "reject"],
    }, ensure_ascii=False)


def _parse_review(raw: str, expected: set[str]) -> dict:
    value = parse_json(raw)
    if set(value) != {"reviews", "cannot_certify_edge"} or value["cannot_certify_edge"] is not True:
        raise ValueError("independent critique must not certify prediction edge")
    rows = value["reviews"]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("review must cover all distinct peer formula IDs")
    seen: set[str] = set()
    cleaned = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"formula_id", "recommendation", "concerns"}:
            raise ValueError("review row schema mismatch")
        identity = row["formula_id"]
        if not isinstance(identity, str) or identity not in expected or identity in seen:
            raise ValueError("unexpected or duplicate formula ID in critique")
        if row["recommendation"] not in ("test", "needs_evidence", "reject"):
            raise ValueError("invalid independent review recommendation")
        if not isinstance(row["concerns"], str) or not 1 <= len(row["concerns"].strip()) <= 700:
            raise ValueError("invalid review evidence")
        seen.add(identity)
        cleaned.append({**row, "concerns": row["concerns"].strip()})
    if seen != expected:
        raise ValueError("incomplete cross-critique")
    return {"reviews": cleaned, "cannot_certify_edge": True}


def _ranked_weight_votes(candidates: list[dict], game: Game) -> dict:
    if not candidates:
        raise ValueError("all formulas rejected by veto quorum")
    votes = {"front": defaultdict(int), "back": defaultdict(int)}
    for row in candidates:
        for side in ("front", "back"):
            for n in row["ticket"][side]:
                votes[side][n] += row["weight"]
    orders = {
        "front": sorted(range(1, game.front_max + 1),
                        key=lambda n: (-votes["front"][n], n)),
        "back": sorted(range(1, game.back_max + 1),
                       key=lambda n: (-votes["back"][n], n)),
    }
    selected = {
        "front": sorted(orders["front"][:game.front_pick]),
        "back": sorted(orders["back"][:game.back_pick]),
    }
    selected["d2_pair"] = sorted(orders["front"][:2])
    # These are named research selections, NOT guaranteed inclusions/exclusions.
    front_dan = sorted(orders["front"][:2])
    front_sha = sorted(orders["front"][-8:])
    back_dan = sorted(orders["back"][:1])
    back_sha = sorted(orders["back"][-(3 if game.name == "SSQ" else 2):])
    if (set(front_dan) & set(front_sha)
            or set(back_dan) & set(back_sha)
            or not set(front_dan).issubset(selected["front"])
            or set(front_sha) & set(selected["front"])
            or set(back_sha) & set(selected["back"])):
        raise AssertionError("dan/sha research lists must be disjoint")
    return {
        "proposed_ticket": selected,
        "research_dan_sha": {
            "front_dan": front_dan,
            "front_sha": front_sha,
            "back_dan": back_dan,
            "back_sha": back_sha,
            "meaning": ("Heuristic keep/exclude candidate only; "
                        "no number has a proven inclusion/exclusion advantage."),
        },
        "vote_order": orders,
        "vote_counts": {
            side: [[n, votes[side][n]] for n in orders[side]]
            for side in ("front", "back")
        },
    }


def run_reviewed_council(prefix: list[Draw], game: Game, agents: tuple[Agent, ...],
                         *, transport: Transport | None = None,
                         live_authorized: bool = False) -> dict:
    agents = parse_agents([asdict(a) for a in agents])
    verify_six_gpt6_agents(agents)
    if (len(prefix) < 30 or any(prefix[i].issue != prefix[i-1].issue + 1
                                for i in range(1, len(prefix)))):
        raise ValueError("require at least 30 contiguous known issues")
    real = transport is None
    if real:
        if live_authorized is not True:
            raise PermissionError("paid model calls require explicit --live authorization")
        require_keys(agents)
        transport = provider_call
    assert transport is not None
    raw_proposals = parallel(
        agents, lambda a: proposal_prompt(a, prefix, game), transport)
    proposals = []
    for agent in agents:
        result = raw_proposals[agent.role]
        formula = parse_proposal(result, game)
        formula_id = sha({"front": formula["front"],
                          "back": formula["back"]})[:24]
        proposals.append({
            "game": game.name, "role": agent.role, "model": agent.model,
            "formula_id": formula_id, "formula": formula,
            "response_sha256": hashlib.sha256(result.encode()).hexdigest(),
            "provider_response_id": getattr(result, "provider_response_id", None),
        })
    raw_reviews = parallel(
        agents, lambda a: _review_prompt(a, prefix, proposals), transport)
    reviews = []
    for agent in agents:
        result = raw_reviews[agent.role]
        expected = {r["formula_id"] for r in proposals
                    if r["role"] != agent.role}
        parsed = _parse_review(result, expected)
        reviews.append({
            "role": agent.role, "model": agent.model, "review": parsed,
            "response_sha256": hashlib.sha256(result.encode()).hexdigest(),
            "provider_response_id": getattr(result, "provider_response_id", None),
        })
    distinct: dict[str, dict] = {}
    for p in proposals:
        row = distinct.setdefault(p["formula_id"], {
            "formula_id": p["formula_id"], "owners": [],
            "formula": p["formula"], "ticket": formula_ticket(prefix, game, p["formula"]),
        })
        row["owners"].append(p["role"])
    eligibility = []
    for key, row in sorted(distinct.items()):
        votes = [
            review for r in reviews if r["role"] not in row["owners"]
            for review in r["review"]["reviews"] if review["formula_id"] == key
        ]
        counts = {name: sum(v["recommendation"] == name for v in votes)
                  for name in ("test", "needs_evidence", "reject")}
        # Three independent cross-review objections constitute a hard veto.
        row["review_counts"] = counts
        row["vetoed"] = counts["reject"] >= 3
        row["weight"] = max(1, 3 + 2*counts["test"] - 2*counts["reject"])
        eligibility.append(row)
    accepted = [r for r in eligibility if not r["vetoed"]]
    decision = {
        "protocol": "MULTI_PROVIDER_FORMULA_COUNCIL_V1",
        "revision": "REVIEWED_DAN_SHA_V2",
        "execution": ("LIVE_PROVIDER_CALLS" if real
                      else "INJECTED_MOCK_TRANSPORT_TEST_ONLY"),
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "history_shown": min(len(prefix), 30),
        "role_assignments": [asdict(a) for a in agents],
        "independent_proposals": proposals,
        "cross_reviews": reviews,
        "candidates_with_reviewer_vetoes": eligibility,
        "accepted_formula_ids": [r["formula_id"] for r in accepted],
        "veto_rule": "reject_count >= 3 unique external specialist roles",
        "decision": "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION",
        "guards": {
            "unknown_target_used": False,
            "model_generated_code_executed": False,
            "formal_v47_modified": False,
            "trusted_timestamp_established": False,
        },
    }
    if not accepted:
        # Never invent a fallback winning ticket after universal objections.
        decision["meeting_status"] = "BLOCKED_ALL_FORMULAS_VETOED"
    else:
        decision["meeting_status"] = "RESEARCH_CANDIDATE_ONLY"
        decision.update(_ranked_weight_votes(accepted, game))
    decision["sha256"] = sha(decision)
    return decision
