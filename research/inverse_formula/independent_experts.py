"""Six independently callable, zero-network research experts with linked evidence.

This is a deterministic simulation, NOT six LLM calls, trusted timestamping,
a formal forecast, or evidence of an edge. Never writes V4.7 or fixed NULL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from research.inverse_formula.committee import audit_recent_past
from research.inverse_formula.formula_bank import catalog, predict_with_bank
from research.inverse_formula.probe import DLT, SSQ, Draw, Game, load_history

ROLES = (
    "mathematician", "formula_discovery", "ensemble_researcher",
    "statistician", "skeptical_reviewer", "engineer",
)
ZERO = "0" * 64
PROTOCOL = "SSQDLT_INDEPENDENT_RESEARCH_EXPERTS_V1"


def digest(value: object) -> str:
    """Content hash, NOT an authenticated signature or timestamp."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def guarded_prefix(history: list[Draw] | tuple[Draw, ...], game: Game,
                   *, cutoff_issue: int) -> tuple[Draw, ...]:
    """Reject a supplied future suffix, gaps, invalid tickets or wrong cutoff."""
    prefix = tuple(history)
    if len(prefix) < 31 or not isinstance(cutoff_issue, int):
        raise ValueError("at least 31 known past issues and an explicit cutoff required")
    if prefix[-1].issue != cutoff_issue:
        raise ValueError("future suffix or cutoff mismatch: fail closed")
    if any(row.issue != prefix[0].issue + i for i, row in enumerate(prefix)):
        raise ValueError("history must have consecutive unique issues")
    for row in prefix:
        for balls, maximum, count in (
            (row.front, game.front_max, game.front_pick),
            (row.back, game.back_max, game.back_pick),
        ):
            if (len(balls) != count or tuple(sorted(set(balls))) != balls
                    or any(not isinstance(n, int) or isinstance(n, bool)
                           or n < 1 or n > maximum for n in balls)):
                raise ValueError("invalid historical ticket")
    return prefix


def mathematician(prefix: tuple[Draw, ...], game: Game) -> dict:
    """Exact draw spaces and D2 chance under a uniform independent-draw null."""
    front_space = math.comb(game.front_max, game.front_pick)
    back_space = math.comb(game.back_max, game.back_pick)
    return {
        "game": game.name,
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "front_domain": [1, game.front_max, game.front_pick],
        "back_domain": [1, game.back_max, game.back_pick],
        "full_ticket_space": front_space * back_space,
        "full_ticket_probability": 1 / (front_space * back_space),
        "d2_probability": math.comb(game.front_pick, 2) /
                          math.comb(game.front_max, 2),
        "assumption": "uniform independent draw; theoretical null, not fitted model",
    }


def formula_discovery(prefix: tuple[Draw, ...], game: Game,
                      *, lookback: int = 24) -> dict:
    """Fixed-family and bounded-parameter search on only observed issues."""
    bank = catalog(list(prefix), game, lookback=lookback)
    rows = [{
        "formula_id": entry["formula_id"],
        "family": entry["family"],
        "anchor_issue": entry["anchor_issue"],
        "validation_first_issue": entry["validation_first_issue"],
        "validation_last_issue": entry["validation_last_issue"],
        "validated_issues": entry["validated_issues"],
        "vote_weight": entry["vote_weight"],
        "formula_parameters": asdict(entry["formula"]),
    } for entry in bank]
    return {
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "search_kind": "fixed_six_families_bounded_history_not_newly_discovered_law",
        "lookback": lookback,
        "candidate_count": len(rows),
        "family_counts": dict(sorted(Counter(x["family"] for x in rows).items())),
        "catalogue": rows,
        "catalogue_sha256": digest(rows),
        "warning": "anchor fitting is retrospective; scores are exploratory",
    }


def combination_research(prefix: tuple[Draw, ...], game: Game,
                         formula_report: dict) -> dict:
    """Legal full ticket, explicit D2 picks, and unselected research numbers."""
    if formula_report["asof_issue"] != prefix[-1].issue:
        raise ValueError("formula cutoff mismatch")
    bank = predict_with_bank(list(prefix), game,
                             lookback=formula_report["lookback"])
    if bank["candidate_count"] != formula_report["candidate_count"]:
        raise ValueError("formula catalogue changed between experts")
    if digest(formula_report["catalogue"]) != formula_report["catalogue_sha256"]:
        raise ValueError("formula catalogue hash mismatch")
    available = {r["formula_id"] for r in formula_report["catalogue"]}
    chosen = [r["formula_id"] for r in bank["selected_formulas"]]
    if not chosen or any(x not in available for x in chosen):
        raise ValueError("selected formula lacks traceable evidence")
    p = bank["prediction"]
    front, back, pair = tuple(p["front"]), tuple(p["back"]), tuple(p["d2_pair"])
    if (len(front) != game.front_pick or len(back) != game.back_pick
            or len(set(front)) != len(front) or len(set(back)) != len(back)
            or tuple(sorted(front)) != front or tuple(sorted(back)) != back
            or any(x < 1 or x > game.front_max for x in front)
            or any(x < 1 or x > game.back_max for x in back)
            or len(set(pair)) != 2 or not set(pair).issubset(front)):
        raise ValueError("illegal complete ticket or D2 pair")
    return {
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "full_ticket": {"front": front, "back": back},
        "d2_pair_research_only": pair,
        "unselected_front_not_verified_kills": [
            n for n in range(1, game.front_max + 1) if n not in front
        ],
        "unselected_back_not_verified_kills": [
            n for n in range(1, game.back_max + 1) if n not in back
        ],
        "chosen_formula_ids": chosen,
        "formula_catalogue_sha256": formula_report["catalogue_sha256"],
        "ensemble_decision_sha256": bank["decision_sha256"],
        "claimed_predictive_advantage": False,
    }


def wilson95(hits: int, trials: int) -> dict:
    """Descriptive 95% Wilson interval, not an independence or edge test."""
    if trials < 1 or not 0 <= hits <= trials:
        raise ValueError("invalid hit counts")
    z = 1.959963984540054
    p = hits / trials
    den = 1 + z * z / trials
    mid = (p + z * z / (2 * trials)) / den
    rad = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials**2)) / den
    return {"hits": hits, "trials": trials, "rate": p,
            "low": max(0.0, mid-rad), "high": min(1.0, mid+rad)}


def statistician(prefix: tuple[Draw, ...], game: Game,
                math_report: dict, *, window: int = 5) -> dict:
    """Past-only replay with theoretical and separately seeded research NULL."""
    if math_report["asof_issue"] != prefix[-1].issue or window < 1:
        raise ValueError("statistics cutoff/window invalid")
    prior = audit_recent_past(list(prefix), game, window=window)
    n = prior["periods"]
    totals = prior["totals"]
    trials = [{
        "target_issue": x["issue"],
        "asof_issue": x["asof_issue"],
        "choice_sha256": digest(x["choices"]),
        "scores": x["scores"],
    } for x in prior["trials"]]
    if any(x["asof_issue"] >= x["target_issue"] or
           x["target_issue"] > prefix[-1].issue for x in trials):
        raise ValueError("target outcome leaks into decision cutoff")
    return {
        "asof_issue": prefix[-1].issue,
        "latest_scored_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "window": n,
        "research_ensemble_d2": wilson95(totals["ensemble"]["d2"], n),
        "research_null_d2": wilson95(totals["research_null"]["d2"], n),
        "research_ensemble_exact": totals["ensemble"]["exact"],
        "research_null_exact": totals["research_null"]["exact"],
        "theoretical_d2": math_report["d2_probability"],
        "trials": trials,
        "interpretation": "exploratory past-only replay; no significant edge claim",
        "prospective_trials": 0,
        "fixed_v47_random_null_used": False,
    }


def skeptical_reviewer(math_report: dict, formula_report: dict,
                       combo_report: dict, stats_report: dict) -> dict:
    """Independent structural cross-check and binding veto on promotion."""
    target = math_report["target_issue"]
    asof = math_report["asof_issue"]
    for report in (formula_report, combo_report, stats_report):
        if report["target_issue"] != target or report["asof_issue"] != asof:
            raise ValueError("cross-expert target/cutoff disagreement")
    if combo_report["formula_catalogue_sha256"] != formula_report["catalogue_sha256"]:
        raise ValueError("ensemble used a different candidate library")
    violations = []
    if any(r["anchor_issue"] > asof or r["validation_last_issue"] > asof
           or r["validation_first_issue"] <= r["anchor_issue"]
           for r in formula_report["catalogue"]):
        violations.append("FORMULA_FUTURE_LEAKAGE")
    if any(r["asof_issue"] >= r["target_issue"]
           or r["target_issue"] > asof for r in stats_report["trials"]):
        violations.append("BACKTEST_FUTURE_LEAKAGE")
    if stats_report["prospective_trials"] != 0:
        violations.append("UNSUPPORTED_PROSPECTIVE_CLAIM")
    return {
        "asof_issue": asof,
        "target_issue": target,
        "cross_review": {
            "formula_anchors_past_only": "FORMULA_FUTURE_LEAKAGE" not in violations,
            "replay_cutoffs_past_only": "BACKTEST_FUTURE_LEAKAGE" not in violations,
            "candidate_ids_from_catalogue": True,
        },
        "violations": violations,
        "veto": True,
        "veto_reasons": violations + [
            "NOT_INDEPENDENTLY_AUTHENTICATED_HISTORY",
            "NO_INDEPENDENT_PROSPECTIVE_PRE_DRAW_TRIAL",
            "EXPLORATORY_MULTIPLE_TESTING_OVERFIT_RISK",
            "NO_VALIDATED_EDGE",
        ],
        "promotion_allowed": False,
        "research_status": "NO_EDGE",
    }


def engineer(prefix: tuple[Draw, ...], game: Game, combo_report: dict,
             reviewer_report: dict) -> dict:
    """Content seal and idempotency key only; NO scheduler, network or ledger IO."""
    if (not reviewer_report["veto"] or reviewer_report["promotion_allowed"]
            or reviewer_report["target_issue"] != prefix[-1].issue + 1):
        raise ValueError("review veto absent or target mismatch")
    candidate = {
        "game": game.name, "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "full_ticket": combo_report["full_ticket"],
        "d2_pair_research_only": combo_report["d2_pair_research_only"],
        "formula_decision_sha256": combo_report["ensemble_decision_sha256"],
        "research_only": True, "formal_v47_compatible_for_promotion": False,
    }
    return {
        "asof_issue": prefix[-1].issue,
        "target_issue": prefix[-1].issue + 1,
        "candidate_sha256": digest(candidate),
        "idempotency_key": digest([PROTOCOL, game.name, prefix[-1].issue,
                                   digest(candidate)]),
        "deployment": "BLOCKED_BY_REVIEW_VETO",
        "local_content_seal_only": True,
        "externally_timestamped_prediction": False,
        "automated_schedule_trigger_verified": False,
        "draw_result_synced": False,
        "actual_draw_scored": False,
        "durable_restart_recovery_verified": False,
        "paid_model_calls": 0,
        "official_v47_written": False,
        "fixed_random_null_written": False,
        "research_status": "NO_EDGE",
    }


def _record(role: str, payload: dict, prefix_sha256: str,
            previous_sha256: str, seq: int) -> dict:
    body = {
        "sequence": seq, "role": role,
        "asof_issue": payload["asof_issue"],
        "target_issue": payload["target_issue"],
        "history_sha256": prefix_sha256,
        "previous_record_sha256": previous_sha256,
        "payload_sha256": digest(payload),
        "payload": payload,
    }
    return {**body, "record_sha256": digest(body)}


def verify_evidence(records: list[dict]) -> bool:
    """Recompute chain and payload hashes; integrity, not identity/authenticity."""
    if len(records) != len(ROLES):
        raise ValueError("six independent expert records required")
    previous = ZERO
    first = records[0]
    for idx, (role, rec) in enumerate(zip(ROLES, records), 1):
        if (rec["role"] != role or rec["sequence"] != idx
                or rec["previous_record_sha256"] != previous
                or rec["history_sha256"] != first["history_sha256"]
                or rec["asof_issue"] != first["asof_issue"]
                or rec["target_issue"] != first["target_issue"]
                or rec["payload"]["asof_issue"] != rec["asof_issue"]
                or rec["payload"]["target_issue"] != rec["target_issue"]):
            raise ValueError("expert evidence linkage mismatch")
        if digest(rec["payload"]) != rec["payload_sha256"]:
            raise ValueError("expert payload hash mismatch")
        body = {k: v for k, v in rec.items() if k != "record_sha256"}
        if digest(body) != rec["record_sha256"]:
            raise ValueError("expert record hash mismatch")
        previous = rec["record_sha256"]
    return True


def simulate_experts(history: list[Draw] | tuple[Draw, ...], game: Game,
                     *, cutoff_issue: int, replay_window: int = 5) -> dict:
    """Offline six-stage deterministic simulation with explicit past-only gate."""
    prefix = guarded_prefix(history, game, cutoff_issue=cutoff_issue)
    p_hash = digest([asdict(x) for x in prefix])
    mathematical = mathematician(prefix, game)
    discovered = formula_discovery(prefix, game)
    combined = combination_research(prefix, game, discovered)
    statistics = statistician(prefix, game, mathematical, window=replay_window)
    review = skeptical_reviewer(mathematical, discovered, combined, statistics)
    engineering = engineer(prefix, game, combined, review)
    payloads = (mathematical, discovered, combined, statistics, review, engineering)
    records = []
    for i, (role, payload) in enumerate(zip(ROLES, payloads), 1):
        records.append(_record(role, payload, p_hash,
                               records[-1]["record_sha256"] if records else ZERO,
                               i))
    verify_evidence(records)
    return {
        "protocol": PROTOCOL,
        "implementation": "SIX_PURE_FUNCTIONS_ZERO_API_CALLS_NOT_SIX_LLMS",
        "game": game.name,
        "asof_issue": cutoff_issue,
        "target_issue": cutoff_issue + 1,
        "history_count": len(prefix),
        "history_sha256": p_hash,
        "records": records,
        "receipt_sha256": digest(records),
        "research_status": "NO_EDGE",
        "formal_promotion_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=34,
                        help="historical prefix only; deliberately not latest/live")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.limit < 31:
        parser.error("limit must be at least 31")
    documents = {}
    for game, name in ((SSQ, "ssq"), (DLT, "dlt")):
        draws, source_sha = load_history(
            Path(__file__).with_name(name + "_2026.txt"), game)
        if args.limit > len(draws):
            parser.error("limit exceeds historical fixture length")
        prefix = draws[:args.limit]
        documents[game.name] = {
            "source_file_sha256": source_sha,
            "simulation": simulate_experts(
                prefix, game, cutoff_issue=prefix[-1].issue),
        }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(documents, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
    print(json.dumps({name: {
        "experts": [r["role"] for r in doc["simulation"]["records"]],
        "receipt_sha256": doc["simulation"]["receipt_sha256"],
        "status": doc["simulation"]["research_status"],
        "paid_model_calls": doc["simulation"]["records"][-1]["payload"]["paid_model_calls"],
    } for name, doc in documents.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
