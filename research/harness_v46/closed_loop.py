"""One reentrant SSQ+DLT SHADOW execution loop over the original V4.7 ledger.

Given already available snapshots and caller outcomes, join forecast -> immutable
freeze -> read-only scoring -> complete-roster D2/Random-NULL study. Does NOT
authenticate official feeds, control a host scheduler, approve an RFC3161 root,
or claim prospective lottery advantage. Never backfill a missing forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import uuid
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
from . import official_intake
from . import frozen_replay

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


def _matching_frozen_snapshot_run(ledger, existing, snapshots):
    """Match exact old input bytes before deriving any current-version identity."""
    if not isinstance(snapshots, dict) or set(snapshots) != set(core.RULES):
        raise GateError("BOTH_GAME_SNAPSHOTS_REQUIRED")
    if not existing:
        return None
    matches = []
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        for run_id in existing:
            # Validate every existing roster before a new irreversible freeze.
            # A corrupted/missing historical artifact is not permission to mint
            # another run from the same target under today's source version.
            cycle.frozen_forecast_report(ledger, run_id)
            original = {g: frozen_replay.load_snapshot(conn, run_id, g)
                        for g in core.RULES}
            if core.canon(original) == core.canon(snapshots):
                matches.append(run_id)
    finally:
        conn.close()
    if len(matches) > 1:
        raise GateError("AMBIGUOUS_FROZEN_SNAPSHOT_RUNS")
    return matches[0] if matches else None


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
        desired = (_matching_frozen_snapshot_run(ledger, existing, snapshots)
                   or manifest(snapshots)["run_id"])
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
    records = conn.execute(
        "SELECT model,payload,prediction_sha256 FROM game_predictions WHERE run_id=?",
        (run_id,),
    ).fetchall()
    if len(records) != len(core.MODELS) or {r[0] for r in records} != set(core.MODELS):
        raise GateError("GAME_INCOMPLETE_SIX_ARM_FREEZE")
    cards = {}
    for model, raw, sha in records:
        prediction = json.loads(raw)
        if (core.digest(prediction) != sha or core.canon(prediction) != raw
                or prediction.get("model") != model):
            raise GateError("GAME_FROZEN_PREDICTION_REPLAY_MISMATCH")
        cards[model] = prediction
    sources = {p.get("model_source_sha256") for p in cards.values()}
    if len(sources) != 1:
        raise GateError("REPLAY_MIXED_MODEL_SOURCES")
    source_sha = sources.pop()
    replay = frozen_replay.resolve_core(source_sha)
    if (core.canon(snapshot) != payload or
            replay.validate_study_snapshot(snapshot) != snapshot_sha or
            snapshot["lottery"] != game or _game_issue(snapshot["target_issue"]) != issue):
        raise GateError("GAME_SNAPSHOT_REPLAY_MISMATCH")
    if not core.dt(snapshot["as_of"]) <= core.dt(frozen_at) < core.dt(snapshot["sales_cutoff"]):
        raise GateError("GAME_FROZEN_LOCAL_TIME_INVALID")
    expected_run = "V47G-" + core.digest({
        "contract": "V47-INDEPENDENT-GAME-SHADOW-1",
        "lottery": game, "issue": issue,
        "snapshot_sha256": snapshot_sha, "models": list(core.MODELS),
        "model_source_sha256": source_sha,
    })[:32]
    if run_id != expected_run:
        raise GateError("GAME_RUN_IDENTITY_MISMATCH")
    for model, prediction in cards.items():
        if prediction != replay.forecast(snapshot, model):
            raise GateError("GAME_FROZEN_PREDICTION_REPLAY_MISMATCH")
    return snapshot, cards, run_id


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
        sha = core.digest(snapshot)
        issue = _game_issue(snapshot["target_issue"])
    elif game not in core.RULES:
        raise GateError("GAME_REQUIRED_FOR_READONLY_TICK")
    if snapshot is None and not ledger.exists():
        raise GateError("GAME_RUN_NOT_REGISTERED")
    conn = (sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True, timeout=30,
                            isolation_level=None) if snapshot is None else
            sqlite3.connect(str(ledger), timeout=30, isolation_level=None))
    try:
        if snapshot is None:
            conn.execute("PRAGMA query_only=ON")
        else:
            conn.execute("PRAGMA recursive_triggers=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(GAME_SCHEMA)
        if snapshot is not None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Before adding irreversible frozen cards, reject evidence that
                # would otherwise fail this tick only AFTER the SQLite commit.
                # Read the registered issues under the same writer transaction.
                registered = {
                    row[0] for row in conn.execute(
                        "SELECT issue FROM game_runs WHERE lottery=?", (game,)
                    )
                }
                for dirname, unknown_issue in (
                    ("outcomes_by_game", "GAME_UNKNOWN_OUTCOME_ISSUE"),
                    ("receipts_by_game", "GAME_UNKNOWN_SCORE_RECEIPT"),
                ):
                    evidence_dir = root / dirname / game
                    _not_symlink(evidence_dir)
                    if evidence_dir.exists():
                        if not evidence_dir.is_dir():
                            raise GateError("GAME_EVIDENCE_DIRECTORY_REQUIRED")
                        for evidence_file in evidence_dir.iterdir():
                            _not_symlink(evidence_file)
                            if (evidence_file.suffix == ".json"
                                    and evidence_file.stem not in registered):
                                raise GateError(unknown_issue)
                existing = conn.execute(
                    "SELECT run_id,snapshot_sha256,snapshot_payload FROM game_runs "
                    "WHERE lottery=? AND issue=?", (game, issue)
                ).fetchone()
                if existing is None:
                    # New forecasts use today's core. An exact existing input
                    # is replayed under its original source instead, even if
                    # today's selectors or validation behavior have changed.
                    core.validate_study_snapshot(snapshot)
                    predictions = {m: core.forecast(snapshot, m) for m in core.MODELS}
                    # Recheck after the SQLite write lock; model generation and
                    # lock acquisition can consume the entire presale window.
                    # Caller-supplied observed_at is for synthetic SHADOW tests,
                    # not independently authenticated time.
                    locked_at = datetime.now(timezone.utc) if observed_at is None else observed
                    if not core.dt(snapshot["as_of"]) <= locked_at < core.dt(snapshot["sales_cutoff"]):
                        raise GateError("GAME_FREEZE_AFTER_CUTOFF")
                    run_id = "V47G-" + core.digest({
                        "contract": "V47-INDEPENDENT-GAME-SHADOW-1",
                        "lottery": game, "issue": issue,
                        "snapshot_sha256": sha, "models": list(core.MODELS),
                        "model_source_sha256": core.model_source_sha256(),
                    })[:32]
                    for m in core.MODELS:
                        p = predictions[m]
                        conn.execute("INSERT INTO game_predictions VALUES(?,?,?,?)",
                                     (run_id, m, core.canon(p), core.digest(p)))
                    # The final check and frozen timestamp belong to the same
                    # transaction; rejection rolls back all six inserted cards.
                    frozen_at = datetime.now(timezone.utc) if observed_at is None else observed
                    if frozen_at < locked_at:
                        raise GateError("GAME_FREEZE_CLOCK_MOVED_BACKWARD")
                    if not core.dt(snapshot["as_of"]) <= frozen_at < core.dt(snapshot["sales_cutoff"]):
                        raise GateError("GAME_FREEZE_AFTER_CUTOFF")
                    conn.execute(
                        "INSERT INTO game_runs VALUES(?,?,?,?,?,?)",
                        (game, issue, run_id, sha, core.canon(snapshot), frozen_at.isoformat()))
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
            m: frozen_replay.score_prediction(p, result)
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



# Every scheduled attempt, including blocked/no-snapshot ones, has an append-only
# local SHADOW journal. Local SHA-256 is NOT independent or WORM proof.
OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS operational_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    lottery TEXT,
    event_payload TEXT NOT NULL,
    event_sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS protect_operational_events_update
BEFORE UPDATE ON operational_events
BEGIN SELECT RAISE(ABORT, 'operational event immutable'); END;
CREATE TRIGGER IF NOT EXISTS protect_operational_events_delete
BEFORE DELETE ON operational_events
BEGIN SELECT RAISE(ABORT, 'operational event immutable'); END;
"""


def _operational_append(conn, tick_id, event_type, lottery, payload):
    conn.execute(
        "INSERT INTO operational_events "
        "(tick_id,event_type,lottery,event_payload,event_sha256) VALUES(?,?,?,?,?)",
        (tick_id, event_type, lottery, core.canon(payload), core.digest(payload)),
    )


def _operational_open(ledger):
    _not_symlink(ledger)
    conn = sqlite3.connect(str(ledger), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(OPERATIONAL_SCHEMA)
        return conn
    except BaseException:
        conn.close()
        raise


def _operational_check_journal(conn):
    # A privileged SQLite edit can remove triggers: validate old bytes before
    # any new network call or append. This is defense-in-depth, not external WORM.
    rows = conn.execute(
        "SELECT tick_id,event_type,lottery,event_payload,event_sha256 "
        "FROM operational_events ORDER BY event_id"
    ).fetchall()
    starts, finishes = set(), set()
    for tick_id, event_type, lottery, raw, checksum in rows:
        try:
            parsed = json.loads(raw, object_pairs_hook=_unique_object,
                                parse_constant=_reject_nonfinite)
            valid = (isinstance(parsed, dict) and core.canon(parsed) == raw
                     and core.digest(parsed) == checksum)
        except (TypeError, ValueError, GateError, OverflowError):
            valid = False
        if (not valid or not isinstance(tick_id, str)
                or not isinstance(event_type, str)):
            raise GateError("OPERATIONAL_EVENT_HASH_OR_SCHEMA_MISMATCH")
        if event_type == "STARTED":
            starts.add(tick_id)
        elif event_type == "FINISHED":
            finishes.add(tick_id)
    return sorted(starts - finishes), len(starts)


def _operational_record(ledger, tick_id, kind, game, payload):
    conn = _operational_open(ledger)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _operational_append(conn, tick_id, kind, game, payload)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _local_game_roster(ledger):
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    try:
        exists = conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='game_runs'"
        ).fetchone()[0]
        if not exists:
            return set()
        return {(game, issue) for game, issue in conn.execute(
            "SELECT lottery,issue FROM game_runs"
        )}
    finally:
        conn.close()


def operational_tick(workspace, *, snapshot_paths=None, intake_timeout_seconds=600):
    """One bounded two-game *attempt*, not a certified official forecast cycle.

    Start journal is durable before any network work; a crashed tick remains
    unfinished and must be visible to the next invocation. An absent/invalid
    target cannot turn a source-history observation into a forecast or result.
    Always attempt the second game and score any already frozen local roster.
    """
    if (type(intake_timeout_seconds) not in (int, float)
            or not math.isfinite(intake_timeout_seconds)
            or not 0 < intake_timeout_seconds <= 3600):
        raise GateError("OPERATIONAL_INTAKE_TIMEOUT_INVALID")
    if snapshot_paths is None:
        snapshot_paths = {}
    if (not isinstance(snapshot_paths, dict)
            or set(snapshot_paths) - set(core.RULES)):
        raise GateError("OPERATIONAL_SNAPSHOT_PATHS_INVALID")
    root = Path(workspace).absolute()
    _not_symlink(root)
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "ledger.sqlite3"
    tick_id = "V47T-" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    conn = _operational_open(ledger)
    try:
        conn.execute("BEGIN IMMEDIATE")
        unfinished, prior_count = _operational_check_journal(conn)
        _operational_append(conn, tick_id, "STARTED", None, {
            "tick_id": tick_id, "observed_at_local_untrusted": now.isoformat(),
            "runner_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "intake_timeout_seconds": intake_timeout_seconds,
            "trust": "LOCAL_CLOCK_UNTRUSTED",
        })
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    original_roster = _local_game_roster(ledger)
    games = {}
    intake_root = root / "operational_intake" / tick_id
    _not_symlink(intake_root)
    intake_root.mkdir(parents=True, exist_ok=False)
    for game in ("SSQ", "DLT"):
        state = {
            "target_gate": "BLOCKED_NO_EXPLICIT_SNAPSHOT",
            "formal_A": 0, "decision": "NO_EDGE",
            "source_authenticity": "NOT_VERIFIED",
        }
        try:
            collected = official_intake.collect_live_history(
                game, timeout_seconds=intake_timeout_seconds)
        except Exception as exc:
            collected = {
                "schema": official_intake.SCHEMA,
                "lottery": game, "status": "BLOCKED",
                "sources": [], "consensus_draws": [],
                "errors": {"collector_exception": type(exc).__name__ + ": " + str(exc)},
                "official_history_admission": "BLOCKED",
                "official_target_admission": "BLOCKED",
                "formal_A": 0, "decision": "NO_EDGE",
            }
        # Exact original bytes/worker diagnostics belong in a distinct,
        # create-only directory for EVERY attempt, even when a source fails.
        try:
            saved = official_intake.write_bundle(
                {"schema": "V47-OPERATIONAL-INTAKE-SHADOW-1",
                 "games": {game: collected}},
                intake_root / game)
            state["intake_manifest_path"] = str(saved)
            state["intake_manifest_sha256"] = hashlib.sha256(
                saved.read_bytes()).hexdigest()
        except Exception as exc:
            state["artifact_error"] = type(exc).__name__ + ": " + str(exc)
        state["source_status"] = collected.get("status", "BLOCKED")
        # Nothing in the fetched history grants target/cutoff approval.
        # Only explicit caller-supplied SHADOW snapshots can be frozen.
        if game in snapshot_paths:
            try:
                snapshot = _read_json(Path(snapshot_paths[game]))
                if (not isinstance(snapshot, dict)
                        or snapshot.get("lottery") != game):
                    raise GateError("GAME_SNAPSHOT_IDENTITY_MISMATCH")
                scoring = advance_game_workspace(root, snapshot=snapshot, game=game)
                state["target_gate"] = "SHADOW_EXPLICIT_SNAPSHOT_ONLY"
                state["scoring"] = scoring
            except (GateError, OSError, ValueError, TypeError, KeyError,
                    sqlite3.Error) as exc:
                state["target_error"] = type(exc).__name__ + ": " + str(exc)
        if "scoring" not in state:
            try:
                state["scoring"] = advance_game_workspace(root, game=game)
            except (GateError, OSError, ValueError, TypeError, KeyError,
                    sqlite3.Error) as exc:
                state["scoring"] = {
                    "status": "BLOCKED_NO_LOCAL_FROZEN_ROSTER",
                    "pending_issues": [], "completed_issues": [],
                    "reason": type(exc).__name__ + ": " + str(exc),
                    "formal_A": 0, "decision": "NO_EDGE",
                }
        games[game] = state
        _operational_record(ledger, tick_id, "GAME_RESULT", game, {
            "tick_id": tick_id, "game": game,
            "intake_manifest_sha256": state.get("intake_manifest_sha256"),
            "target_gate": state["target_gate"],
            "target_error": state.get("target_error"),
            "artifact_error": state.get("artifact_error"),
            "scoring_status": state["scoring"]["status"],
            "source_status": state["source_status"],
        })
    current_roster = _local_game_roster(ledger)
    completed = sum(len(v["scoring"].get("completed_issues", []))
                    for v in games.values())
    pending = sum(len(v["scoring"].get("pending_issues", []))
                  for v in games.values())
    result = {
        "schema": "V47-OPERATIONAL-TICK-SHADOW-1",
        "tick_id": tick_id, "games": games,
        "new_frozen_issue_count": len(current_roster - original_roster),
        "local_frozen_issue_count": len(current_roster),
        "local_scored_issue_count": completed,
        "local_pending_issue_count": pending,
        "operational_attempt_count": prior_count + 1,
        "unfinished_prior_tick_ids": unfinished,
        "formal_future_denominator": "NOT_VERIFIED",
        "coverage": "ATTEMPTS_AND_LOCAL_FROZEN_ROSTER_NOT_OFFICIAL_CALENDAR",
        "independent_timestamp": "NOT_VERIFIED",
        "official_results_authenticated": False,
        "formal_A": 0, "decision": "NO_EDGE",
    }
    _operational_record(ledger, tick_id, "FINISHED", None, {
        "tick_id": tick_id, "new_frozen_issue_count": result["new_frozen_issue_count"],
        "local_scored_issue_count": completed, "formal_A": 0,
        "decision": "NO_EDGE",
    })
    return result


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
    parser.add_argument("--operational-tick", action="store_true",
                        help="run two independent SHADOW source/scoring attempts")
    parser.add_argument("--intake-timeout-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        if args.operational_tick:
            if (args.snapshot_bundle or args.research_history_bundle
                    or args.game_snapshot or args.game):
                raise GateError("OPERATIONAL_MODE_CANNOT_MIX_INPUT_MODES")
            value = operational_tick(args.workspace,
                                     intake_timeout_seconds=args.intake_timeout_seconds)
            print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
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
