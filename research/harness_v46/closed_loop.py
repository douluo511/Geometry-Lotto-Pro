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
from . import core

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



# A separate issue identity per lottery shares this V4.7 workspace and CLI.
# The original 12-card dual-run legacy tables remain untouched, read-only.
GAME_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_runs (
 lottery TEXT NOT NULL, issue TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE,
 snapshot_sha256 TEXT NOT NULL, snapshot_payload TEXT NOT NULL,
 frozen_at_local_untrusted TEXT NOT NULL,
 PRIMARY KEY(lottery, issue)
);
CREATE TABLE IF NOT EXISTS game_predictions (
 run_id TEXT NOT NULL, model TEXT NOT NULL, payload TEXT NOT NULL,
 prediction_sha256 TEXT NOT NULL, PRIMARY KEY(run_id, model)
);
CREATE TRIGGER IF NOT EXISTS protect_game_runs_update BEFORE UPDATE ON game_runs
 BEGIN SELECT RAISE(ABORT,'game run immutable'); END;
CREATE TRIGGER IF NOT EXISTS protect_game_runs_delete BEFORE DELETE ON game_runs
 BEGIN SELECT RAISE(ABORT,'game run immutable'); END;
CREATE TRIGGER IF NOT EXISTS protect_game_predictions_update BEFORE UPDATE ON game_predictions
 BEGIN SELECT RAISE(ABORT,'game prediction immutable'); END;
CREATE TRIGGER IF NOT EXISTS protect_game_predictions_delete BEFORE DELETE ON game_predictions
 BEGIN SELECT RAISE(ABORT,'game prediction immutable'); END;
"""


def _game_issue(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise GateError("GAME_ISSUE_ASCII_DECIMAL_REQUIRED")
    issue = str(int(value))
    if issue != value:
        raise GateError("GAME_ISSUE_CANONICAL_ID_REQUIRED")
    return issue


def _read_frozen_game(conn, game, row):
    """Reconstruct ALL six frozen outputs, and compare with stored model code."""
    issue, run_id, snapshot_sha, payload, frozen_at = row
    if core.digest(json.loads(payload)) != snapshot_sha:
        raise GateError("GAME_SNAPSHOT_SHA_MISMATCH")
    snapshot = json.loads(payload)
    if (core.canon(snapshot) != payload or
            core.validate_study_snapshot(snapshot) != snapshot_sha or
            snapshot["lottery"] != game or _game_issue(snapshot["target_issue"]) != issue):
        raise GateError("GAME_SNAPSHOT_REPLAY_MISMATCH")
    if not core.dt(snapshot["as_of"]) <= core.dt(frozen_at) < core.dt(snapshot["sales_cutoff"]):
        raise GateError("GAME_FROZEN_LOCAL_TIME_INVALID")
    expected_run = "V47G-" + core.digest({
        "contract": "V47-INDEPENDENT-GAME-SHADOW-1",
        "lottery": game, "issue": issue,
        "snapshot_sha256": snapshot_sha, "models": list(core.MODELS),
        "model_source_sha256": core.model_source_sha256(),
    })[:32]
    if run_id != expected_run:
        raise GateError("GAME_RUN_IDENTITY_MISMATCH")
    records = conn.execute(
        "SELECT model,payload,prediction_sha256 FROM game_predictions WHERE run_id=?",
        (run_id,),
    ).fetchall()
    if len(records) != len(core.MODELS) or {r[0] for r in records} != set(core.MODELS):
        raise GateError("GAME_INCOMPLETE_SIX_ARM_FREEZE")
    cards = []
    for model, raw, sha in records:
        prediction = json.loads(raw)
        if (core.digest(prediction) != sha or core.canon(prediction) != raw
                or prediction != core.forecast(snapshot, model)):
            raise GateError("GAME_FROZEN_PREDICTION_REPLAY_MISMATCH")
        cards.append(prediction)
    return snapshot, {m: p for m, p in zip(
        [r[0] for r in records], cards)}, run_id


def advance_game_workspace(workspace, *, snapshot=None, game=None, observed_at=None) -> dict:
    """Optional single-game operation of SAME existing closed_loop/ledger.

    Each issue freezes six unchanged arms, independently of the other game's
    calendar. This is UNVERIFIED SHADOW evidence, not a formal prospective run.
    Older dual-game run tables are never migrated, erased or treated as new runs.
    """
    root = Path(workspace).absolute()
    _not_symlink(root)
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "ledger.sqlite3"
    _not_symlink(ledger)
    observed = datetime.now(timezone.utc) if observed_at is None else observed_at
    if (not isinstance(observed, datetime) or observed.tzinfo is None
            or observed.utcoffset() is None):
        raise GateError("GAME_OBSERVATION_REQUIRES_AWARE_CLOCK")
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            raise GateError("GAME_SINGLE_SNAPSHOT_REQUIRED")
        expected_game = snapshot.get("lottery")
        if expected_game not in core.RULES or (game is not None and game != expected_game):
            raise GateError("GAME_SNAPSHOT_IDENTITY_MISMATCH")
        game = expected_game
        sha = core.validate_study_snapshot(snapshot)
        issue = _game_issue(snapshot["target_issue"])
        predictions = {m: core.forecast(snapshot, m) for m in core.MODELS}
    elif game not in core.RULES:
        raise GateError("GAME_REQUIRED_FOR_READONLY_TICK")
    if snapshot is None and not ledger.exists():
        raise GateError("GAME_RUN_NOT_REGISTERED")
    conn = sqlite3.connect(str(ledger), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA recursive_triggers=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(GAME_SCHEMA)
        if snapshot is not None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT run_id,snapshot_sha256,snapshot_payload FROM game_runs "
                    "WHERE lottery=? AND issue=?", (game, issue)
                ).fetchone()
                if existing is None:
                    if not core.dt(snapshot["as_of"]) <= observed < core.dt(snapshot["sales_cutoff"]):
                        raise GateError("GAME_FREEZE_AFTER_CUTOFF")
                    run_id = "V47G-" + core.digest({
                        "contract": "V47-INDEPENDENT-GAME-SHADOW-1",
                        "lottery": game, "issue": issue,
                        "snapshot_sha256": sha, "models": list(core.MODELS),
                        "model_source_sha256": core.model_source_sha256(),
                    })[:32]
                    conn.execute(
                        "INSERT INTO game_runs VALUES(?,?,?,?,?,?)",
                        (game, issue, run_id, sha, core.canon(snapshot), observed.isoformat()))
                    for m in core.MODELS:
                        p = predictions[m]
                        conn.execute("INSERT INTO game_predictions VALUES(?,?,?,?)",
                                     (run_id, m, core.canon(p), core.digest(p)))
                elif existing[1:] != (sha, core.canon(snapshot)):
                    raise GateError("GAME_TARGET_ALREADY_FROZEN_DIFFERENT_SNAPSHOT")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        roster = conn.execute(
            "SELECT issue,run_id,snapshot_sha256,snapshot_payload,"
            "frozen_at_local_untrusted FROM game_runs WHERE lottery=?",
            (game,),
        ).fetchall()
        if not roster:
            raise GateError("GAME_RUN_NOT_REGISTERED")
        roster.sort(key=lambda r: int(r[0]))
        loaded = []
        for row in roster:
            ss, cards, rid = _read_frozen_game(conn, game, row)
            loaded.append((row[0], ss, cards, rid))
    finally:
        conn.close()

    outcome_dir = root / "outcomes_by_game" / game
    receipt_dir = root / "receipts_by_game" / game
    for path in (outcome_dir, receipt_dir):
        _not_symlink(path)
        if path.exists() and not path.is_dir():
            raise GateError("GAME_EVIDENCE_DIRECTORY_REQUIRED")
    known_issues = {item[0] for item in loaded}
    if outcome_dir.exists():
        for path in outcome_dir.iterdir():
            _not_symlink(path)
            if path.suffix == ".json" and path.stem not in known_issues:
                raise GateError("GAME_UNKNOWN_OUTCOME_ISSUE")
    if receipt_dir.exists():
        for path in receipt_dir.iterdir():
            _not_symlink(path)
            if path.suffix == ".json" and path.stem not in known_issues:
                raise GateError("GAME_UNKNOWN_SCORE_RECEIPT")
    pending, completed, scores = [], [], []
    for issue, ss, cards, rid in loaded:
        result_file = outcome_dir / (issue + ".json")
        receipt_file = receipt_dir / (issue + ".json")
        if not result_file.exists():
            if receipt_file.exists():
                raise GateError("GAME_RECEIPT_WITHOUT_ORIGINAL_OUTCOME")
            pending.append(issue)
            continue
        result = _read_json(result_file)
        if (not isinstance(result, dict) or set(result) !=
                {"lottery", "issue", "front", "back", "drawn_at"}
                or result.get("lottery") != game
                or result.get("issue") != issue):
            raise GateError("GAME_RESULT_ISSUE_MISMATCH")
        if (observed <= core.dt(ss["target_draw_at"])
                or observed <= core.dt(result["drawn_at"])
                or core.dt(result["drawn_at"]) < core.dt(ss["target_draw_at"])):
            raise GateError("GAME_RESULT_NOT_YET_DRAWN")
        result_sha = core.digest(result)
        comparison = {
            m: core.score(p, result)
            for m, p in cards.items()
        }
        claim = {
            "schema": "V47-PER-GAME-SHADOW-SCORE-1",
            "lottery": game, "issue": issue, "run_id": rid,
            "result_sha256": result_sha, "result": result,
            "frozen_prediction_sha256": {
                m: core.digest(p) for m, p in cards.items()
            },
            "models": comparison, "outcome_source": "CALLER_UNVERIFIED",
            "independent_predraw_timestamp_verified": False,
            "formal_A": 0, "decision": "NO_EDGE",
        }
        claim["score_receipt_sha256"] = core.digest(claim)
        receipt_dir.mkdir(parents=True, exist_ok=True)
        _write_once(receipt_file, claim)
        completed.append(issue)
        scores.append(claim)
    latest = loaded[-1]
    out = {
        "schema": "V47-SHADOW-INDEPENDENT-GAME-1",
        "lottery": game,
        "status": "WAITING_FOR_OUTCOME" if pending else "LOCAL_ROSTER_SHADOW_SCORED",
        "run_ids": [x[3] for x in loaded],
        "frozen_issues": [x[0] for x in loaded],
        "pending_issues": pending,
        "completed_issues": completed,
        "frozen_cards": [latest[2][m] for m in core.MODELS],
        "scores_by_issue": scores,
        "local_ledger_roster_complete": not pending,
        "official_results_authenticated": False,
        "independent_predraw_timestamp_verified": False,
        "research_eligible": False,
        "coverage": "THIS_GAME_LOCAL_FROZEN_ROSTER_ONLY_NOT_OFFICIAL_CALENDAR",
        "legacy_dual_game_runs": "UNCHANGED_SEPARATE_SHADOW_TABLES",
        "formal_A": 0, "decision": "NO_EDGE",
    }
    if not pending:
        hits = {m: sum(record["models"][m]["D2"] for record in scores)
                for m in core.MODELS}
        out["local_d2_diagnostic"] = {
            "draw_count": len(scores), "model_d2_hits": hits,
            "paired_random_null": {
                m: {
                    "wins": sum(r["models"][m]["D2"] == 1
                                and r["models"]["random_null"]["D2"] == 0
                                for r in scores),
                    "losses": sum(r["models"][m]["D2"] == 0
                                  and r["models"]["random_null"]["D2"] == 1
                                  for r in scores),
                }
                for m in core.MODELS if m != "random_null"
            },
            "formal_admission": "BLOCKED_UNVERIFIED_EVIDENCE",
        }
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reentrant V4.7 dual-game SHADOW forecast-score-study loop")
    parser.add_argument("--workspace", required=True,
                        help="Existing SHADOW workspace or new empty folder")
    parser.add_argument("--snapshot-bundle",
                        help="Both games; caller supplied, not official authentication")
    parser.add_argument("--research-history-bundle",
                        help="Optional unverified historical data for exploratory D2 lab")
    parser.add_argument("--game-snapshot",
                        help="Optional SSQ OR DLT snapshot for independent per-game issue cycle")
    parser.add_argument("--game", choices=("SSQ", "DLT"),
                        help="Read-only independent tick of the named game's existing issues")
    args = parser.parse_args(argv)
    try:
        snapshots = (_read_json(Path(args.snapshot_bundle))
                     if args.snapshot_bundle else None)
        research = (_read_json(Path(args.research_history_bundle))
                    if args.research_history_bundle else None)
        if args.game_snapshot or args.game:
            if args.snapshot_bundle or args.research_history_bundle:
                raise GateError("CANNOT_MIX_DUAL_AND_INDEPENDENT_GAME_MODES")
            single = _read_json(Path(args.game_snapshot)) if args.game_snapshot else None
            value = advance_game_workspace(args.workspace, snapshot=single,
                                           game=args.game)
        else:
            value = advance_workspace(args.workspace, snapshots=snapshots,
                                      research_history=research)
    except (GateError, ValueError, TypeError, KeyError, sqlite3.Error, OSError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
