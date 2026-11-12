"""CPU-optimized, privacy-preserving formula search (research-only).

Pure in-memory algorithm: NO official fetch, storage, tickets or draw-data logging.
The V1 72 expressions are a strict subset of this 312-expression grammar.
Vectorized and optional Numba implementations reproduce V1's modular mode.
Nothing here is a real or authorized lottery forecast.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import multiprocessing
import os
import random
import time

import numpy as np

from research.supercompute import auto_discovery as v1
from research.supercompute.engine import SPECS, chance, derive_seed

try:
    from numba import njit
except ImportError:  # numpy-only fallback remains fully functional
    njit = None

SCHEMA = "SSQDLT_FORMULA_COMPUTE_ACCEL_RESEARCH_V1"
ATOMS = ("LAG1", "LAG2", "LAG3", "LAG4", "LAG5", "ISSUE")
WINDOWS = (8, 16, 32, 64)
MIN_LAG = 5
MAX_FORMULAS = 312
MAX_WORKERS = 8
MAX_EXPERTS = 8
MAX_PER_FAMILY = 2


def expanded_grammar():
    expressions = []
    for op in ("ATOM", "DOUBLE"):
        expressions += [(op, atom, None) for atom in ATOMS]
    for op in ("ADD", "SUB", "MUL"):
        for i, left in enumerate(ATOMS):
            for j, right in enumerate(ATOMS):
                if op in ("ADD", "MUL") and j < i:
                    continue
                if op in ("ADD", "SUB") and i == j:
                    continue
                expressions.append((op, left, right))
    result = tuple({
        "id": f"{op}:{left}:{right or 'NONE'}:W{window}",
        "family": op, "op": op, "left": left,
        "right": right, "window": window,
    } for op, left, right in expressions for window in WINDOWS)
    if len(result) != MAX_FORMULAS or len({x["id"] for x in result}) != MAX_FORMULAS:
        raise AssertionError("extended bounded grammar count or uniqueness failed")
    if not {x["id"] for x in v1.GRAMMAR}.issubset({x["id"] for x in result}):
        raise AssertionError("legacy grammar coverage lost")
    return result


GRAMMAR = expanded_grammar()
FORMULA_BY_ID = {x["id"]: x for x in GRAMMAR}


def synthetic_rows(game, n=260, seed=20261112):
    """Deterministic synthetic-only fixtures, never real lottery history."""
    if game not in SPECS or n < 130:
        raise ValueError("invalid synthetic experiment")
    fm, fp, bm, bp = SPECS[game]
    rows = []
    for t in range(n):
        rng = random.Random(derive_seed("SYNTHETIC_CPU_WORKLOAD_V1", game, seed, t))
        rows.append({
            "issue": str((2026000 if game == "ssq" else 26000) + t + 1),
            "front": sorted(rng.sample(range(1, fm + 1), fp)),
            "back": sorted(rng.sample(range(1, bm + 1), bp)),
        })
    return rows


def _validate_rows(rows, game):
    if game not in SPECS or not 120 <= len(rows) <= 20000:
        raise ValueError("unsupported game or unsafe history size")
    fm, fp, bm, bp = SPECS[game]
    prev = None
    for r in rows:
        if type(r) is not dict:
            raise ValueError("invalid draw record")
        issue = str(r.get("issue", ""))
        if not issue.isascii() or not issue.isdigit() or len(issue) != (
                7 if game == "ssq" else 5):
            raise ValueError("ambiguous issue identity")
        if prev is not None and int(issue) <= prev:
            raise ValueError("duplicate or out-of-order issue")
        prev = int(issue)
        for area, maximum, count in (("front", fm, fp), ("back", bm, bp)):
            balls = r.get(area)
            if (type(balls) is not list or len(balls) != count
                    or any(type(b) is not int or not 1 <= b <= maximum
                           for b in balls)
                    or sorted(set(balls)) != balls):
                raise ValueError("invalid " + area)


if njit is not None:
    @njit(cache=True)
    def _mode_numba(residual, targets, window, modulus, first_valid):
        result = np.empty((len(targets), residual.shape[1]), dtype=np.int64)
        for k in range(len(targets)):
            target = targets[k]
            begin = max(first_valid, target - window)
            for position in range(residual.shape[1]):
                counts = np.zeros(modulus, dtype=np.int64)
                for j in range(begin, target):
                    counts[residual[j, position]] += 1
                winning = 0
                for number in range(1, modulus):
                    if counts[number] > counts[winning]:
                        winning = number
                result[k, position] = winning
        return result
else:
    _mode_numba = None


def _numpy_mode(residual, targets, window, modulus):
    """Cumulative one-hot counts: each target sees j < target only."""
    one_hot = residual[:, :, None] == np.arange(modulus, dtype=np.int64)
    counts = np.concatenate((
        np.zeros((1, residual.shape[1], modulus), dtype=np.int32),
        np.cumsum(one_hot, axis=0, dtype=np.int32),
    ), axis=0)
    starts = np.maximum(MIN_LAG, targets - window)
    # argmax yields lexicographically first modular residual on equal counts.
    return np.argmax(counts[targets] - counts[starts], axis=2)


class PrefixMatrix:
    """Immutable snapshot-scoped, bounded in-memory cache; no cross-run cache."""

    def __init__(self, rows, game, *, cache_entries=64, max_temp_mib=64):
        _validate_rows(rows, game)
        if type(cache_entries) is not int or not 0 <= cache_entries <= 256:
            raise ValueError("cache entries must be bounded")
        if not 1 <= max_temp_mib <= 2048:
            raise ValueError("memory budget outside admitted bounds")
        self.game = game
        self.rows = tuple({
            "issue": str(x["issue"]),
            "front": tuple(x["front"]),
            "back": tuple(x["back"]),
        } for x in rows)
        self.issue = np.array([int(x["issue"]) for x in self.rows], dtype=np.int64)
        self.areas = {
            "front": np.array([x["front"] for x in self.rows], dtype=np.int64),
            "back": np.array([x["back"] for x in self.rows], dtype=np.int64),
        }
        for array in (self.issue, *self.areas.values()):
            array.setflags(write=False)
        self.cache = OrderedDict()
        self.cache_entries = cache_entries
        self.max_temp_bytes = int(max_temp_mib * 1024 * 1024)
        self.cache_hits = 0
        self.cache_misses = 0
        self.source_sha256 = hashlib.sha256(
            json.dumps(self.rows, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    def _atom(self, area, name):
        data = self.areas[area]
        t = len(self.rows)
        width = data.shape[1]
        if name == "ISSUE":
            return np.broadcast_to(
                np.concatenate((np.zeros(1, dtype=np.int64), self.issue + 1))[:, None],
                (t + 1, width),
            )
        lag = int(name.removeprefix("LAG"))
        if name not in ATOMS or not 1 <= lag <= MIN_LAG:
            raise ValueError("unknown atom")
        out = np.zeros((t + 1, width), dtype=np.int64)
        out[lag:] = data[:t + 1 - lag] - 1
        return out

    def evaluate(self, expression, area):
        if area not in self.areas:
            raise ValueError("unsupported ball area")
        if expression["id"] not in FORMULA_BY_ID or (
                expression != FORMULA_BY_ID[expression["id"]]):
            raise ValueError("only fixed registered expression grammar is allowed")
        key = (area, expression["op"], expression["left"], expression["right"])
        if key in self.cache:
            self.cache.move_to_end(key)
            self.cache_hits += 1
            return self.cache[key]
        self.cache_misses += 1
        a = self._atom(area, expression["left"])
        op = expression["op"]
        if op == "ATOM":
            val = a
        elif op == "DOUBLE":
            val = a * 2
        else:
            b = self._atom(area, expression["right"])
            if op == "ADD":
                val = a + b
            elif op == "SUB":
                val = a - b
            elif op == "MUL":
                val = a * b
            else:
                raise ValueError("unsupported operator")
        modulus = SPECS[self.game][0 if area == "front" else 2]
        result = np.asarray(val % modulus, dtype=np.int64)
        result.setflags(write=False)
        if self.cache_entries:
            self.cache[key] = result
            while len(self.cache) > self.cache_entries:
                self.cache.popitem(last=False)
        return result

    def predict(self, expression, targets, *, backend="numpy"):
        """Target t learns residuals only from [max(5,t-W),t); never draws[t]."""
        indices = np.array(list(targets), dtype=np.int64)
        if not len(indices) or len(set(indices.tolist())) != len(indices):
            raise ValueError("nonempty unique target set required")
        if np.any(indices < 70) or np.any(indices > len(self.rows)):
            raise ValueError("target needs warmup and cannot exceed history")
        if backend not in ("numpy", "numba"):
            raise ValueError("backend unavailable")
        if backend == "numba" and _mode_numba is None:
            raise RuntimeError("Numba unavailable, use numpy fallback")
        result_arrays = {}
        for area in ("front", "back"):
            modulus = SPECS[self.game][0 if area == "front" else 2]
            evals = self.evaluate(expression, area)
            draws = self.areas[area]
            residual = np.zeros_like(evals)
            residual[:len(self.rows)] = (
                (draws - 1 - evals[:len(self.rows)]) % modulus)
            mem_est = (
                (len(self.rows) + 2) * draws.shape[1] * modulus * 5
            )  # bool one-hot + int32 cumulative
            if backend == "numpy" and mem_est > self.max_temp_bytes:
                raise MemoryError("estimated mode histogram buffer exceeds budget")
            if backend == "numpy":
                offset = _numpy_mode(
                    residual, indices, expression["window"], modulus)
            else:
                offset = _mode_numba(
                    residual, indices, expression["window"],
                    modulus, MIN_LAG)
            result_arrays[area] = 1 + (
                evals[indices] + offset) % modulus
        predictions = []
        for k, index in enumerate(indices.tolist()):
            asof = self.rows[index - 1]["issue"]
            pred = {}
            for area, maximum, picks in (
                    ("front", SPECS[self.game][0], SPECS[self.game][1]),
                    ("back", SPECS[self.game][2], SPECS[self.game][3])):
                raw = [int(x) for x in result_arrays[area][k]]
                pred[area] = v1.complete_balls(
                    raw, maximum, picks, game=self.game,
                    asof=asof, formula_id=expression["id"], area=area)
            pred["d2_pair"] = sorted(pred["front"][:2])
            pred["front"] = sorted(pred["front"])
            pred["back"] = sorted(pred["back"])
            predictions.append(pred)
        return predictions


def _chunk_worker(args):
    rows, game, targets, group, backend, cache_entries, memory = args
    engine = PrefixMatrix(
        rows, game, cache_entries=cache_entries, max_temp_mib=memory)
    return [(expr["id"], engine.predict(
        expr, targets, backend=backend)) for expr in group]


def evaluate_grid(rows, game, targets, expressions=GRAMMAR, *,
                  backend="numpy", workers=1, cache_entries=64,
                  max_temp_mib=64):
    """Deterministic order, spawn-safe parallel chunks; no saved data or logs."""
    if not 1 <= workers <= min(MAX_WORKERS, os.cpu_count() or 1):
        raise ValueError("workers exceed bounded local CPU limit")
    if not 1 <= len(expressions) <= MAX_FORMULAS:
        raise ValueError("invalid formula count")
    if len({x["id"] for x in expressions}) != len(expressions):
        raise ValueError("duplicate formulas")
    matrix = PrefixMatrix(rows, game, cache_entries=cache_entries,
                          max_temp_mib=max_temp_mib)
    if workers == 1:
        return OrderedDict((
            expr["id"], matrix.predict(expr, targets, backend=backend)
        ) for expr in expressions)
    per_group = max(1, math.ceil(len(expressions) / (workers * 2)))
    groups = [expressions[i:i + per_group]
              for i in range(0, len(expressions), per_group)]
    args = [(rows, game, list(targets), group, backend,
             cache_entries, max_temp_mib) for group in groups]
    with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        blocks = list(pool.map(_chunk_worker, args))
    return OrderedDict(
        (key, tickets) for block in blocks for key, tickets in block)


def _complexity(expr):
    return {"ATOM": 0, "DOUBLE": 1, "ADD": 2,
            "SUB": 2, "MUL": 3}[expr["family"]] + (
                1 if expr["left"] in ("LAG4", "LAG5") else 0)


def training_rank(rows, game, targets, expressions=GRAMMAR, *,
                  backend="numpy", workers=1, max_temp_mib=64):
    """Rank on development targets ONLY; no D2-target optimization."""
    if not 20 <= len(targets) <= 150 or max(targets) >= len(rows):
        raise ValueError("invalid development cohort")
    if sorted(targets) != list(range(min(targets), max(targets) + 1)):
        raise ValueError("development targets must be a contiguous interval")
    tickets = evaluate_grid(
        rows, game, targets, expressions,
        backend=backend, workers=workers, max_temp_mib=max_temp_mib)
    fm, fp, bm, bp = SPECS[game]
    n = len(targets)
    expected_front = n * fp * fp / fm
    expected_back = n * bp * bp / bm
    records = []
    for expr in expressions:
        preds = tickets[expr["id"]]
        front = sum(len(set(p["front"]) & set(rows[t]["front"]))
                    for p, t in zip(preds, targets))
        back = sum(len(set(p["back"]) & set(rows[t]["back"]))
                   for p, t in zip(preds, targets))
        score = ((front - expected_front) / (n * fp)
                 + (back - expected_back) / (n * bp)
                 - 0.002 * _complexity(expr))
        fingerprint = v1.digest(preds)
        records.append({
            "expr": expr, "score": round(score, 12),
            "front_total": front, "back_total": back,
            "behavior_digest": fingerprint,
        })
    records.sort(key=lambda x: (-x["score"], x["expr"]["id"]))
    roster = []
    families = Counter()
    fingerprints = set()
    for row in records:
        family = row["expr"]["family"]
        if families[family] >= MAX_PER_FAMILY or row["behavior_digest"] in fingerprints:
            continue
        families[family] += 1
        fingerprints.add(row["behavior_digest"])
        roster.append({"formula_id": row["expr"]["id"], "weight": 1,
                       "development_gain": row["score"]})
        if len(roster) == MAX_EXPERTS:
            break
    if len(roster) != MAX_EXPERTS:
        raise RuntimeError("not enough distinct candidates")
    fixed = {
        "schema": "SSQDLT_FROZEN_ACCEL_FORMULAS_V1",
        "game": game, "grammar_sha256": v1.digest(GRAMMAR),
        "validation_count": n, "validation_last_issue": str(rows[targets[-1]]["issue"]),
        "asof_history_sha256": v1.digest(rows[:max(targets) + 1]),
        "weights": "EQUAL_FIXED",
        "selection": roster,
        "tuning_d2": False,
        "independent_predraw_verified": False,
        "official_source_authenticated": False,
        "formal_A": 0, "edge": "NO_EDGE",
    }
    fixed["freeze_sha256"] = v1.digest(fixed)
    return fixed


def _ensemble(tickets, game, asof):
    fm, fp, bm, bp = SPECS[game]
    sums = {"front": defaultdict(int), "back": defaultdict(int)}
    for ticket in tickets:
        for area in ("front", "back"):
            for n in ticket[area]:
                sums[area][n] += 1
    ranks = {
        area: sorted(
            range(1, maximum + 1),
            key=lambda n: (-sums[area][n],
                           derive_seed("AUTO_VOTE_TIE_V1", game, asof, area, n)),
        ) for area, maximum in (("front", fm), ("back", bm))
    }
    front = sorted(ranks["front"][:fp])
    back = sorted(ranks["back"][:bp])
    return {"front": front, "back": back,
            "d2_pair": sorted(ranks["front"][:2])}


def wilson(hits, trials, z=1.959963984540054):
    if trials <= 0 or not 0 <= hits <= trials:
        raise ValueError("invalid binomial count")
    p = hits / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def holdout_evaluate(rows, game, *, validation=40, holdout=40, backend="numpy",
                     workers=1, expressions=GRAMMAR):
    """Synthetic/offline retrospective only. Test outcomes never reselect IDs."""
    _validate_rows(rows, game)
    test_start = len(rows) - holdout
    validation_start = test_start - validation
    if (type(holdout) is not int or not 20 <= holdout <= 300
            or type(validation) is not int or not 20 <= validation <= 150
            or validation_start < 100):
        raise ValueError("invalid frozen chronological split")
    frozen = training_rank(
        rows[:test_start], game, list(range(validation_start, test_start)),
        expressions=expressions, backend=backend, workers=workers)
    selected = tuple(FORMULA_BY_ID[x["formula_id"]] for x in frozen["selection"])
    grid = evaluate_grid(
        rows, game, list(range(test_start, len(rows))), selected,
        backend=backend, workers=workers)
    count = {
        "model": {"d2_hits": 0, "front_hits": 0, "back_hits": 0, "exact": 0},
        "research_null": {"d2_hits": 0, "front_hits": 0, "back_hits": 0, "exact": 0},
    }
    model_only = null_only = both = 0
    for step, target in enumerate(range(test_start, len(rows))):
        forecast = _ensemble(
            [grid[expr["id"]][step] for expr in selected],
            game, str(rows[target - 1]["issue"]))
        actual = rows[target]  # strictly score AFTER grid prediction computed
        baseline = v1.research_null(game, str(actual["issue"]))
        m, b = v1.hit_counts(forecast, actual), v1.hit_counts(baseline, actual)
        for group, stats in (("model", m), ("research_null", b)):
            count[group]["d2_hits"] += stats["d2"]
            count[group]["front_hits"] += stats["front_hits"]
            count[group]["back_hits"] += stats["back_hits"]
            count[group]["exact"] += stats["exact"]
        model_only += (m["d2"] == 1 and b["d2"] == 0)
        null_only += (m["d2"] == 0 and b["d2"] == 1)
        both += (m["d2"] == 1 and b["d2"] == 1)
    comparison = {
        "model_only": int(model_only), "null_only": int(null_only),
        "both": int(both),
        "neither": holdout - model_only - null_only - both,
        "p_exploratory_two_sided": v1.exact_paired_p(
            model_only, null_only),
    }
    return {
        "schema": SCHEMA,
        "game": game, "validation": validation, "holdout": holdout,
        "expressions_scanned": len(expressions),
        "frozen_selection_sha256": frozen["freeze_sha256"],
        "selected_formula_ids": [x["formula_id"] for x in frozen["selection"]],
        "aggregates_only": count,
        "paired_same_issue": comparison,
        "theoretical_d2_chance": chance(game)["dan2_probability"],
        "wilson95_model_d2": wilson(count["model"]["d2_hits"], holdout),
        "independent_predraw_verified": False,
        "prospective_scored": 0, "formal_A": 0, "edge": "NO_EDGE",
        "source": "CALLER_SUPPLIED_OFFLINE_ONLY",
    }


def bounded_formula_search(rows, game, targets, *,
                           seconds=3.0, max_temp_mib=64,
                           backend="numba", chunk_size=12):
    """Finite best-effort CPU-time budget. Never choose based on final holdout."""
    if not 0.05 <= seconds <= 3600 or not 1 <= chunk_size <= 64:
        raise ValueError("unsafe budget")
    if backend == "numba" and _mode_numba is None:
        backend = "numpy"
    engine = PrefixMatrix(rows, game, max_temp_mib=max_temp_mib)
    t0 = time.process_time()
    records = []
    for start in range(0, len(GRAMMAR), chunk_size):
        for expr in GRAMMAR[start:start + chunk_size]:
            predictions = engine.predict(expr, targets, backend=backend)
            # No observations used to stop, only measured CPU consumption.
            records.append({
                "formula_id": expr["id"], "prediction_digest": v1.digest(predictions),
            })
        if time.process_time() - t0 >= seconds:
            break
    return {
        "candidates_evaluated": len(records), "candidates_possible": len(GRAMMAR),
        "tested_formula_ids_digest": v1.digest([x["formula_id"] for x in records]),
        "cpu_seconds": time.process_time() - t0,
        "budget_seconds": seconds, "max_temp_mib": max_temp_mib,
        "cache_hits": engine.cache_hits, "cache_misses": engine.cache_misses,
        "complete_search": len(records) == len(GRAMMAR),
        "time_limited": len(records) < len(GRAMMAR),
        "no_holdout_outcomes_used": True, "formal_A": 0,
    }


def holm_adjust(p_values):
    """Familywise exploratory correction across predeclared game comparisons."""
    if not p_values or any(
            not isinstance(p, (float, int)) or not math.isfinite(p)
            or p < 0 or p > 1 for p in p_values):
        raise ValueError("invalid testing family")
    ordered = sorted(range(len(p_values)), key=lambda i: (p_values[i], i))
    out = [0.0] * len(p_values)
    maximum = 0.0
    for rank, index in enumerate(ordered):
        maximum = max(maximum, min(1.0, p_values[index] * (
            len(p_values) - rank)))
        out[index] = maximum
    return out


def synthetic_two_game_holdout(*, history=190, validation=20, holdout=20,
                               backend="numpy", workers=1):
    """Aggregate-only synthetic experiment; two-game Holm family (not official)."""
    if not 150 <= history <= 500:
        raise ValueError("synthetic history budget exceeded")
    # Include every operator family, preserving predeclared deterministic order.
    expressions = tuple(x for x in GRAMMAR if x["window"] == 8)
    outputs = [holdout_evaluate(
        synthetic_rows(game, n=history), game, validation=validation,
        holdout=holdout, backend=backend, workers=workers,
        expressions=expressions) for game in ("ssq", "dlt")]
    corrected = holm_adjust([
        out["paired_same_issue"]["p_exploratory_two_sided"]
        for out in outputs
    ])
    for output, adjusted in zip(outputs, corrected):
        output["paired_same_issue"]["p_holm_two_games_exploratory"] = adjusted
        output["paired_same_issue"]["predeclared_family_size"] = 2
    return {
        "schema": SCHEMA,
        "experiment": "SYNTHETIC_ONLY_FROZEN_TWO_GAME_EXPLORATION",
        "games": {x["game"]: x for x in outputs},
        "formally_admissible": False,
        "prospective_scored": 0,
        "formal_A": 0, "edge": "NO_EDGE",
    }
