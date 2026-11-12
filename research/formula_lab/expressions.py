"""Pure computation port of PR #479 (3d6516d); no file or network I/O.

Automatic bounded mathematical-expression discovery for SSQ/DLT (research only).

A grammar enumerates new candidate formula trees and rolling calibration windows.
At every historical target, candidates are evaluated only against earlier draws.
This deliberately does NOT issue or promote formal forecasts. A fair random
lottery cannot be made predictable by searching more formulas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import random

from research.supercompute.engine import SPECS, derive_seed

SCHEMA = "SSQDLT_AUTOMATIC_FORMULA_DISCOVERY_V1"
ATOMS = ("LAG1", "LAG2", "LAG3", "ISSUE")
OPERATIONS = ("ATOM", "DOUBLE", "ADD", "SUB", "MUL")
WINDOWS = (8, 16)
VALIDATION = 10
MAX_EXPERTS = 8
MAX_PER_FAMILY = 2


def digest(obj):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def grammar():
    """Generate candidate expression trees algorithmically, not from fitted outcomes."""
    expressions = []
    for op in ("ATOM", "DOUBLE"):
        expressions.extend((op, atom, None) for atom in ATOMS)
    for op in ("ADD", "SUB", "MUL"):
        for i, left in enumerate(ATOMS):
            for j, right in enumerate(ATOMS):
                if op in ("ADD", "MUL") and j < i:
                    continue
                if (op == "SUB" or op == "ADD") and i == j:
                    continue  # x+x is already DOUBLE(x); x-x is constant
                expressions.append((op, left, right))
    result = []
    for op, left, right in expressions:
        for window in WINDOWS:
            result.append({
                "id": f"{op}:{left}:{right or 'NONE'}:W{window}",
                "family": op,
                "op": op, "left": left, "right": right, "window": window,
            })
    if len({x["id"] for x in result}) != len(result):
        raise AssertionError("duplicate formula grammar")
    return tuple(result)


GRAMMAR = grammar()


def atom_value(atom, history, index, area, pos):
    if atom == "ISSUE":
        return int(history[index - 1]["issue"]) + 1
    lag = {"LAG1": 1, "LAG2": 2, "LAG3": 3}[atom]
    return history[index - lag][area][pos] - 1


def evaluate_expr(expr, history, index, area, pos, modulus):
    if index < 3 or index > len(history):
        raise ValueError("formula requires three strictly previous draws")
    a = atom_value(expr["left"], history, index, area, pos)
    op = expr["op"]
    if op == "ATOM":
        value = a
    elif op == "DOUBLE":
        value = 2 * a
    else:
        b = atom_value(expr["right"], history, index, area, pos)
        value = {"ADD": lambda: a + b, "SUB": lambda: a - b,
                 "MUL": lambda: a * b}[op]()
    return value % modulus


def learn_offset(expr, history, index, area, pos, modulus):
    """Fit modular residual from the last W known target observations only."""
    start = max(3, index - expr["window"])
    residuals = Counter(
        (history[j][area][pos] - 1 -
         evaluate_expr(expr, history, j, area, pos, modulus)) % modulus
        for j in range(start, index)
    )
    if not residuals:
        raise ValueError("empty causal training interval")
    return min(residuals, key=lambda r: (-residuals[r], r))


def complete_balls(raw, maximum, count, *, game, asof, formula_id, area):
    """Remove duplicates and fill missing positions by deterministic SHA rank."""
    if not raw or not all(1 <= x <= maximum for x in raw):
        raise ValueError("invalid candidate balls")
    ordered = list(dict.fromkeys(raw))
    if len(ordered) < count:
        remaining = [v for v in range(1, maximum + 1) if v not in ordered]
        remaining.sort(key=lambda n: derive_seed(
            "AUTO_FORMULA_DEDUP_V1", game, asof, formula_id, area, n))
        ordered += remaining[:count - len(ordered)]
    return ordered[:count]


def candidate(history, game, expr):
    if game not in SPECS or len(history) < 40:
        raise ValueError("invalid game or insufficient historical prefix")
    fm, fp, bm, bp = SPECS[game]
    index = len(history)
    asof = str(history[-1]["issue"])
    raw = {}
    for area, maximum, count in (("front", fm, fp), ("back", bm, bp)):
        raw[area] = [
            1 + (evaluate_expr(expr, history, index, area, pos, maximum)
                 + learn_offset(expr, history, index, area, pos, maximum)) % maximum
            for pos in range(count)
        ]
    front = complete_balls(raw["front"], fm, fp, game=game, asof=asof,
                           formula_id=expr["id"], area="front")
    back = complete_balls(raw["back"], bm, bp, game=game, asof=asof,
                          formula_id=expr["id"], area="back")
    return {"front": sorted(front), "back": sorted(back),
            "d2_pair": sorted(front[:2])}


def hit_counts(pred, actual):
    return {
        "d2": int(set(pred["d2_pair"]).issubset(actual["front"])),
        "front_hits": len(set(pred["front"]).intersection(actual["front"])),
        "back_hits": len(set(pred["back"]).intersection(actual["back"])),
        "exact": int(pred["front"] == actual["front"] and
                     pred["back"] == actual["back"]),
    }


def research_null(game, target_issue):
    """Unchanging same-issue random control; separate from official V4.7 NULL."""
    fm, fp, bm, bp = SPECS[game]
    rng = random.Random(derive_seed("AUTO_DISCOVERY_RESEARCH_NULL_V1",
                                    game, str(target_issue)))
    d2 = rng.sample(range(1, fm + 1), 2)
    remaining = [x for x in range(1, fm + 1) if x not in d2]
    front = sorted(d2 + rng.sample(remaining, fp - 2))
    back = sorted(rng.sample(range(1, bm + 1), bp))
    return {"front": front, "back": back, "d2_pair": sorted(d2)}


def vote(history, game, chosen):
    fm, fp, bm, bp = SPECS[game]
    votes = {"front": defaultdict(float), "back": defaultdict(float)}
    predictions = []
    for item in chosen:
        pick = candidate(history, game, item["expr"])
        predictions.append({"formula_id": item["expr"]["id"], "ticket": pick})
        for area in ("front", "back"):
            for ball in pick[area]:
                votes[area][ball] += item["weight"]
    asof = str(history[-1]["issue"])
    ranks = {}
    for area, maximum in (("front", fm), ("back", bm)):
        ranks[area] = sorted(
            range(1, maximum + 1),
            key=lambda n: (-votes[area][n],
                           derive_seed("AUTO_VOTE_TIE_V1", game, asof, area, n)),
        )
    front = sorted(ranks["front"][:fp])
    back = sorted(ranks["back"][:bp])
    d2 = sorted(ranks["front"][:2])
    if not set(d2).issubset(front):
        raise AssertionError("D2 not subset of front")
    return {"front": front, "back": back, "d2_pair": d2}, predictions
