"""Fail-closed V4.6 research wrapper of the pinned V4.5 algorithms.

No official-target admission, TSA, formal slot substitution or prediction edge.
Chat tabs are human handoff surfaces, not automatically connected agents.
"""
from __future__ import annotations

import itertools
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.ssq_dlt_v45 import models as prior


class HarnessBlocked(ValueError):
    pass


ROLES = {
    "test1": "00-CONTROL",
    "test2": "01-OFFICIAL-DATA",
    "test3": "02-HOT60",
    "test4": "03-EWMA",
    "test5": "04-SHRINKMIX",
    "test6": "05-PAIRWISE-D2",
    "test7": "06-STABILITY-CHALLENGER",
    "test8": "07-RANDOM-NULL",
    "test9": "08-INDEPENDENT-AUDIT",
    "test10": "09-HARNESS-ENGINEERING",
}
MODELS = (
    "02-HOT60", "03-EWMA", "04-SHRINKMIX",
    "05-PAIRWISE-D2", "06-STABILITY-CHALLENGER", "07-RANDOM-NULL",
)
VERSION = "R46-RESEARCH-PROTOTYPE-1"


def _time(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HarnessBlocked("AWARE_TIMESTAMP_REQUIRED") from exc


def _history_guard(game, issue, history, asof, target_at):
    if game not in prior.RULES or not history or len(history) < 60:
        raise HarnessBlocked("VALID_60_DRAW_HISTORY_REQUIRED")
    if not _time(asof) < _time(target_at):
        raise HarnessBlocked("TARGET_MUST_FOLLOW_ASOF")
    try:
        prior.validate_history(game, issue, history)
    except prior.ModelBlocked as exc:
        raise HarnessBlocked(str(exc)) from exc
    last = None
    for row in history:
        moment = _time(row.get("draw_at"))
        if moment >= _time(asof) or (last is not None and moment <= last):
            raise HarnessBlocked("FUTURE_OR_UNSORTED_HISTORY_TIME")
        last = moment


def _stability(history, upper):
    # Exploratory only; not the blocked U/R/C registered challenger.
    a = Counter(n for row in history[-60:-30] for n in row["front"])
    b = Counter(n for row in history[-30:] for n in row["front"])
    return sorted(range(1, upper + 1),
                  key=lambda n: (-min(a[n], b[n]), -(a[n] + b[n]), n))


def generate(game, issue, history, *, asof, target_draw_at, seed=20261018):
    """Deterministic isolated research candidates. Caller targets are UNVERIFIED."""
    _history_guard(game, issue, history, asof, target_draw_at)
    if type(seed) is not int or seed < 0:
        raise HarnessBlocked("INVALID_SEED")
    upper, front_count, back_upper, back_count = prior.RULES[game]
    front_scores = prior._scores(history, "front", upper, front_count)
    back_scores = prior._scores(history, "back", back_upper, back_count)
    ranks = {}
    for name, key in (("02-HOT60", "R45-HOT60"),
                      ("03-EWMA", "R45-EWMA"),
                      ("04-SHRINKMIX", "R45-SHRINKMIX")):
        ranks[name] = prior._ranking(front_scores[key], upper)
    pair = prior._best_pair(history, front_scores["R45-PAIRWISE-D2"], upper)
    ranks["05-PAIRWISE-D2"] = pair + [
        n for n in prior._ranking(front_scores["R45-PAIRWISE-D2"], upper)
        if n not in pair
    ]
    ranks["06-STABILITY-CHALLENGER"] = _stability(history, upper)
    ranks["07-RANDOM-NULL"] = prior._sample(
        seed, game, issue, "R46-NULL", "front-rank", upper, upper
    )
    result = {}
    for name in MODELS:
        rank = ranks[name]
        front = sorted(rank[:front_count])
        if name == "07-RANDOM-NULL":
            back = sorted(prior._sample(seed, game, issue, "R46-NULL",
                                        "back", back_count, back_upper))
        else:
            back_key = {
                "02-HOT60": "R45-HOT60",
                "03-EWMA": "R45-EWMA",
                "04-SHRINKMIX": "R45-SHRINKMIX",
            }.get(name, "R45-SHRINKMIX")
            back = sorted(prior._ranking(back_scores[back_key], back_upper)[:back_count])
        candidate = {
            "ordered_dan": rank[:5],
            "primary_d2": rank[:2],
            "d1_d5": {str(k): rank[:k] for k in range(1, 6)},
            "ticket": {"front": front, "back": back},
            "version": VERSION,
            "qualification": "EXPLORATORY_UNREGISTERED" if name.startswith("06-") else "RESEARCH_ONLY",
        }
        validate_candidate(game, candidate)
        result[name] = candidate
    return {
        "schema": "ssq-dlt-v46-research-1", "game": game, "issue": issue,
        "asof": asof, "target_draw_at": target_draw_at, "seed": seed,
        "source_snapshot_sha256": prior.digest(history),
        "model_source_sha256": prior.source_sha256(),
        "registry_sha256": prior.digest({"roles": ROLES, "models": MODELS, "version": VERSION}),
        "target_verified": False, "external_tsa": False, "admission": "SHADOW_ONLY",
        "formal_A": 0, "decision": "NO_EDGE", "models": result,
    }


def validate_candidate(game, candidate):
    upper, front_count, back_upper, back_count = prior.RULES[game]
    order = candidate.get("ordered_dan")
    if (type(order) is not list or len(order) != 5
            or len(set(order)) != 5 or any(type(n) is not int or not 1 <= n <= upper for n in order)):
        raise HarnessBlocked("INVALID_ORDERED_DAN")
    if candidate.get("primary_d2") != order[:2] or candidate.get("d1_d5") != {
        str(k): order[:k] for k in range(1, 6)
    }:
        raise HarnessBlocked("POST_HOC_D2_OR_PREFIX_REPLACEMENT")
    ticket = candidate.get("ticket")
    try:
        prior.validate_numbers(ticket["front"], front_count, upper)
        prior.validate_numbers(ticket["back"], back_count, back_upper)
    except (TypeError, KeyError, prior.ModelBlocked) as exc:
        raise HarnessBlocked("INVALID_LEGAL_SINGLE") from exc
    if not set(order[:2]).issubset(ticket["front"]):
        raise HarnessBlocked("D2_MISSING_FROM_TICKET")


def score_research(prediction, draw_front, draw_back):
    """Research-only diagnosis; draw/source admission must be established elsewhere."""
    if prediction.get("admission") != "SHADOW_ONLY" or prediction.get("formal_A") != 0:
        raise HarnessBlocked("FORMAL_ADMISSION_FORBIDDEN")
    game = prediction["game"]
    upper, front_count, back_upper, back_count = prior.RULES[game]
    try:
        prior.validate_numbers(draw_front, front_count, upper)
        prior.validate_numbers(draw_back, back_count, back_upper)
    except prior.ModelBlocked as exc:
        raise HarnessBlocked("INVALID_DRAW") from exc
    scored = {}
    for name in MODELS:
        candidate = prediction["models"][name]
        validate_candidate(game, candidate)
        hits = {str(k): len(set(candidate["ordered_dan"][:k]) & set(draw_front))
                for k in range(1, 6)}
        scored[name] = {"hits": hits, "d2_full": int(hits["2"] == 2),
                        "d1_d5_full": {str(k): int(hits[str(k)] == k)
                                       for k in range(1, 6)}}
    null_hit = scored["07-RANDOM-NULL"]["d2_full"]
    return {"schema": "ssq-dlt-v46-score-1", "game": game,
            "forecast_sha256": prior.digest(prediction),
            "outcome_source_status": "UNVERIFIED_CALLER_INPUT",
            "scored": scored,
            "same_period_vs_null": {
                name: scored[name]["d2_full"] - null_hit for name in MODELS if name != "07-RANDOM-NULL"
            },
            "p0_d2": 15 / 528 if game == "SSQ" else 10 / 595,
            "formal_A": 0, "decision": "NO_EDGE"}


class Ledger:
    """Local append-only idempotent ledger, not a privileged-safe TSA."""
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA recursive_triggers=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events "
            "(event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, sha256 TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self.db.executescript("""
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
        """)

    def append_batch(self, records):
        """One SQL transaction for all dual-game events; no partial SSQ commit.

        A ledger event is keyed by its caller-supplied stable event_id. Exact
        retries are idempotent; differing bytes or kinds must fail closed.
        """
        prepared = []
        seen = {}
        for event_id, kind, payload in records:
            encoded = prior.canonical_bytes(payload).decode("utf-8")
            checksum = prior.digest(payload)
            identity = (kind, checksum, encoded)
            if event_id in seen and seen[event_id] != identity:
                raise HarnessBlocked("CONFLICTING_REPLAY_ATTEMPT")
            seen[event_id] = identity
            prepared.append((event_id, kind, checksum, encoded))
        if not prepared:
            raise HarnessBlocked("EMPTY_ATOMIC_BATCH")
        with self.db:
            for event_id, kind, checksum, encoded in prepared:
                old = self.db.execute(
                    "SELECT kind,sha256,payload FROM events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if old is not None:
                    if old != (kind, checksum, encoded):
                        raise HarnessBlocked("CONFLICTING_REPLAY_ATTEMPT")
                    continue
                self.db.execute(
                    "INSERT INTO events VALUES (?,?,?,?)",
                    (event_id, kind, checksum, encoded),
                )
        return {event_id: checksum for event_id, _, checksum, _ in prepared}

    def append(self, event_id, kind, payload):
        return self.append_batch([(event_id, kind, payload)])[event_id]

    def verify(self):
        rows = self.db.execute("SELECT event_id,sha256,payload FROM events").fetchall()
        for _, checksum, value in rows:
            if prior.digest(json.loads(value)) != checksum:
                raise HarnessBlocked("LEDGER_PAYLOAD_HASH_MISMATCH")
        return len(rows)

    def close(self):
        self.db.close()
