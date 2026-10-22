"""V4.6 isolated research core. No network, purchase, or formal A promotion."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from itertools import combinations

MODELS = ("hot60", "ewma", "shrinkmix", "pairwise_d2", "challenger", "random_null")
RULES = {
    "SSQ": {"pool": 33, "front": 6, "back_pool": 16, "back": 1, "d2": 15 / 528},
    "DLT": {"pool": 35, "front": 5, "back_pool": 12, "back": 2, "d2": 10 / 595},
}
MIN_STUDY_HISTORY = 120
VERSION = "v47-research-core-0.1"
NULL_SEED = "SSQ-DLT-V47-NULL-SHA256-SORT-v1-20261022"  # pre-registered new control stream
RANKING_TIE_BREAK = "score_descending_then_numeric_ascending"
TICKET_BACK_ENGINE = "SHA256_SORT_V1"
PARAMETERS = {
    "hot60": {"window": 60, "tie_break": "numeric_ascending"},
    "ewma": {"window": 120, "weight_decay": 0.92, "input_weight": 0.08},
    "shrinkmix": {"recent_window": 60, "tau": 200},
    "pairwise_d2": {"window": 120, "pair_residual_tau": 200},
    "challenger": {"windows": [30, 60, 120], "rule": "maximin_pair_score"},
    "random_null": {"seed": NULL_SEED, "engine": TICKET_BACK_ENGINE},
}


class GateError(ValueError):
    """A hard research gate failed; never fabricate a prediction."""


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def model_source_sha256():
    """SHA256 of the exact installed model-core source bytes."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def parameter_contract(model):
    """Include global tie-break, lottery rules and ticket generation in the parameter identity."""
    if model not in MODELS:
        raise GateError("unknown model for parameter contract")
    return {
        "contract": "V47-PARAMETER-CONTRACT-1",
        "model": model,
        "model_version": VERSION,
        "model_parameters": PARAMETERS[model],
        "ranking_tie_break": RANKING_TIE_BREAK,
        "lottery_rules_sha256": digest(RULES),
        "ticket_back": {
            "engine": TICKET_BACK_ENGINE,
            "seed_id": NULL_SEED,
            "derivation": "sha256(joined identity fields); rank each ball by sha256(prefix|ball)",
        },
    }


def dt(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise GateError("invalid ISO timestamp") from exc
    if stamp.tzinfo is None:
        raise GateError("timestamp must include timezone")
    return stamp


def _balls(values, maximum, required):
    if (not isinstance(values, list) or len(values) != required
            or any(type(v) is not int or v < 1 or v > maximum for v in values)
            or len(set(values)) != required or values != sorted(values)):
        raise GateError("invalid or noncanonical draw balls")


def validate_snapshot(snapshot):
    """Strict as-of structure only. Official authenticity requires 01 review."""
    if not isinstance(snapshot, dict) or snapshot.get("lottery") not in RULES:
        raise GateError("invalid lottery")
    r = RULES[snapshot["lottery"]]
    draws = snapshot.get("draws")
    if not isinstance(draws, list) or not draws:
        raise GateError("missing draw history")
    as_of, cutoff, target_time = (dt(snapshot[k]) for k in
                                  ("as_of", "sales_cutoff", "target_draw_at"))
    if not as_of < cutoff <= target_time:
        raise GateError("time lock violation")
    if not str(snapshot.get("target_issue", "")).isdigit():
        raise GateError("invalid target issue")
    last_issue, last_time = -1, None
    for draw in draws:
        issue = str(draw.get("issue", ""))
        if not issue.isdigit() or int(issue) <= last_issue:
            raise GateError("duplicate/out-of-order issue")
        last_issue = int(issue)
        _balls(draw["front"], r["pool"], r["front"])
        _balls(draw["back"], r["back_pool"], r["back"])
        occurred = dt(draw["drawn_at"])
        published = dt(draw["published_at"])
        if not occurred <= published <= as_of:
            raise GateError("future data or invalid publication time")
        if last_time is not None and occurred <= last_time:
            raise GateError("time travel or out-of-order draw")
        last_time = occurred
    if int(snapshot["target_issue"]) <= last_issue:
        raise GateError("target not strictly future")
    if not last_time < as_of:
        raise GateError("last draw later than snapshot")
    return digest(snapshot)


def validate_study_snapshot(snapshot):
    """Admission gate for a complete six-stream research run; structure alone is not official proof."""
    checksum = validate_snapshot(snapshot)
    if len(snapshot["draws"]) < MIN_STUDY_HISTORY:
        raise GateError("study requires at least 120 historical draws")
    return checksum


def _stable_permutation(values, *parts):
    """Cross-platform deterministic permutation independent of Python's random module."""
    prefix = "|".join(map(str, parts)).encode("utf-8")
    return sorted(
        values,
        key=lambda value: (
            hashlib.sha256(prefix + b"|" + str(value).encode("ascii")).digest(),
            value,
        ),
    )


def _rank(scores):
    # fixed and reproducible tie-break: numeric ascending
    return sorted(scores, key=lambda n: (-scores[n], n))


def _freq(draws, n, pool):
    count = Counter(x for d in draws[-n:] for x in d["front"])
    return {i: count[i] / min(n, len(draws)) for i in range(1, pool + 1)}


def _pair_scores(draws, pool, window=120):
    tail = draws[-window:]
    n = len(tail)
    counts = Counter(x for d in tail for x in d["front"])
    pairs = Counter(p for d in tail for p in combinations(d["front"], 2))
    k = len(tail[0]["front"])
    scores = {}
    for a, b in combinations(range(1, pool + 1), 2):
        expected = counts[a] * counts[b] * (k - 1) / (n * k)
        # residual shrunk to limit rare-pair noise; hypothesis, not advantage
        residual = (pairs[(a, b)] - expected) / (n + 200)
        scores[(a, b)] = ((counts[a] + counts[b]) / n) + residual
    return scores


def _model_ranking(snapshot, model):
    r = RULES[snapshot["lottery"]]
    history, pool = snapshot["draws"], r["pool"]
    if model == "hot60":
        if len(history) < 60:
            raise GateError("hot60 needs 60 historical draws")
        return _rank(_freq(history, 60, pool))
    if model == "ewma":
        if len(history) < 60:
            raise GateError("ewma needs 60 historical draws")
        weights = {n: 0.0 for n in range(1, pool + 1)}
        for d in history[-120:]:
            for n in weights:
                weights[n] *= .92
            for n in d["front"]:
                weights[n] += .08
        return _rank(weights)
    if model == "shrinkmix":
        if len(history) < 60:
            raise GateError("shrinkmix needs 60 historical draws")
        recent = _freq(history, 60, pool)
        lifetime = _freq(history, len(history), pool)
        k = 60 / (60 + 200)
        return _rank({i: k * recent[i] + (1 - k) * lifetime[i] for i in recent})
    if model == "pairwise_d2":
        if len(history) < 120:
            raise GateError("pairwise_d2 registered window requires 120 historical draws")
        pairs = _pair_scores(history, pool)
        first, second = sorted(pairs, key=lambda p: (-pairs[p], p))[0]
        rest = [n for n in _rank(_freq(history, 60, pool))
                if n not in (first, second)]
        return [first, second] + rest
    if model == "challenger":
        if len(history) < 120:
            raise GateError("challenger needs 120 historical draws")
        windows = [ _pair_scores(history[-w:], pool, w) for w in (30, 60, 120) ]
        pairs = windows[0].keys()
        # Robust minimum across fixed windows; a separate falsifiable hypothesis.
        best = min(pairs, key=lambda p: (-min(d[p] for d in windows), p))
        rest = [n for n in _rank(_freq(history, 120, pool))
                if n not in best]
        return [*best] + rest
    if model == "random_null":
        nums = list(range(1, pool + 1))
        return _stable_permutation(nums, NULL_SEED, snapshot["lottery"],
                                   snapshot["target_issue"], "front")
    raise GateError("unknown model")


def forecast(snapshot, model):
    snapshot_sha = validate_snapshot(snapshot)
    if model not in MODELS:
        raise GateError("model not preregistered")
    r = RULES[snapshot["lottery"]]
    ranking = _model_ranking(snapshot, model)
    first_five = ranking[:5]
    front = sorted(ranking[:r["front"]])
    others = _stable_permutation(
        list(range(1, r["back_pool"] + 1)), NULL_SEED,
        snapshot["lottery"], snapshot["target_issue"], model, "back"
    )
    back = sorted(others[:r["back"]])
    prediction = {
        "version": VERSION,
        "model": model,
        "lottery": snapshot["lottery"],
        "target_issue": str(snapshot["target_issue"]),
        "snapshot_sha256": snapshot_sha,
        "parameters_sha256": digest(parameter_contract(model)),
        "model_source_sha256": model_source_sha256(),
        "candidates_1_to_5": first_five,
        "primary_d2": first_five[:2],
        "ticket": {"front": front, "back": back},
        "null_seed_id": NULL_SEED if model == "random_null" else None,
        "evidence_class": "SHADOW",
        "formal_a_eligible": False,
    }
    validate_forecast(prediction, snapshot)
    return prediction


def validate_forecast(prediction, snapshot):
    if prediction.get("snapshot_sha256") != validate_snapshot(snapshot):
        raise GateError("snapshot mismatch")
    if prediction.get("target_issue") != str(snapshot["target_issue"]):
        raise GateError("issue mismatch")
    if prediction.get("lottery") != snapshot["lottery"] or prediction.get("model") not in MODELS:
        raise GateError("identity mismatch")
    if prediction.get("parameters_sha256") != digest(parameter_contract(prediction["model"])):
        raise GateError("model parameters mismatch")
    if prediction.get("model_source_sha256") != model_source_sha256():
        raise GateError("model source SHA256 mismatch")
    r = RULES[snapshot["lottery"]]
    candidates = prediction.get("candidates_1_to_5")
    if (not isinstance(candidates, list) or len(candidates) != 5
            or len(set(candidates)) != 5
            or any(type(x) is not int or not 1 <= x <= r["pool"] for x in candidates)
            or prediction.get("primary_d2") != candidates[:2]):
        raise GateError("invalid ordered candidates or primary D2")
    ticket = prediction.get("ticket", {})
    _balls(ticket.get("front"), r["pool"], r["front"])
    _balls(ticket.get("back"), r["back_pool"], r["back"])
    if not set(candidates).issubset(ticket["front"]):
        raise GateError("five candidates must be included in ticket")
    if prediction.get("formal_a_eligible") is not False:
        raise GateError("research core cannot grant formal A")
    if prediction.get("version") != VERSION or prediction.get("evidence_class") != "SHADOW":
        raise GateError("model version or research evidence class mismatch")
    if prediction.get("null_seed_id") != (NULL_SEED if prediction["model"] == "random_null" else None):
        raise GateError("NULL seed attribution mismatch")
    # Reconstruct deterministically, including legal filler and rear-zone balls.
    # Merely checking ball ranges allows a valid-looking substituted ticket.
    expected_ranking = _model_ranking(snapshot, prediction["model"])
    if candidates != expected_ranking[:5]:
        raise GateError("candidate ranking does not match declared model")
    if ticket["front"] != sorted(expected_ranking[:r["front"]]):
        raise GateError("ticket front does not match declared model")
    expected_back = _stable_permutation(
        list(range(1, r["back_pool"] + 1)), NULL_SEED,
        snapshot["lottery"], snapshot["target_issue"], prediction["model"], "back"
    )
    if ticket["back"] != sorted(expected_back[:r["back"]]):
        raise GateError("ticket back does not match declared model")
    return True


SCHEMA = """
-- One immutable snapshot identity per RUN_ID and lottery. A six-agent batch
-- must never silently mix differently sourced histories or target issues.
CREATE TABLE IF NOT EXISTS run_context (
    run_id TEXT NOT NULL,
    lottery TEXT NOT NULL CHECK(lottery IN ('SSQ', 'DLT')),
    target_issue TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    as_of TEXT NOT NULL,
    sales_cutoff TEXT NOT NULL,
    PRIMARY KEY(run_id, lottery)
);
CREATE TRIGGER IF NOT EXISTS prevent_context_update BEFORE UPDATE ON run_context
BEGIN SELECT RAISE(ABORT, 'immutable run context'); END;
CREATE TRIGGER IF NOT EXISTS prevent_context_delete BEFORE DELETE ON run_context
BEGIN SELECT RAISE(ABORT, 'immutable run context'); END;
CREATE TABLE IF NOT EXISTS predictions (
    run_id TEXT NOT NULL,
    lottery TEXT NOT NULL,
    model TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    prediction_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    evidence_class TEXT NOT NULL CHECK(evidence_class='SHADOW'),
    PRIMARY KEY(run_id, lottery, model)
);
CREATE TRIGGER IF NOT EXISTS prevent_prediction_update BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'immutable prediction'); END;
CREATE TRIGGER IF NOT EXISTS prevent_prediction_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'immutable prediction'); END;
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS prevent_audit_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
CREATE TRIGGER IF NOT EXISTS prevent_audit_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
"""


def init_ledger(conn):
    conn.executescript(SCHEMA)


def freeze_shadow(conn, run_id, snapshot, prediction, frozen_at):
    """Atomic local record. This is NOT an external trustworthy timestamp."""
    validate_study_snapshot(snapshot)
    validate_forecast(prediction, snapshot)
    if not run_id or not isinstance(run_id, str):
        raise GateError("missing run id")
    if not dt(snapshot["as_of"]) <= dt(frozen_at) < dt(snapshot["sales_cutoff"]):
        raise GateError("prediction not before sales cutoff")
    # The context must be pinned before inserting the first agent prediction.
    # This is only a local consistency guard, not official provenance or TSA.
    identity = (
        str(snapshot["target_issue"]), prediction["snapshot_sha256"],
        snapshot["as_of"], snapshot["sales_cutoff"],
    )
    existing = conn.execute(
        "SELECT target_issue,snapshot_sha256,as_of,sales_cutoff "
        "FROM run_context WHERE run_id=? AND lottery=?",
        (run_id, prediction["lottery"]),
    ).fetchone()
    if existing is None:
        # A pre-v0.3 ledger can already contain predictions without this
        # manifest. Fail closed rather than silently pinning an incompatible
        # snapshot; legacy data require a new RUN_ID and separate audit.
        legacy = conn.execute(
            "SELECT 1 FROM predictions WHERE run_id=? AND lottery=? LIMIT 1",
            (run_id, prediction["lottery"]),
        ).fetchone()
        if legacy is not None:
            raise GateError("legacy run lacks context; start a new RUN_ID")
        conn.execute(
            "INSERT INTO run_context "
            "(run_id,lottery,target_issue,snapshot_sha256,as_of,sales_cutoff) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, prediction["lottery"], *identity),
        )
    elif tuple(existing) != identity:
        raise GateError("RUN_ID lottery context mismatch: different snapshot or target")
    payload = canon(prediction)
    prediction_sha = hashlib.sha256(payload.encode()).hexdigest()
    # No implicit commit: a caller can atomically freeze all model records.
    # The caller owns the transaction; SHADOW does not claim trusted time.
    # Exact retries are idempotent: never change the original frozen_at or
    # re-emit a freeze event. Any changed content remains a hard conflict.
    previous = conn.execute(
        "SELECT prediction_sha256,payload FROM predictions "
        "WHERE run_id=? AND lottery=? AND model=?",
        (run_id, prediction["lottery"], prediction["model"]),
    ).fetchone()
    if previous is not None:
        if previous != (prediction_sha, payload):
            raise GateError("conflicting repeated prediction")
        return prediction_sha
    conn.execute(
        "INSERT INTO predictions VALUES(?,?,?,?,?,?,?,?)",
        (run_id, prediction["lottery"], prediction["model"], frozen_at,
         prediction["snapshot_sha256"], prediction_sha, payload, "SHADOW"))
    conn.execute(
        "INSERT INTO audit_events(run_id,event_type,payload) VALUES(?,?,?)",
        (run_id, "LOCAL_SHADOW_FREEZE", canon({
            "model": prediction["model"], "lottery": prediction["lottery"],
            "prediction_sha256": prediction_sha, "external_tsa": "NOT_RUN"})))
    return prediction_sha


def score(frozen_prediction, official_result):
    """Read-only per-draw diagnostic scoring; no proof of prediction advantage."""
    if (frozen_prediction["lottery"] != official_result["lottery"]
            or frozen_prediction["target_issue"] != str(official_result["issue"])):
        raise GateError("wrong issue or lottery")
    r = RULES[frozen_prediction["lottery"]]
    _balls(official_result["front"], r["pool"], r["front"])
    _balls(official_result["back"], r["back_pool"], r["back"])
    found = set(official_result["front"])
    picks = frozen_prediction["candidates_1_to_5"]
    d = {f"D{k}": int(set(picks[:k]).issubset(found)) for k in range(1, 6)}
    d["hit_count_5"] = len(set(picks) & found)
    d["ticket_front_hits"] = len(set(frozen_prediction["ticket"]["front"]) & found)
    d["ticket_back_hits"] = len(set(frozen_prediction["ticket"]["back"]) & set(official_result["back"]))
    return d
