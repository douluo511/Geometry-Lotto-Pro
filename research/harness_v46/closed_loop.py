"""One reentrant SSQ+DLT SHADOW execution loop over the original V4.7 ledger.

Given already available snapshots and caller outcomes, join forecast -> immutable
freeze -> read-only scoring -> complete-roster D2/Random-NULL study. Does NOT
authenticate official feeds, control a host scheduler, approve an RFC3161 root,
or claim prospective lottery advantage. Never backfill a missing forecast.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import prospective_cycle as cycle
from . import d2_challenger_lab as d2lab
from .convergence import manifest
from .core import GateError

RUN_ID = re.compile(r"V47-[0-9a-f]{32}\Z")


MAX_JSON_BYTES = 32_000_000


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise GateError("CLOSED_LOOP_JSON_DUPLICATE_KEY:" + name)
        result[name] = value
    return result


def _reject_nonfinite(value):
    raise GateError("CLOSED_LOOP_JSON_NONFINITE:" + value)


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise GateError("CLOSED_LOOP_JSON_NONFINITE:" + value)
    return parsed


def _read_json(path):
    _not_symlink(path)
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise GateError("CLOSED_LOOP_JSON_INPUT_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_nonfinite, parse_float=_finite_float)
    except UnicodeError as exc:
        raise GateError("CLOSED_LOOP_JSON_INVALID_UTF8") from exc


def _not_symlink(path: Path) -> None:
    raw = Path(path)
    if ".." in raw.parts:
        raise GateError("CLOSED_LOOP_PARENT_TRAVERSAL_FORBIDDEN")
    p = raw.absolute()
    if any(item.is_symlink() for item in (p, *p.parents)):
        raise GateError("SYMLINK_EVIDENCE_PATH_NOT_ACCEPTED")


def _write_once(path: Path, value: dict) -> None:
    """Crash-safe create-only local SHADOW receipt, not independently WORM.

    Stage and fsync complete contents BEFORE making the receipt visible.
    Link the staged file atomically: unlike os.replace(), os.link() cannot
    overwrite a different receipt, including under concurrent Bot ticks.
    A surviving .pending file after process death is NOT a score receipt.
    """
    _not_symlink(path)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")
    stage = None
    try:
        fd, name = tempfile.mkstemp(
            dir=path.parent, prefix="." + path.name + ".", suffix=".pending")
        stage = Path(name)
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            # Same-directory hard link creates destination only if absent.
            # No OS-specific replace/rename-over-existing escape hatch.
            os.link(stage, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise GateError("SCORE_RECEIPT_CONFLICT") from None
            return
        # On POSIX make the new directory entry durable where supported.
        # Windows receipt/cold-boot durability still requires host validation.
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def _registered_runs(ledger: Path) -> list[str]:
    if not ledger.is_file():
        return []
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return sorted(row[0] for row in conn.execute("SELECT run_id FROM run_manifests"))
    finally:
        conn.close()


def advance_workspace(workspace, *, snapshots=None, research_history=None, observed_at=None) -> dict:
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

    # Validate the optional exploratory input BEFORE any frozen ledger write.
    # A malformed challenger diagnostic must never leave an orphan predraw run.
    diagnostic = (d2lab.audit_walk_forward(research_history)
                  if research_history is not None else None)
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
        result_bundle = _read_json(outcome_files[run_id])
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
    if diagnostic is not None:
        # This retrospective, already-known history is never prospective
        # evidence and cannot change the six frozen model arms.
        output["research_diagnostic"] = diagnostic
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reentrant V4.7 dual-game SHADOW forecast-score-study loop")
    parser.add_argument("--workspace", required=True,
                        help="Existing SHADOW workspace or new empty folder")
    parser.add_argument("--snapshot-bundle",
                        help="Both games; caller supplied, not official authentication")
    parser.add_argument("--research-history-bundle",
                        help="Optional unverified historical data for exploratory D2 lab")
    args = parser.parse_args(argv)
    try:
        snapshots = (_read_json(Path(args.snapshot_bundle))
                     if args.snapshot_bundle else None)
        research = (_read_json(Path(args.research_history_bundle))
                    if args.research_history_bundle else None)
        value = advance_workspace(args.workspace, snapshots=snapshots,
                                  research_history=research)
    except (GateError, ValueError, TypeError, KeyError, sqlite3.Error, OSError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
