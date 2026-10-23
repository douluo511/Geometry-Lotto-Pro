"""One reentrant SSQ+DLT SHADOW execution loop over the original V4.7 ledger.

Given already available snapshots and caller outcomes, join forecast -> immutable
freeze -> read-only scoring -> complete-roster D2/Random-NULL study. Does NOT
authenticate official feeds, control a host scheduler, approve an RFC3161 root,
or claim prospective lottery advantage. Never backfill a missing forecast.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import prospective_cycle as cycle
from .convergence import manifest
from .core import GateError

RUN_ID = re.compile(r"V47-[0-9a-f]{32}\Z")


def _not_symlink(path: Path) -> None:
    if path.is_symlink():
        raise GateError("SYMLINK_EVIDENCE_PATH_NOT_ACCEPTED")


def _write_once(path: Path, value: dict) -> None:
    """Exclusive, fsynced local SHADOW receipt; never silently rewrite evidence."""
    _not_symlink(path)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with path.open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise GateError("SCORE_RECEIPT_CONFLICT") from None


def _registered_runs(ledger: Path) -> list[str]:
    if not ledger.is_file():
        return []
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return sorted(row[0] for row in conn.execute("SELECT run_id FROM run_manifests"))
    finally:
        conn.close()


def advance_workspace(workspace, *, snapshots=None, observed_at=None) -> dict:
    """Idempotent entrypoint; caller-controlled snapshots/outcomes are UNVERIFIED.

    Same command may be called before and after a draw. A pre-draw snapshot
    creates a complete two-game frozen batch (if still before cutoff);
    outcome files in outcomes/<run_id>.json are scored only after draw time.
    Missing outcomes block the global study rather than quietly shrinking n.
    """
    root = Path(workspace).absolute()
    _not_symlink(root)
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "ledger.sqlite3"
    outcomes = root / "outcomes"
    receipts_dir = root / "receipts"
    for path in (ledger, outcomes, receipts_dir):
        _not_symlink(path)
    observed = datetime.now(timezone.utc) if observed_at is None else observed_at
    if (not isinstance(observed, datetime) or observed.tzinfo is None
            or observed.utcoffset() is None):
        raise GateError("CYCLE_REQUIRES_AWARE_CLOCK")

    existing = _registered_runs(ledger)
    if snapshots is not None:
        # The same immutable identity is safe to examine even after cutoff;
        # no attempt to create an absent run is allowed after its cutoff.
        desired = manifest(snapshots)["run_id"]
        if desired in existing:
            cycle.frozen_forecast_report(ledger, desired)
        else:
            cycle.forecast_on_demand(snapshots, ledger, now=observed)
        existing = _registered_runs(ledger)
    if not existing:
        raise GateError("NO_REGISTERED_RUN_OR_SNAPSHOT")
    if any(not isinstance(r, str) or not RUN_ID.fullmatch(r) for r in existing):
        raise GateError("UNEXPECTED_FROZEN_RUN_IDENTITY")

    outcome_files = {} if not outcomes.exists() else {
        file.stem: file for file in outcomes.iterdir()
        if file.suffix == ".json"
    }
    if outcomes.exists() and not outcomes.is_dir():
        raise GateError("OUTCOMES_DIRECTORY_REQUIRED")
    if set(outcome_files) - set(existing):
        raise GateError("UNKNOWN_OUTCOME_RUN")
    for file in outcome_files.values():
        _not_symlink(file)

    stored_files = {} if not receipts_dir.exists() else {
        file.stem: file for file in receipts_dir.iterdir()
        if file.suffix == ".json"
    }
    if receipts_dir.exists() and not receipts_dir.is_dir():
        raise GateError("RECEIPTS_DIRECTORY_REQUIRED")
    if set(stored_files) - set(existing):
        raise GateError("UNKNOWN_STORED_RECEIPT")
    for file in stored_files.values():
        _not_symlink(file)

    pending, scores = [], []
    for run_id in existing:
        # Replays the original pinned forecasts rather than recomputing picks.
        cycle.frozen_forecast_report(ledger, run_id)
        if run_id not in outcome_files:
            if run_id in stored_files:
                raise GateError("MISSING_ORIGINAL_OUTCOME_FOR_RECEIPT")
            pending.append(run_id)
            continue
        result_bundle = json.loads(outcome_files[run_id].read_text(encoding="utf-8"))
        scored = cycle.evaluate_after_draw(
            ledger, run_id, result_bundle, observed_at=observed)
        receipts_dir.mkdir(exist_ok=True)
        _write_once(receipts_dir / (run_id + ".json"), scored)
        scores.append(scored)

    output = {
        "schema": "V47-SHADOW-CLOSED-LOOP-1",
        "status": "WAITING_FOR_OUTCOME" if pending else "STUDY_SHADOW_READY",
        "run_ids": existing,
        "pending_run_ids": pending,
        "pending_run_count": len(pending),
        "completed_run_count": len(scores),
        "original_frozen_ledger": str(ledger),
        "outcome_authenticity": "CALLER_UNVERIFIED",
        "predraw_external_seal": "NOT_VERIFIED",
        "independent_scheduler": "NOT_VERIFIED",
        "formal_A": 0,
        "decision": "NO_EDGE",
    }
    if not pending:
        output["study"] = cycle.summarize_prospective_receipts(
            ledger, scores, observed_at=observed)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reentrant V4.7 dual-game SHADOW forecast-score-study loop")
    parser.add_argument("--workspace", required=True,
                        help="Existing SHADOW workspace or new empty folder")
    parser.add_argument("--snapshot-bundle",
                        help="Both games; caller supplied, not official authentication")
    args = parser.parse_args(argv)
    try:
        snapshots = (json.loads(Path(args.snapshot_bundle).read_text(encoding="utf-8"))
                     if args.snapshot_bundle else None)
        value = advance_workspace(args.workspace, snapshots=snapshots)
    except (GateError, ValueError, TypeError, KeyError, sqlite3.Error, OSError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
