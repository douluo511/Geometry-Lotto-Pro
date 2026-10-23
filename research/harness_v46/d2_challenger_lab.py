"""V4.7 isolated D2 challenger laboratory. RETROSPECTIVE / SHADOW ONLY.

This does not alter any registered 6-model forecast, original 8 formal slots,
negative-control seed, frozen prediction, or official D2 protocol. A candidate
picked from known history has *no established* ability to beat fair draws.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from itertools import combinations
from pathlib import Path

from . import core
from .statistics import clopper_pearson, exact_binomial_upper_tail

CHALLENGER_ID = "RECENCY_PAIR_H45_120_V1"
WINDOW = 120
HALF_LIFE = 45

def challenger_contract_sha256() -> str:
    """Fixed identity, including implementation bytes; not a preregistration."""
    return core.digest({
        "schema": "V47-EXPERIMENTAL-D2-CONTRACT-1",
        "id": CHALLENGER_ID,
        "window": WINDOW,
        "half_life_draws": HALF_LIFE,
        "rank": "descending_exponentially_weighted_pair_occurrences_then_lex",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixed_null_seed_id": core.NULL_SEED,
    })


def pick_recency_pair(history: list[dict], game: str) -> list[int]:
    """One fixed research pair, chosen solely from the preceding 120 draws.

    Weights 2**(-age_in_draws/45). It is a hypothesis rather than a
    calibrated posterior probability or an established predictive edge.
    """
    if game not in core.RULES:
        raise core.GateError("D2_CHALLENGER_UNKNOWN_LOTTERY")
    if not isinstance(history, list) or len(history) < WINDOW:
        raise core.GateError("D2_CHALLENGER_WARMUP_120_REQUIRED")
    pool = core.RULES[game]["pool"]
    size = core.RULES[game]["front"]
    weighted = Counter()
    for age, draw in enumerate(reversed(history[-WINDOW:])):
        if not isinstance(draw, dict):
            raise core.GateError("D2_CHALLENGER_INVALID_TRAINING_DRAW")
        core._balls(draw.get("front"), pool, size)
        weight = 2.0 ** (-age / HALF_LIFE)
        for pair in combinations(draw["front"], 2):
            weighted[pair] += weight
    best = min(combinations(range(1, pool + 1), 2),
               key=lambda pair: (-weighted[pair], pair))
    return list(best)


def _exact_statistics(rows: list[dict], game: str) -> dict:
    subset = [r for r in rows if r["lottery"] == game]
    n = len(subset)
    c = sum(r["d2_hits"]["challenger"] for r in subset)
    p = sum(r["d2_hits"]["pairwise_d2"] for r in subset)
    null = sum(r["d2_hits"]["random_null"] for r in subset)
    wins = sum(r["d2_hits"]["challenger"] == 1
               and r["d2_hits"]["random_null"] == 0 for r in subset)
    losses = sum(r["d2_hits"]["challenger"] == 0
                 and r["d2_hits"]["random_null"] == 1 for r in subset)
    fair = core.RULES[game]["d2"]
    return {
        "n": n, "challenger_hits": c, "challenger_rate": c / n,
        "pairwise_d2_hits": p, "random_null_hits": null,
        "random_null_rate": null / n, "fair_d2": fair,
        "challenger_minus_null_rate": (c - null) / n,
        "paired_wins": wins, "paired_losses": losses,
        "paired_p_unadjusted": exact_binomial_upper_tail(
            wins, wins + losses, 0.5) if wins + losses else 1.0,
        "fair_p_unadjusted": exact_binomial_upper_tail(c, n, fair),
        "challenger_ci95": list(clopper_pearson(c, n)),
        "registration": "NOT_PREREGISTERED",
        "hypothesis_test": "EXPLORATORY_UNADJUSTED_NOT_FOR_PROMOTION",
    }


def audit_walk_forward(bundle: dict) -> dict:
    """Expanding-origin contiguous retrospective audit; target labels never train themselves.

    For historical draw i, model uses only draw indices < i, and all prior
    publication timestamps MUST precede draw i's actual draw time.
    Does not certify that historical inputs or published timestamps are true.
    """
    if not isinstance(bundle, dict) or set(bundle) != set(core.RULES):
        raise core.GateError("EXACT_TWO_GAMES_REQUIRED")
    rows = []
    for game in ("SSQ", "DLT"):
        snapshot = bundle[game]
        if not isinstance(snapshot, dict) or snapshot.get("lottery") != game:
            raise core.GateError("D2_CHALLENGER_SNAPSHOT_GAME_MISMATCH")
        core.validate_study_snapshot(snapshot)
        history = snapshot["draws"]
        if len(history) <= WINDOW:
            raise core.GateError("D2_CHALLENGER_NO_HELDOUT_HISTORY")
        for i in range(WINDOW, len(history)):
            target = history[i]
            training = history[:i]
            drawn_at = core.dt(target["drawn_at"])
            if max(core.dt(d["published_at"]) for d in training) >= drawn_at:
                raise core.GateError("TRAINING_NOT_PUBLISHED_BEFORE_TEST_DRAW")
            pred = {
                "lottery": game, "draws": training, "target_issue": target["issue"],
            }
            pairs = {
                "challenger": pick_recency_pair(training, game),
                "pairwise_d2": core._model_ranking(pred, "pairwise_d2")[:2],
                "random_null": core._model_ranking(pred, "random_null")[:2],
            }
            actual = set(target["front"])
            rows.append({
                "lottery": game,
                "issue": str(target["issue"]),
                "draw_index": i,
                "max_training_published_at": max(d["published_at"] for d in training),
                "target_drawn_at": target["drawn_at"],
                "pairs": pairs,
                "d2_hits": {k: int(set(v).issubset(actual))
                            for k, v in pairs.items()},
            })
    return {
        "schema": "V47-D2-EXPLORATORY-WALKFORWARD-1",
        "model": CHALLENGER_ID,
        "challenger_contract_sha256": challenger_contract_sha256(),
        "fixed_null_seed_id": core.NULL_SEED,
        "input_bundle_sha256": core.digest(bundle),
        "evaluation_rows_sha256": core.digest(rows),
        "draws_by_game": {g: sum(r["lottery"] == g for r in rows)
                          for g in ("SSQ", "DLT")},
        "rows": rows,
        "exploratory_statistics": {
            g: _exact_statistics(rows, g) for g in ("SSQ", "DLT")
        },
        "data_provenance": "CALLER_SUPPLIED_UNVERIFIED_HISTORY",
        "evidence_class": "RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE",
        "qualified_prospective": False,
        "selection_and_multiple_testing": "NOT_PREREGISTERED_NO_PROMOTION",
        "historical_69_2880_negative_control": "UNRESOLVED_NOT_EXCLUDED",
        "formal_A": 0,
        "decision": "NO_EDGE",
        "limitations": [
            "Existing historical target labels were already exposed before the study; this is not future evidence.",
            "The candidate, pairwise, and NULL paths share unverified caller inputs.",
            "Official schedule completeness, publication truth, TSA, and independent result custody are not verified.",
            "No post-hoc window selection or retroactive replacement of the registered model is allowed.",
        ],
    }
