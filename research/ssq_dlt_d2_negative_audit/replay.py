"""Exact replay of the already exposed DLT scrambled-pair negative control.

This is forensic reproduction, not an additional seed or an efficacy test.
The only randomness consumed is the original registered RNG stream.  The
prefix guard checks index/identity structure; it cannot prove historical
real-world data availability or detect a future value relabelled as old data.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import hashlib
from itertools import combinations
import json
import math
import random

from research.ssq_dlt_d2_next import models as candidates
from research.ssq_dlt_d2_next import simulation as prior
from research.ssq_dlt_v45 import models as original


GAME = "DLT"
SCENARIO = "SCRAMBLED_PAIR_STRONG"
TARGET_MODEL = "R46-REPLICATED-PAIR"
MODEL_IDS = (*candidates.MODEL_IDS, original.PRIMARY_MODEL, original.NULL_MODEL)
ALL_IDS = (*MODEL_IDS, "GENERATOR_REFERENCE_PAIR")
WARMUP = 240
EVALUATION = 240
REPLICATIONS = 12


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _state_sha(rng):
    # getstate() is observational.  In particular, never subclass Random:
    # overriding random() can change sample()'s _randbelow implementation.
    return _sha(rng.getstate())


def _legal_numbers(numbers, count, maximum, reason):
    if (type(numbers) is not list or len(numbers) != count
            or any(type(x) is not int or not 1 <= x <= maximum for x in numbers)
            or len(set(numbers)) != count or numbers != sorted(numbers)):
        raise ValueError(reason)


def trace_stream(replication: int) -> tuple[list, list]:
    """Reproduce all 480 original draws without changing RNG consumption."""
    if type(replication) is not int or not 0 <= replication < REPLICATIONS:
        raise ValueError("UNREGISTERED_REPLICATION")
    n, k, _, bk = original.RULES[GAME]
    seed = prior.stream_seed(GAME, SCENARIO, replication)
    rng = random.Random(seed)
    initialization_before = _state_sha(rng)
    # Although this scenario never uses ring, the old generator samples it.
    ring = rng.sample(range(1, n + 1), n)
    initialization_after = _state_sha(rng)
    odds = prior.SPEC["strong_pair_odds_ratio"]
    p0 = k * (k - 1) / (n * (n - 1))
    probability = odds * p0 / (1 + (odds - 1) * p0)
    pair = [1, 2]
    others = [x for x in range(1, n + 1) if x not in pair]
    rows, traces = [], []
    for index in range(WARMUP + EVALUATION):
        before = _state_sha(rng)
        branch_random = rng.random()
        attempts = 0
        rejected = []
        if branch_random < probability:
            branch = "PAIR_HIT"
            latent = sorted(pair + rng.sample(others, k - 2))
        else:
            branch = "PAIR_MISS"
            for attempts in range(1, 1001):
                latent = sorted(rng.sample(range(1, n + 1), k))
                if not set(pair) <= set(latent):
                    break
                rejected.append(latent)
            else:
                raise ValueError("SYNTHETIC_REJECTION_LIMIT")
        after_tilt = _state_sha(rng)
        permutation = rng.sample(range(1, n + 1), n)
        front = sorted(permutation[x - 1] for x in latent)
        after = _state_sha(rng)
        row = dict(game=GAME, issue=f"{index + 1:05d}",
                   draw_date=(date(2000, 1, 1) + timedelta(days=index)).isoformat(),
                   front=front, back=list(range(1, bk + 1)))
        rows.append(row)
        trace = dict(replication=replication, index=index,
                     rng_state_before_sha256=before,
                     rng_state_after_tilt_sha256=after_tilt,
                     rng_state_after_sha256=after,
                     tilt_branch=branch, branch_random=branch_random,
                     conditional_latent_pair_hit_probability=probability,
                     rejection_attempts=attempts, rejected_draws=rejected,
                     latent_front=latent, permutation=permutation,
                     output=front)
        if index == 0:
            trace["initialization"] = dict(
                seed=seed, unused_ring=ring,
                rng_state_before_sha256=initialization_before,
                rng_state_after_sha256=initialization_after)
        traces.append(trace)
    return rows, traces


def _target_records(document):
    """Validate the entire target keyspace before any expensive predictions."""
    if type(document) is not dict or type(document.get("periods")) is not list:
        raise ValueError("SYNTHETIC_DOCUMENT_REQUIRED")
    if document.get("spec") != prior.SPEC:
        raise ValueError("REGISTERED_SPEC_MISMATCH")
    records = {}
    for row in document["periods"]:
        if type(row) is not dict:
            raise ValueError("PERIOD_OBJECT_REQUIRED")
        if row.get("game") != GAME or row.get("scenario") != SCENARIO:
            continue
        replication, index = row.get("replication"), row.get("index")
        if (type(replication) is not int or type(index) is not int
                or not 0 <= replication < REPLICATIONS
                or not WARMUP <= index < WARMUP + EVALUATION):
            raise ValueError("TARGET_RECORD_OUT_OF_RANGE")
        key = (replication, index)
        if key in records:
            raise ValueError("DUPLICATE_TARGET_RECORD")
        end = row.get("training_end")
        if type(end) is not int or end != index - 1:
            raise ValueError("TRAINING_PREFIX_BOUNDARY_MISMATCH")
        _legal_numbers(row.get("draw_front"), 5, 35, "INVALID_STORED_FRONT")
        predictions, hits = row.get("predictions"), row.get("hits")
        if (type(predictions) is not dict or set(predictions) != set(ALL_IDS)
                or type(hits) is not dict or set(hits) != set(ALL_IDS)):
            raise ValueError("EXACT_REGISTERED_MODELS_REQUIRED")
        for model in ALL_IDS:
            _legal_numbers(predictions[model], 2, 35, "INVALID_STORED_D2")
            hit = hits[model]
            if type(hit) is not int or hit not in (0, 1):
                raise ValueError("INVALID_STORED_HIT")
            independently_scored = int(set(predictions[model]) <= set(row["draw_front"]))
            if hit != independently_scored:
                raise ValueError("STORED_HIT_SCORING_MISMATCH")
        loss = row.get("cbpair_brier")
        if (isinstance(loss, bool) or not isinstance(loss, (int, float))
                or not math.isfinite(loss) or not 0 <= loss <= 1):
            raise ValueError("INVALID_STORED_BRIER")
        if row.get("formal_A") != 0 or row.get("decision") != "NO_EDGE":
            raise ValueError("RESEARCH_BOUNDARY_MISMATCH")
        records[key] = row
    expected = {(rep, index) for rep in range(REPLICATIONS)
                for index in range(WARMUP, WARMUP + EVALUATION)}
    if set(records) != expected:
        raise ValueError("MISSING_TARGET_RECORDS")
    return records


def _guard_prefix(prefix, index):
    """Reject observed index/identity future inclusion, not hidden availability."""
    if (type(index) is not int or not WARMUP <= index < WARMUP + EVALUATION
            or type(prefix) is not list or len(prefix) != index):
        raise ValueError("PREFIX_LENGTH_OR_TARGET_INCLUSION")
    for position, row in enumerate(prefix):
        if (type(row) is not dict or row.get("game") != GAME
                or row.get("issue") != f"{position + 1:05d}"
                or row.get("draw_date") != (date(2000, 1, 1) + timedelta(days=position)).isoformat()):
            raise ValueError("PREFIX_INDEX_IDENTITY_MISMATCH")


def _predictions(prefix, replication, index):
    _guard_prefix(prefix, index)
    new = candidates.predict_candidates(GAME, prefix)
    pairs = tuple(combinations(range(1, 36), 2))
    recent = prefix[-60:]
    counts = Counter(pair for row in recent for pair in combinations(row["front"], 2))
    marginals = Counter(x for row in recent for x in row["front"])
    primary = list(min(pairs, key=lambda pair: (
        -counts[pair], -marginals[pair[0]] - marginals[pair[1]], pair)))
    null = sorted(original._sample(
        original.DEFAULT_SEED, GAME,
        f"SYNTHETIC:{SCENARIO}:{replication}:{index}",
        original.NULL_MODEL, "dan", 2, 35))
    predictions = {model: new[model]["d2"] for model in candidates.MODEL_IDS}
    predictions.update({original.PRIMARY_MODEL: primary,
                        original.NULL_MODEL: null,
                        "GENERATOR_REFERENCE_PAIR": [1, 2]})
    return predictions, new


def _prefix_check(rows, replication, index, expected):
    # Perturb every target/future front while preserving distinct/legal size.
    # The production call receives only [:index], never this suffix.
    mutated = [dict(row, front=list(row["front"])) for row in rows]
    for row in mutated[index:]:
        row["front"] = sorted((x % 35) + 1 for x in row["front"])
    actual, _ = _predictions(mutated[:index], replication, index)
    if actual != expected:
        raise ValueError("PREFIX_PREDICTION_CHANGED_BY_FUTURE")
    try:
        _predictions(mutated[:index + 1], replication, index)
    except ValueError as exc:
        if str(exc) != "PREFIX_LENGTH_OR_TARGET_INCLUSION":
            raise
    else:
        raise ValueError("PREFIX_FUTURE_INJECTION_NOT_REJECTED")
    return dict(replication=replication, index=index,
                prefix_sha256=_sha(rows[:index]), predictions_sha256=_sha(expected),
                target_and_future_mutation_unchanged=True,
                target_inclusion_rejected=True,
                scope="INDEX_IDENTITY_PREFIX_GUARD_NOT_REAL_WORLD_AVAILABILITY_PROOF")


def replay_target(document, progress=None) -> dict:
    """Fully replay the original 12 x 240 scored target records."""
    stored = _target_records(document)
    replayed, traces, draws, checks = [], [], [], []
    totals = {model: 0 for model in ALL_IDS}
    per_replication = []
    for replication in range(REPLICATIONS):
        rows, stream_traces = trace_stream(replication)
        original_rows, _ = prior.synthetic_history(GAME, SCENARIO, replication)
        if rows != original_rows:
            raise ValueError("ORIGINAL_GENERATOR_STREAM_MISMATCH")
        traces.extend(stream_traces)
        draws.extend(dict(replication=replication, index=i, **row)
                     for i, row in enumerate(rows))
        rep_hits = {model: 0 for model in ALL_IDS}
        for index in range(WARMUP, WARMUP + EVALUATION):
            record = stored[replication, index]
            if record["draw_front"] != rows[index]["front"]:
                raise ValueError("STORED_FRONT_GENERATOR_MISMATCH")
            predictions, new = _predictions(rows[:index], replication, index)
            if predictions != record["predictions"]:
                raise ValueError("STORED_D2_REPLAY_MISMATCH")
            hits = {model: int(set(pair) <= set(rows[index]["front"]))
                    for model, pair in predictions.items()}
            if hits != record["hits"]:
                raise ValueError("REPLAY_HIT_SCORING_MISMATCH")
            probabilities = new[candidates.MODEL_IDS[0]]["pair_probabilities"]
            front_pairs = tuple(combinations(rows[index]["front"], 2))
            loss = (sum(q * q for q in probabilities.values())
                    - 2 * sum(probabilities[pair] for pair in front_pairs) + 10) / 595
            if not math.isclose(loss, record["cbpair_brier"], rel_tol=1e-12, abs_tol=1e-15):
                raise ValueError("STORED_BRIER_REPLAY_MISMATCH")
            for model, hit in hits.items():
                totals[model] += hit
                rep_hits[model] += hit
            replayed.append(dict(game=GAME, scenario=SCENARIO,
                                 replication=replication, index=index,
                                 training_end=index - 1, predictions=predictions,
                                 hits=hits, draw_front=rows[index]["front"],
                                 cbpair_brier=loss, formal_A=0, decision="NO_EDGE"))
            if index in (240, 359, 479):
                checks.append(_prefix_check(rows, replication, index, predictions))
        per_replication.append(dict(replication=replication, n=EVALUATION, hits=rep_hits))
        if progress:
            progress(dict(stage="exact_original_stream_replay", replication=replication,
                          n=len(replayed), target_hits=totals[TARGET_MODEL]))
    prediction_rows = [dict(replication=row["replication"], index=row["index"],
                            predictions=row["predictions"]) for row in replayed]
    return dict(schema="ssq-dlt-negative-original-replay-1", game=GAME,
                scenario=SCENARIO, status="PASS", n=len(replayed),
                target_model=TARGET_MODEL, target_hits=totals[TARGET_MODEL],
                expected_prior_target_hits=69,
                original_anomaly_reproduced=(totals[TARGET_MODEL] == 69),
                scored_hits=totals, per_replication=per_replication,
                predictions_sha256=_sha(prediction_rows), draws_sha256=_sha(draws),
                trace_sha256=_sha(traces), prefix_only_checks=checks,
                records=replayed, traces=traces, draws=draws,
                formal_A=0, decision="NO_EDGE",
                scope="FORENSIC_REPLAY_OF_EXPOSED_SYNTHETIC_DATA_NOT_LOTTERY_EFFICACY")
