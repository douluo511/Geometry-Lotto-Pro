"""V4.7 local SHADOW bot entrypoint: frozen forecast and replayable feedback.

For an external scheduler on a persistent host; this module does not install
one, validate official sources or provide a trusted timestamp. Never run a
GitHub ephemeral CI worker as a durable evidence ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import cumulative_shadow as cumulative
from . import prospective_cycle as cycle
from .core import GateError, canon, digest, dt

RUN_ID = re.compile(r"V47-[0-9a-f]{32}\Z")
SCHEMA = "V47-SHADOW-BOT-RECEIPT-1"


def _run_id(value):
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise GateError("INVALID_BOT_RUN_ID")
    return value


def _directory(path, *, make=False):
    p = Path(path)
    if p.is_symlink():
        raise GateError("BOT_SYMLINK_DIRECTORY_FORBIDDEN")
    if make:
        p.mkdir(exist_ok=True)
    if not p.is_dir() or p.is_symlink():
        raise GateError("BOT_PERSISTENT_DIRECTORY_REQUIRED")
    return p


def _folder(root, name, *, make=True):
    return _directory(_directory(root) / name, make=make)


def _sealed_record(phase, run_id, payload):
    data = {
        "schema": SCHEMA, "phase": phase, "run_id": _run_id(run_id),
        "payload": payload, "trust": "LOCAL_SHADOW_ONLY",
        "formal_A": 0, "decision": "NO_EDGE",
    }
    data["local_sha256_untrusted"] = digest(data)
    return data


def _read_record(path, phase=None):
    if path.is_symlink():
        raise GateError("BOT_SYMLINK_RECEIPT_FORBIDDEN")
    try:
        raw = path.read_bytes()
        record = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise GateError("BOT_RECEIPT_UNAVAILABLE_OR_MALFORMED") from exc
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise GateError("BOT_RECEIPT_SCHEMA_MISMATCH")
    if (record.get("trust") != "LOCAL_SHADOW_ONLY" or record.get("formal_A") != 0
            or type(record.get("formal_A")) is not int
            or record.get("decision") != "NO_EDGE"
            or record.get("phase") not in ("forecast", "score")
            or (phase is not None and record["phase"] != phase)
            or set(record) != {"schema", "phase", "run_id", "payload", "trust",
                               "formal_A", "decision", "local_sha256_untrusted"}):
        raise GateError("BOT_RECEIPT_CANNOT_CLAIM_AUTHORITY")
    checksum = record["local_sha256_untrusted"]
    if digest({k: v for k, v in record.items() if k != "local_sha256_untrusted"}) != checksum:
        raise GateError("BOT_RECEIPT_INTEGRITY_FAIL")
    _run_id(record["run_id"])
    if path.name != record["run_id"] + ".json":
        raise GateError("BOT_RECEIPT_PATH_IDENTITY_MISMATCH")
    return record


def _put_once(folder, receipt):
    dest = folder / (receipt["run_id"] + ".json")
    if dest.exists() or dest.is_symlink():
        existing = _read_record(dest, receipt["phase"])
        if existing != receipt:
            raise GateError("BOT_CONFLICTING_EXACT_RUN_RETRY")
        return existing
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(dest, flags, 0o600)
    except FileExistsError:
        existing = _read_record(dest, receipt["phase"])
        if existing != receipt:
            raise GateError("BOT_CONCURRENT_CONFLICT")
        return existing
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canon(receipt).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Fail closed. Never count a partial write as a valid receipt.
        raise
    return receipt


def forecast_tick(snapshot_bundle, database, evidence_dir, *, now=None):
    """External host triggers pre-cutoff. Writes SHADOW-only receipt once."""
    _directory(evidence_dir)
    _directory(Path(database).parent)
    result = cycle.forecast_on_demand(snapshot_bundle, database, now=now)
    run_id = _run_id(result["run_id"])
    if result.get("formal_A") != 0 or result.get("decision") != "NO_EDGE":
        raise GateError("BOT_FORECAST_FORMAL_PROMOTION_FORBIDDEN")
    receipt = _sealed_record("forecast", run_id, {
        "database": str(Path(database).resolve()),
        "frozen_forecast": result,
    })
    return _put_once(_folder(evidence_dir, "forecasts"), receipt)


def score_tick(evidence_dir, run_id, claimed_results, *, now=None):
    """Never scores before announced target draw, even for forged future results.

    Uses only the saved forecast ledger; claimed draw time is NOT authenticated.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise GateError("BOT_REQUIRES_AWARE_CLOCK")
    run_id = _run_id(run_id)
    base = _directory(evidence_dir)
    prior = _read_record(_folder(base, "forecasts", make=False) / (run_id + ".json"), "forecast")
    database = prior["payload"]["database"]
    frozen = cycle.frozen_forecast_report(database, run_id)
    expected = prior["payload"]["frozen_forecast"]
    if (frozen.get("games") != expected.get("games")
            or frozen.get("run_id") != expected.get("run_id")):
        raise GateError("BOT_FROZEN_PREDICTION_DRIFT")
    if not isinstance(claimed_results, dict) or set(claimed_results) != {"SSQ", "DLT"}:
        raise GateError("BOT_BOTH_RESULTS_REQUIRED")
    from .core import load_registered_snapshot
    import sqlite3
    conn = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        for game in ("SSQ", "DLT"):
            snapshot = load_registered_snapshot(conn, run_id, game)
            result = claimed_results[game]
            if not isinstance(result, dict) or "drawn_at" not in result:
                raise GateError("BOT_CLAIMED_DRAW_TIME_REQUIRED")
            if now < dt(snapshot["target_draw_at"]):
                raise GateError("BOT_REAL_CLOCK_BEFORE_TARGET_DRAW")
            if dt(result["drawn_at"]) > now:
                raise GateError("BOT_CLAIMED_DRAW_IN_FUTURE")
    finally:
        conn.close()
    input_row = {"database": database, "run_id": run_id, "results": claimed_results}
    diagnostic = cumulative.cumulative_shadow_review([input_row])
    receipt = _sealed_record("score", run_id, {
        "input": input_row,
        "single_run_diagnostic": diagnostic,
        "outcome_authenticity": "CALLER_UNVERIFIED",
    })
    return _put_once(_folder(base, "scores"), receipt)


def cumulative_tick(evidence_dir):
    """Recompute every cumulative hit from frozen ledgers, not stored score bits."""
    base = _directory(evidence_dir)
    folder = _folder(base, "scores", make=False)
    rows = []
    for p in sorted(folder.iterdir()):
        if p.is_symlink():
            raise GateError("BOT_SYMLINK_RECEIPT_FORBIDDEN")
        if p.suffix != ".json" or not p.is_file():
            raise GateError("BOT_UNKNOWN_SCORE_ARTIFACT")
        receipt = _read_record(p, "score")
        row = receipt["payload"]["input"]
        if row["run_id"] != receipt["run_id"]:
            raise GateError("BOT_SCORE_INPUT_RUN_ID_MISMATCH")
        rows.append(row)
    return cumulative.cumulative_shadow_review(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4.7 SHADOW prediction/replay bot (external scheduler required)")
    parser.add_argument("phase", choices=("forecast", "score", "cumulative"))
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--database")
    parser.add_argument("--snapshot-bundle")
    parser.add_argument("--result-bundle")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        if args.phase == "forecast":
            if not args.database or not args.snapshot_bundle:
                raise GateError("BOT_FORECAST_INPUT_REQUIRED")
            snapshots = json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
            result = forecast_tick(snapshots, args.database, args.evidence_dir)
        elif args.phase == "score":
            if not args.run_id or not args.result_bundle:
                raise GateError("BOT_SCORE_INPUT_REQUIRED")
            results = json.loads(Path(args.result_bundle).read_text(encoding="utf-8"))
            result = score_tick(args.evidence_dir, args.run_id, results)
        else:
            result = cumulative_tick(args.evidence_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (GateError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
