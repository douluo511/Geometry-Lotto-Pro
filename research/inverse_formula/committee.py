"""Six-role, deterministic research committee for inverse-formula experiments.

This is an auditable role-based orchestration prototype, NOT six independently
running LLMs. It imports only research modules; it does not write into formal
V4.7 predictors, fixed NULL, seeds, or frozen ledgers.

For a decision at issue T, every candidate uses only issues through T-1.
An internal rolling replay is descriptive and is not independent prospective
evidence; no automatic promotion is allowed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from research.inverse_formula.formula_bank import (
    catalog, predict_with_bank,
)
from research.inverse_formula.probe import (
    DLT, SSQ, Draw, Game, compare, load_history,
)
from research.inverse_formula.reverse_search import (
    METHODS, apply_formula, select_from_past,
)

ROLE_NAMES = (
    "mathematician", "formula_discovery", "ensemble_researcher",
    "statistician", "skeptical_reviewer", "engineer",
)
SEED_RESEARCH_NULL = 20261111


def canonical_hash(value: object) -> str:
    """Hash a canonical JSON receipt; this is not trusted timestamping."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def research_null(issue: int, game: Game) -> dict:
    """Issue-keyed independent control; accepts NO outcome or future history."""
    rng = random.Random(
        SEED_RESEARCH_NULL + issue + (100000 if game.name == "SSQ" else 200000)
    )
    two = tuple(sorted(rng.sample(range(1, game.front_max + 1), 2)))
    remaining = [i for i in range(1, game.front_max + 1) if i not in two]
    front = tuple(sorted(two + tuple(rng.sample(remaining, game.front_pick - 2))))
    back = tuple(sorted(rng.sample(range(1, game.back_max + 1), game.back_pick)))
    return {"front": front, "back": back, "d2_pair": two}


def _check_history(prefix: list[Draw], min_size: int = 31) -> None:
    if len(prefix) < min_size:
        raise ValueError(f"at least {min_size} past draws are required")
    if any(prefix[i].issue != prefix[i - 1].issue + 1
           for i in range(1, len(prefix))):
        raise ValueError("history must be strictly consecutive")
    if len({x.issue for x in prefix}) != len(prefix):
        raise ValueError("duplicate history issues")


def _score_pair(ticket: dict, actual: Draw) -> dict:
    front, back = tuple(ticket["front"]), tuple(ticket["back"])
    two = tuple(ticket["d2_pair"])
    if len(two) != 2 or not set(two).issubset(front):
        raise ValueError("D2 must be exactly two distinct selected front balls")
    metric = compare((front, back), actual)
    return {
        "exact": metric["full"],
        "d2": int(set(two).issubset(actual.front)),
        "front_hits": metric["front_hits"],
    }


def _single_candidate(prefix: list[Draw], game: Game) -> dict:
    formula, support = select_from_past(prefix, game)
    front, back = apply_formula(formula, prefix, game)
    return {
        "front": front,
        "back": back,
        "d2_pair": front[:2],
        "family": formula.method,
        "formula_anchor_issue": prefix[formula.anchor_index].issue,
        "selection_evidence": support,
    }


def audit_recent_past(prefix: list[Draw], game: Game, window: int = 10) -> dict:
    """Compare FIXED research strategies on earlier one-step forecasts.

    The replay cannot infer the target outcome before choosing any candidate.
    When used to motivate future adjustments, the replay is exploratory and
    is NOT a fresh independent test of the proposed modifications.
    """
    _check_history(prefix)
    if window < 1:
        raise ValueError("window must be positive")
    start = max(30, len(prefix) - window)
    totals = {
        name: {"d2": 0, "exact": 0, "front_hits": 0}
        for name in ("ensemble", "single", "research_null")
    }
    trials = []
    for idx in range(start, len(prefix)):
        prior = prefix[:idx]
        actual = prefix[idx]  # Read only AFTER all forecasts are fixed.
        bank = predict_with_bank(prior, game)
        solo = _single_candidate(prior, game)
        null = research_null(actual.issue, game)
        tickets = {
            "ensemble": bank["prediction"],
            "single": solo,
            "research_null": null,
        }
        scores = {name: _score_pair(pick, actual)
                  for name, pick in tickets.items()}
        for name, fields in scores.items():
            for key, val in fields.items():
                totals[name][key] += val
        trials.append({
            "issue": actual.issue, "asof_issue": prior[-1].issue,
            "ensemble_commit_hash": bank["decision_sha256"],
            "choices": {name: {
                "front": pick["front"], "back": pick["back"],
                "d2_pair": pick["d2_pair"]
            } for name, pick in tickets.items()},
            "scores": scores,
        })
    return {
        "periods": len(trials),
        "first_evaluated_issue": trials[0]["issue"],
        "last_evaluated_issue": trials[-1]["issue"],
        "totals": totals,
        "theoretical_d2": (game.front_pick * (game.front_pick - 1)) /
                          (game.front_max * (game.front_max - 1)),
        "trials": trials,
        "interpretation": "EXPLORATORY_REPLAY_NOT_PROSPECTIVE",
    }


def run_committee(prefix: list[Draw], game: Game, *,
                  evaluation_window: int = 10) -> dict:
    """Convene the six role modules; return a reproducible meeting receipt.

    This function deliberately does not update any real-world model/ledger.
    An actual multi-model implementation can later bind role outputs to
    independently signed, separately executed model calls.
    """
    _check_history(prefix)
    asof = prefix[-1].issue
    target = asof + 1

    formula_list = catalog(prefix, game)
    ensemble = predict_with_bank(prefix, game)
    solo = _single_candidate(prefix, game)
    internal = audit_recent_past(prefix, game, evaluation_window)

    # The committee cannot certify an edge on the same historical data
    # repeatedly inspected during strategy and formula development.
    research_candidate = ensemble["prediction"]
    transcript = [
        {
            "role": "mathematician",
            "proposal": "Use six fixed algebraic reverse-formula families.",
            "evidence": {
                "families": list(METHODS),
                "training_identity": "anchor result is used to fit formula",
            },
            "objection": "post-hoc exact recovery is not a forecast",
        },
        {
            "role": "formula_discovery",
            "proposal": "Keep every prior identity; activate eligible formulas.",
            "evidence": {
                "active_candidates": len(formula_list),
                "eligible_anchor_latest": max(x["anchor_issue"]
                                              for x in formula_list),
            },
            "objection": "past wins may be selected from many attempts",
        },
        {
            "role": "ensemble_researcher",
            "proposal": "Use capped historical-score vote weighting.",
            "evidence": {
                "chosen_formula_ids": [
                    x["formula_id"] for x in ensemble["selected_formulas"]
                ],
                "choice": research_candidate,
                "alternative_single": {
                    "front": solo["front"],
                    "back": solo["back"],
                    "d2_pair": solo["d2_pair"],
                    "family": solo["family"],
                },
            },
            "objection": "weights are heuristics, not calibrated probabilities",
        },
        {
            "role": "statistician",
            "proposal": "Check paired historical results against fixed control.",
            "evidence": {
                "window": internal["periods"],
                "d2_by_method": {
                    k: v["d2"] for k, v in internal["totals"].items()
                },
                "theoretical_d2": internal["theoretical_d2"],
            },
            "objection": "multiple comparisons; exploratory sample only",
        },
        {
            "role": "skeptical_reviewer",
            "proposal": "Reject promotion until pre-registered future evidence.",
            "evidence": {
                "formal_edge_verified": False,
                "source_authentication_verified": False,
                "prospective_freeze_verified": False,
            },
            "objection": "historical model selection can overfit the replay",
        },
        {
            "role": "engineer",
            "proposal": "Output auditable research candidate without deployment.",
            "evidence": {
                "asof_issue": asof,
                "target_issue": target,
                "bank_decision_hash": ensemble["decision_sha256"],
                "official_v47_written": False,
            },
            "objection": "this hash is not a trusted pre-draw timestamp",
        },
    ]
    if tuple(x["role"] for x in transcript) != ROLE_NAMES:
        raise AssertionError("missing committee roles")
    if not set(research_candidate["d2_pair"]).issubset(
            set(research_candidate["front"])):
        raise AssertionError("invalid D2 selection")
    receipt = {
        "protocol": "SSQDLT_RESEARCH_COMMITTEE_V1",
        "implementation": "DETERMINISTIC_ROLE_SIMULATION_NOT_INDEPENDENT_LLM_AGENTS",
        "game": game.name,
        "asof_issue": asof,
        "target_issue": target,
        "history_count": len(prefix),
        "decision": {
            "proposal": research_candidate,
            "strategy": "fixed_formula_bank_ensemble",
            "research_only": True,
            "promote_to_formal_v47": False,
            "status": "NO_EDGE",
            "disagreement": "skeptic rejects forecasting advantage",
        },
        "transcript": transcript,
        "internal_replay": internal,
        "bank_decision_sha256": ensemble["decision_sha256"],
        "guards": {
            "future_outcome_available_to_committee": False,
            "future_result_used_for_ranking": False,
            "historical_replay_is_independent": False,
            "pre_draw_external_timestamp_created": False,
            "official_v47_modified": False,
            "fixed_random_null_modified": False,
        },
    }
    receipt["receipt_sha256"] = canonical_hash(receipt)
    return receipt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ssq", type=Path,
                    default=Path(__file__).with_name("ssq_2026.txt"))
    ap.add_argument("--dlt", type=Path,
                    default=Path(__file__).with_name("dlt_2026.txt"))
    ap.add_argument("--evaluation-window", type=int, default=10)
    ap.add_argument("--out", type=Path,
                    help="research receipt output; no writes to formal ledgers")
    args = ap.parse_args()
    documents = {}
    for name, path, game in (
        ("SSQ", args.ssq, SSQ), ("DLT", args.dlt, DLT)
    ):
        rows, data_sha = load_history(path, game)
        documents[name] = {
            "source_sha256": data_sha,
            "committee": run_committee(
                rows, game, evaluation_window=args.evaluation_window
            ),
        }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(documents, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps({
        game: {
            "asof_issue": doc["committee"]["asof_issue"],
            "target_issue": doc["committee"]["target_issue"],
            "roles": [x["role"] for x in doc["committee"]["transcript"]],
            "internal_d2": {
                name: score["d2"] for name, score in
                doc["committee"]["internal_replay"]["totals"].items()
            },
            "candidate": doc["committee"]["decision"]["proposal"],
            "receipt_sha256": doc["committee"]["receipt_sha256"],
            "status": doc["committee"]["decision"]["status"],
        } for game, doc in documents.items()
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
