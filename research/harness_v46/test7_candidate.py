"""test7 proposed residual-only cross-window challenger.

EXPLORATORY_UNREGISTERED. This module does not change core.forecast,
the canonical six-arm registry, any V4.5 slot, or a frozen prediction.
Only test1's future preregistration can authorize prospective use.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from itertools import combinations

from research.harness_v46 import core

CANDIDATE_ID = "test7_cw_residual_minimax_v1"
STATUS = "EXPLORATORY_UNREGISTERED"
BASE_CORE_COMMIT = "f12e47106f1d0c325573a48e39a6e2efd5d459ff"
WINDOWS = (30, 60, 120)
TAU = 200

def parameter_contract():
    """Full proposed identity; not an authorized/registered V4.7 core parameter."""
    return {
        "model_id": CANDIDATE_ID,
        "status": STATUS,
        "base_core_commit": BASE_CORE_COMMIT,
        "core_version": core.VERSION,
        "windows": list(WINDOWS),
        "minimum_history": 120,
        "tau": TAU,
        "expectation": "c_i*c_j*(k-1)/(w*k)",
        "window_residual": "(cooccurrence-expectation)/(w+tau)",
        "window_aggregation": "minimum",
        "pair_selection": "max_score_then_pair_numeric_ascending",
        "remaining_candidates": "last120_frequency_desc_then_numeric_ascending",
        "numerics": "fractions.Fraction_exact",
        "ticket_front": "top_k_candidates_numeric_ascending",
        "ticket_back": {
            "engine": core.TICKET_BACK_ENGINE,
            "seed": core.NULL_SEED,
            "identity_parts": "seed|lottery|target_issue|challenger|back",
        },
        "lottery_rules_sha256": core.digest(core.RULES),
        "parent_core_source_sha256": core.model_source_sha256(),
    }

def pair_scores(draws, lottery, window):
    """Exact arithmetic: joint association conditioned on observed marginal counts.

    This is a heuristic expectation, not a claim of a calibrated null distribution.
    """
    if lottery not in core.RULES or window not in WINDOWS or len(draws) < window:
        raise core.GateError("invalid lottery/window or insufficient history")
    rules = core.RULES[lottery]
    k, pool = rules["front"], rules["pool"]
    tail = draws[-window:]
    counts = Counter(ball for draw in tail for ball in draw["front"])
    joint = Counter(pair for draw in tail for pair in combinations(draw["front"], 2))
    return {
        (a, b): Fraction(
            joint[(a, b)] * window * k - counts[a] * counts[b] * (k - 1),
            window * k * (window + TAU),
        )
        for a, b in combinations(range(1, pool + 1), 2)
    }

def select_proposal(snapshot):
    """Research proposal only: no admission to official forecast or formal A.

    The canonical core must check the whole as-of snapshot before any selection.
    """
    snapshot_sha = core.validate_study_snapshot(snapshot)
    lottery, draws = snapshot["lottery"], snapshot["draws"]
    rules = core.RULES[lottery]
    window_scores = [pair_scores(draws, lottery, w) for w in WINDOWS]
    best_pair = min(
        window_scores[0],
        key=lambda pair: (-min(scores[pair] for scores in window_scores), pair),
    )
    counts = Counter(ball for draw in draws[-120:] for ball in draw["front"])
    rest = sorted(
        (i for i in range(1, rules["pool"] + 1) if i not in best_pair),
        key=lambda i: (-counts[i], i),
    )
    ranking = list(best_pair) + rest
    back_order = core._stable_permutation(
        list(range(1, rules["back_pool"] + 1)),
        core.NULL_SEED, lottery, snapshot["target_issue"], "challenger", "back",
    )
    return {
        "model_id": CANDIDATE_ID,
        "registration_status": STATUS,
        "formal_a_eligible": False,
        "snapshot_sha256": snapshot_sha,
        "parameter_sha256": core.digest(parameter_contract()),
        "candidates_1_to_5": ranking[:5],
        "primary_d2": ranking[:2],
        "ticket": {
            "front": sorted(ranking[:rules["front"]]),
            "back": sorted(back_order[:rules["back"]]),
        },
    }
