"""Explicitly configured V4.7 SHADOW research bot: one idempotent tick.

Not an autonomous official-data collector, a background process, an independently
trusted publication clock, or a claim of genuine preregistered prediction.
Each tick uses the original dual-game forecast ledger and read-only scorer.
A host scheduler may call this entrypoint repeatedly; the scheduler itself
is not installed or enabled by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .convergence import manifest
from .core import RULES, GateError, canon, dt
from .prospective_cycle import (
    evaluate_after_draw, forecast_on_demand, frozen_forecast_report,
    summarize_from_frozen_runs,
)

BOT_SCHEMA = "V47-SHADOW-BOT-CONFIG-1"


def _read_object(path):
    if not path.is_file():
        raise GateError("BOT_REQUIRED_INPUT_FILE_MISSING:" + path.name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise GateError("BOT_INPUT_JSON_INVALID:" + path.name) from exc
    if not isinstance(value, dict):
        raise GateError("BOT_INPUT_REQUIRES_OBJECT:" + path.name)
    return value


def _config(path):
    location = Path(path).resolve()
    item = _read_object(location)
    if set(item) != {"schema", "snapshot_bundle", "database", "result_bundle", "receipts_dir"}:
        raise GateError("BOT_CONFIG_FIELDS_INVALID")
    if item["schema"] != BOT_SCHEMA:
        raise GateError("BOT_CONFIG_SCHEMA_INVALID")
    for name in ("snapshot_bundle", "database", "receipts_dir"):
        if not isinstance(item[name], str) or not item[name].strip():
            raise GateError("BOT_CONFIG_PATH_MISSING:" + name)
    if item["result_bundle"] is not None and (
        not isinstance(item["result_bundle"], str) or not item["result_bundle"].strip()
    ):
        raise GateError("BOT_RESULT_PATH_MUST_BE_STRING_OR_NULL")

    def resolve(value):
        p = Path(value)
        return p.resolve() if p.is_absolute() else (location.parent / p).resolve()

    return {
        "snapshot_bundle": resolve(item["snapshot_bundle"]),
        "database": resolve(item["database"]),
        "result_bundle": None if item["result_bundle"] is None else resolve(item["result_bundle"]),
        "receipts_dir": resolve(item["receipts_dir"]),
    }


def _persist_once(directory, label, report):
    """Atomic create-only local receipt; conflicting rerun never rewrites it.

    These reports are useful durable local artifacts, NOT trusted TSA seals:
    privileged actors can edit local files, clocks and result inputs.
    """
    if not directory.is_dir():
        raise GateError("BOT_RECEIPTS_DIRECTORY_MISSING")
    if directory.is_symlink():
        raise GateError("BOT_RECEIPTS_DIRECTORY_SYMLINK_FORBIDDEN")
    payload = (canon(report) + "\n").encode("utf-8")
    name = hashlib.sha256(report["run_id"].encode("utf-8")).hexdigest()[:20]
    target = directory / (name + "-" + label + ".json")
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if target.is_symlink():
            raise GateError("BOT_RECEIPT_SYMLINK_FORBIDDEN")
        if target.read_bytes() != payload:
            raise GateError("BOT_RECEIPT_ALREADY_EXISTS_DIFFERENT_CONTENT")
    else:
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # A failed partial write may need forensic intervention; never
            # silently replace it on retry.
            raise
    return {"path": str(target), "local_sha256": hashlib.sha256(payload).hexdigest(),
            "trust": "LOCAL_WRITABLE_NOT_EXTERNAL_SEAL"}


def _has_run(database, run_id):
    if not database.is_file():
        return False
    try:
        conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            return conn.execute(
                "SELECT 1 FROM run_manifests WHERE run_id=?", (run_id,)
            ).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise GateError("BOT_EXISTING_LEDGER_CANNOT_BE_INSPECTED") from exc


def tick(config_path, *, observed_at=None):
    """Execute an immediate retry-safe, fail-closed bot cycle.

    Prospective data supply remains a separate reviewed input process. This
    function cannot validate that snapshot provenance or caller outcomes are
    truly official.
    """
    now = datetime.now(timezone.utc) if observed_at is None else observed_at
    if (not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None):
        raise GateError("BOT_REQUIRES_AWARE_OBSERVATION_TIME")
    config = _config(config_path)
    # Failure to preserve an observation is a no-go for a new forecast.
    # Do not make a prediction when the expected evidence directory is missing.
    if not config["receipts_dir"].is_dir():
        raise GateError("BOT_RECEIPTS_DIRECTORY_MISSING")
    if config["receipts_dir"].is_symlink():
        raise GateError("BOT_RECEIPTS_DIRECTORY_SYMLINK_FORBIDDEN")
    snapshots = _read_object(config["snapshot_bundle"])
    if set(snapshots) != set(RULES):
        raise GateError("BOT_REQUIRES_BOTH_LOTTERIES")
    identity = manifest(snapshots)
    run_id = identity["run_id"]
    as_of = max(dt(v["as_of"]) for v in snapshots.values())
    cutoff = min(dt(v["sales_cutoff"]) for v in snapshots.values())
    target_draw = max(dt(v["target_draw_at"]) for v in snapshots.values())
    common = {
        "schema": "V47-SHADOW-BOT-TICK-1", "run_id": run_id,
        "formal_A": 0, "decision": "NO_EDGE",
        "source_authenticity": "NOT_VERIFIED",
        "predraw_time_authenticity": "LOCAL_ONLY",
        "outcome_authenticity": "CALLER_UNVERIFIED",
    }
    if now < as_of:
        return {**common, "status": "WAIT_ASOF"}
    if not _has_run(config["database"], run_id):
        if now >= cutoff:
            # Never backfill an old target as though it were pre-draw.
            return {**common, "status": "BLOCKED_MISSED_PREDRAW_FREEZE"}
        if not config["database"].parent.is_dir():
            raise GateError("BOT_LEDGER_PARENT_DIRECTORY_MISSING")
        forecast = forecast_on_demand(snapshots, config["database"], now=now)
    else:
        # Read only. The DB could predate the supplied snapshot: the run ID,
        # six-model batch and source hashes must all still replay correctly.
        forecast = frozen_forecast_report(config["database"], run_id)
    frozen_receipt = _persist_once(config["receipts_dir"], "forecast", {
        k: v for k, v in forecast.items() if k != "freeze_receipt"
    })
    # Caller may provision results after the event, without editing the bot's
    # original forecast or changing its immutable issue manifest.
    if now < target_draw:
        return {**common, "status": "SHADOW_FROZEN_WAIT_DRAW",
                "forecast_receipt": frozen_receipt,
                "target_issues": {g: forecast["games"][g]["target_issue"] for g in RULES}}
    if (config["result_bundle"] is None
            or not config["result_bundle"].is_file()):
        return {**common, "status": "SHADOW_FROZEN_WAIT_RESULT",
                "forecast_receipt": frozen_receipt}
    outcomes = _read_object(config["result_bundle"])
    # Explicitly prohibit trusting unauthenticated caller outcomes as G01.
    scored = evaluate_after_draw(
        config["database"], run_id, outcomes, observed_at=now,
    )
    # Save the caller's unverified raw outcome alongside the computed receipt:
    # future cumulative ticks must recompute from original frozen model rows,
    # not trust anyone's stored win bits or posthoc hit-rate claims.
    scored_receipt = {**scored, "caller_supplied_result_bundle": outcomes}
    score_receipt = _persist_once(config["receipts_dir"], "score", scored_receipt)
    records = []
    for saved_path in sorted(config["receipts_dir"].glob("*-score.json")):
        if saved_path.is_symlink():
            raise GateError("BOT_RECEIPT_SYMLINK_FORBIDDEN")
        saved = _read_object(saved_path)
        if (saved.get("schema") != "V47-PROSPECTIVE-SHADOW-SCORE-1"
                or saved.get("formal_A") != 0 or saved.get("decision") != "NO_EDGE"
                or saved.get("outcome_source") != "CALLER_UNVERIFIED"
                or not isinstance(saved.get("run_id"), str)
                or not isinstance(saved.get("caller_supplied_result_bundle"), dict)):
            raise GateError("BOT_UNTRUSTED_CUMULATIVE_SCORE_RECEIPT")
        original = evaluate_after_draw(
            config["database"], saved["run_id"],
            saved["caller_supplied_result_bundle"], observed_at=now,
        )
        if original != {k: v for k, v in saved.items()
                        if k != "caller_supplied_result_bundle"}:
            raise GateError("BOT_PRIOR_SCORE_RECEIPT_INCONSISTENT")
        records.append({
            "database": str(config["database"]), "run_id": saved["run_id"],
            "results": saved["caller_supplied_result_bundle"],
        })
    cumulative = summarize_from_frozen_runs(records, observed_at=now)
    cumulative_receipt = _persist_once(
        config["receipts_dir"], "cumulative", {**cumulative, "run_id": run_id}
    )
    return {**common, "status": "SHADOW_SCORE_RECORDED",
            "forecast_receipt": frozen_receipt, "score_receipt": score_receipt,
            "cumulative_receipt": cumulative_receipt,
            "cumulative_run_count": cumulative["run_count"],
            "comparison": "EACH_D1_D5_AND_PAIRED_RANDOM_NULL",
            "research_valid": "NOT_VERIFIED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-shot V4.7 safe SHADOW bot tick")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        report = tick(args.config)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2))
        return 0 if not report["status"].startswith("BLOCKED") else 2
    except (GateError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
