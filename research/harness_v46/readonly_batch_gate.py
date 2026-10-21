"""Independent, local-only V4.6 dual-lottery SHADOW completeness gate.

Reads existing SQLite evidence, but never calls or imports a prediction model.
PASS proves internal consistency and 12/12 presence only, NOT official data,
external timestamp, formal A eligibility, or predictive advantage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

MODELS = frozenset(("hot60", "ewma", "shrinkmix", "pairwise_d2", "challenger", "random_null"))
RULES = {
    "SSQ": {"pool": 33, "front": 6, "back_pool": 16, "back": 1},
    "DLT": {"pool": 35, "front": 5, "back_pool": 12, "back": 2},
}


class EvidenceGateError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise EvidenceGateError(reason)


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise EvidenceGateError("invalid timestamp") from exc
    _require(result.tzinfo is not None, "timezone missing")
    return result


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _balls(values, size, pool):
    return (isinstance(values, list) and len(values) == size
            and all(type(n) is int and 1 <= n <= pool for n in values)
            and values == sorted(set(values)))


def inspect_run(database, run_id):
    """Check a complete 2-lottery x 6-model batch; never mutates the ledger."""
    path = Path(database).resolve()
    _require(path.is_file(), "missing database; never create on read")
    _require(bool(run_id), "missing run_id")
    for suffix in ("-wal", "-shm", "-journal"):
        _require(not Path(str(path) + suffix).exists(), "sidecar present: require closed checkpointed ledger")
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        contexts = db.execute(
            "SELECT lottery,target_issue,snapshot_sha256,as_of,sales_cutoff "
            "FROM run_context WHERE run_id=?", (run_id,)
        ).fetchall()
        _require(len(contexts) == 2 and {row[0] for row in contexts} == set(RULES),
                 "dual-lottery context incomplete or invalid")
        context = {}
        for game, issue, sha, as_of, cutoff in contexts:
            _require(str(issue).isdigit(), "invalid target issue")
            _require(_sha(sha), "invalid snapshot SHA")
            _require(_time(as_of) < _time(cutoff), "invalid context time order")
            context[game] = {"target_issue": str(issue), "snapshot_sha256": sha,
                             "as_of": as_of, "sales_cutoff": cutoff}

        rows = db.execute(
            "SELECT lottery,model,frozen_at,snapshot_sha256,prediction_sha256,"
            "payload,evidence_class FROM predictions WHERE run_id=?", (run_id,)
        ).fetchall()
        _require(len(rows) == len(RULES) * len(MODELS), "incomplete 12/12 prediction batch")
        seen, evidence = set(), {}
        for game, model, frozen_at, snapshot_sha, prediction_sha, raw, classification in rows:
            _require(game in RULES and model in MODELS, "unexpected agent identity")
            _require((game, model) not in seen, "duplicate model identity")
            seen.add((game, model))
            ctx, rules = context[game], RULES[game]
            _require(_time(ctx["as_of"]) <= _time(frozen_at) < _time(ctx["sales_cutoff"]),
                     "prediction frozen outside as-of / sales cutoff window")
            _require(snapshot_sha == ctx["snapshot_sha256"], "mixed snapshot SHA")
            _require(classification == "SHADOW", "evidence class must remain SHADOW")
            _require(_sha(prediction_sha), "malformed prediction SHA")
            _require(hashlib.sha256(raw.encode("utf-8")).hexdigest() == prediction_sha,
                     "stored payload SHA mismatch")
            try:
                p = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise EvidenceGateError("invalid prediction JSON") from exc
            _require(raw == _canonical(p), "noncanonical prediction JSON")
            _require(p.get("model") == model and p.get("lottery") == game
                     and p.get("target_issue") == ctx["target_issue"]
                     and p.get("snapshot_sha256") == ctx["snapshot_sha256"],
                     "prediction identity / context mismatch")
            _require(p.get("evidence_class") == "SHADOW" and p.get("formal_a_eligible") is False,
                     "research-only evidence cannot claim A")
            _require(_sha(p.get("parameters_sha256")), "missing parameters SHA")
            picks = p.get("candidates_1_to_5")
            _require(isinstance(picks, list) and len(picks) == 5
                     and all(type(n) is int and 1 <= n <= rules["pool"] for n in picks)
                     and len(set(picks)) == 5, "invalid 1-5 ordered candidates")
            _require(p.get("primary_d2") == picks[:2], "unique primary D2 changed")
            ticket = p.get("ticket")
            _require(isinstance(ticket, dict), "missing ticket")
            _require(_balls(ticket.get("front"), rules["front"], rules["pool"])
                     and _balls(ticket.get("back"), rules["back"], rules["back_pool"]),
                     "illegal full ticket")
            _require(set(picks).issubset(set(ticket["front"])),
                     "candidates not included in ticket")
            evidence[(game, model)] = (prediction_sha, picks[:2])

        _require(seen == {(g, m) for g in RULES for m in MODELS},
                 "missing or extra model identity")
        events = db.execute(
            "SELECT event_type,payload FROM audit_events WHERE run_id=?", (run_id,)
        ).fetchall()
        _require(len(events) == len(rows), "missing/extra freeze audit event")
        event_keys = set()
        for kind, raw in events:
            _require(kind == "LOCAL_SHADOW_FREEZE", "unknown audit event")
            try:
                event = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise EvidenceGateError("invalid audit event JSON") from exc
            key = (event.get("lottery"), event.get("model"))
            _require(key in evidence and key not in event_keys, "unknown/duplicate freeze event")
            event_keys.add(key)
            _require(event.get("prediction_sha256") == evidence[key][0],
                     "freeze event SHA mismatch")
            _require(event.get("external_tsa") == "NOT_RUN",
                     "local freeze cannot claim external trusted time")
        return {
            "run_id": run_id,
            "status": "LOCAL_INTEGRITY_PASS_SHADOW_ONLY",
            "complete_model_rows": len(seen),
            "games": {g: {"target_issue": context[g]["target_issue"],
                           "snapshot_sha256": context[g]["snapshot_sha256"],
                           "model_d2": {m: evidence[(g, m)][1] for m in sorted(MODELS)}}
                      for g in sorted(RULES)},
            "formal_a_eligible": False,
            "predictive_edge_proven": False,
            "official_data_verified": False,
            "external_tsa_verified": False,
            "caveat": "Local integrity cannot establish real as-of provenance or tamper-proof time.",
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        report = inspect_run(args.database, args.run_id)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (EvidenceGateError, sqlite3.Error, OSError, ValueError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
