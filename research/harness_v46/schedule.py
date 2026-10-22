"""V4.7 Windows/CLI compensation handler. SHADOW ONLY; no trusted scheduling proof."""
from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime, timezone, time, timedelta
from pathlib import Path

from .core import MODELS, GateError, dt, forecast, freeze_shadow, init_ledger, register_snapshot
from .convergence import (STAGES, append_stage, append_shadow_trace, check_complete_batch,
                           init_workflow, manifest, register_manifest, tsa_request)

JST = timezone(timedelta(hours=9), name="JST")  # Japan does not use DST
DAYS = {0, 2, 5}  # Mon/Wed/Sat: target delivery run, not actual lottery draw date

GUARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_target_guard(
    lottery TEXT NOT NULL, target_issue TEXT NOT NULL,
    run_id TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
    PRIMARY KEY(lottery,target_issue)
);
CREATE TRIGGER IF NOT EXISTS scheduled_guard_no_update
BEFORE UPDATE ON scheduled_target_guard
BEGIN SELECT RAISE(ABORT, 'immutable target scheduling guard'); END;
CREATE TRIGGER IF NOT EXISTS scheduled_guard_no_delete
BEFORE DELETE ON scheduled_target_guard
BEGIN SELECT RAISE(ABORT, 'immutable target scheduling guard'); END;
"""

def due_in_jst(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise GateError("SCHEDULER_REQUIRES_AWARE_CLOCK")
    local = now.astimezone(JST)
    return local.weekday() in DAYS and local.time().replace(tzinfo=None) >= time(16, 0)


def scheduled_once(snapshots, database, now=None):
    """Persist both games together; all-or-nothing and fail closed on bad time."""
    now = now or datetime.now(timezone.utc)
    if not due_in_jst(now):
        return {"status": "WAIT_NOT_DELIVERY_WINDOW", "formal_A": 0, "timestamp_trust": "LOCAL_ONLY"}
    identity = manifest(snapshots)
    run_id = identity["run_id"]
    for game, s in snapshots.items():
        if not dt(s["as_of"]) <= now < dt(s["sales_cutoff"]):
            raise GateError("ASOF_OR_CUTOFF_FAIL_NO_RETROACTIVE_FORECAST")
    path = Path(database)
    if not path.parent.exists():
        raise GateError("SCHEDULER_DATABASE_PARENT_MISSING")
    conn = sqlite3.connect(str(path), timeout=15)
    try:
        conn.execute("PRAGMA synchronous=FULL")
        init_ledger(conn)
        init_workflow(conn)
        conn.executescript(GUARD_SCHEMA)
        receipts = {}
        with conn:
            manifest_sha = register_manifest(conn, identity)
            # Persist both exact snapshot preimages before any model can freeze.
            for game in ("SSQ", "DLT"):
                register_snapshot(conn, run_id, snapshots[game])
            for game in ("SSQ", "DLT"):
                s = snapshots[game]
                target = str(s["target_issue"])
                existing = conn.execute(
                    "SELECT run_id,snapshot_sha256 FROM scheduled_target_guard "
                    "WHERE lottery=? AND target_issue=?", (game, target)).fetchone()
                expected = (run_id, identity["games"][game]["snapshot_sha256"])
                if existing is None:
                    conn.execute("INSERT INTO scheduled_target_guard VALUES(?,?,?,?)",
                                 (game, target, *expected))
                elif existing != expected:
                    raise GateError("TARGET_ALREADY_FROZEN_WITH_DIFFERENT_RUN")
            for game in ("SSQ", "DLT"):
                s = snapshots[game]
                for model in MODELS:
                    prediction = forecast(s, model)
                    freeze_shadow(conn, run_id, s, prediction, now.isoformat())
                batch = check_complete_batch(conn, run_id, game)
                # Official target/source and authorization are not independently verified.
                # Keep a blocked SYNC gate receipt; research execution is a separate trace.
                append_stage(conn, run_id, game, "SYNC", {
                    "gate_status": "BLOCKED", "evidence_class": "SHADOW",
                    "formal_A": 0, "reason": "OFFICIAL_TARGET_AND_SOURCE_NOT_VERIFIED",
                })
                for stage in STAGES[:6]:
                    proof = {"status": "SHADOW_UNVERIFIED", "evidence_class": "SHADOW",
                             "formal_A": 0}
                    if stage == "FREEZE":
                        proof["batch_sha256"] = batch
                    append_shadow_trace(conn, run_id, game, stage, proof)
                tsa_request(conn, run_id, game)
                receipts[game] = {"target_issue": str(s["target_issue"]),
                                  "batch_sha256": batch, "model_count": len(MODELS)}
        return {"status": "SHADOW_ONLY", "run_id": run_id,
                "manifest_sha256": manifest_sha, "games": receipts,
                "official_source_authenticity": "NOT_VERIFIED",
                "authorization": "NOT_FORMAL", "external_tsa": "NOT_VERIFIED",
                "gate_status": "BLOCKED", "evidence_class": "SHADOW",
                "shadow_trace_status": "UNVERIFIED_EXECUTION_ONLY",
                "timestamp_trust": "LOCAL_ONLY", "formal_A": 0, "decision": "NO_EDGE"}
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4.7 JST delivery/recovery gate, SHADOW ONLY")
    parser.add_argument("--snapshot-bundle", required=True,
                        help="JSON map with exactly SSQ and DLT vetted as-of snapshot objects")
    parser.add_argument("--database", required=True)
    args = parser.parse_args(argv)
    snapshots = json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
    result = scheduled_once(snapshots, args.database)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
