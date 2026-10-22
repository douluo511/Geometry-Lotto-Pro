"""test10 convergence contract for synthetic / unverified V4.7 SHADOW studies.

This is not a sandbox, a trusted clock, an official-data verifier, a TSA client,
or authority to promote a prediction to formal A. No model choices live here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .core import (MODELS, RULES, VERSION, GateError, canon, digest, dt, score,
                   model_source_sha256, parameter_contract, validate_snapshot,
                   validate_study_snapshot, validate_run_manifest_record,
                   load_registered_snapshot, validate_forecast)

ROLES = {
    "test1": "00-CONTROL", "test2": "01-OFFICIAL-DATA",
    "test3": "02-HOT60", "test4": "03-EWMA",
    "test5": "04-SHRINKMIX", "test6": "05-PAIRWISE-D2",
    "test7": "06-CHALLENGER", "test8": "07-RANDOM-NULL",
    "test9": "08-INDEPENDENT-AUDIT", "test10": "09-ENGINEERING",
}
MODEL_ROLES = dict(zip(MODELS, ("test3", "test4", "test5", "test6", "test7", "test8")))
TOOLS = {
    "test1": frozenset({"read_status", "dispatch"}),
    "test2": frozenset({"read_raw_sources", "submit_asof"}),
    "test3": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test4": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test5": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test6": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test7": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test8": frozenset({"read_locked_asof", "submit_own_forecast"}),
    "test9": frozenset({"read_frozen", "read_result", "score_readonly"}),
    "test10": frozenset({"read_ci", "run_synthetic_tests", "inspect_journal"}),
}
STAGES = ("SYNC", "VERIFY", "AUTHORIZE", "PREDICT", "FREEZE", "WAIT",
          "REPLAY", "SCORE", "AUDIT", "REPORT", "NEXT")


ORCHESTRATION_SOURCE_FILES = (
    "convergence.py", "schedule.py", "cli.py", "statistics.py", "source_validation.py",
    "source_fetch.py", "official_intake.py",
    "../../SSQ/SSQ/glp/sources.py", "../../SSQ/SSQ/glp/constants.py",
    "../../SSQ/SSQ/glp/domain.py", "../../SSQ/SSQ/glp/util.py", "../../SSQ/SSQ/glp/net_client.py",
    "../../DLT/src/glp/sources.py", "../../DLT/src/glp/constants.py",
    "../../DLT/src/glp/domain.py", "../../DLT/src/glp/util.py", "../../DLT/src/glp/net_client.py",
    "windows_shadow_tasks.ps1", "invoke_v46_shadow.ps1",
)


def orchestration_source_sha256():
    """Bind every checked-in execution entrypoint that can affect a run."""
    root = Path(__file__).parent
    files = {}
    for name in ORCHESTRATION_SOURCE_FILES:
        path = root / name
        if not path.is_file():
            raise GateError("ORCHESTRATION_SOURCE_MISSING:" + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest({"contract": "V47-ORCHESTRATION-SOURCE-1", "files": files})


def require_tool(role, name):
    """Capability declaration for orchestrator; actual host must enforce it."""
    if role not in ROLES or name not in TOOLS[role]:
        raise GateError("ROLE_TOOL_DENIED")
    return True


def handoff(run_id, lottery, sender, receiver, kind, payload):
    """Serializable handoff, not proof that two ChatGPT tabs are connected."""
    if not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("INVALID_RUN_ID")
    if lottery not in RULES or sender not in ROLES or receiver not in ROLES:
        raise GateError("INVALID_HANDOFF_IDENTITY")
    if not isinstance(payload, dict) or kind not in ("LOCKED_ASOF", "FROZEN_FORECAST", "AUDIT_RECEIPT"):
        raise GateError("INVALID_HANDOFF_PAYLOAD")
    producers = set(MODEL_ROLES.values())
    if sender in producers and receiver in producers:
        raise GateError("PRODUCER_TO_PRODUCER_HANDOFF_DENIED")
    if kind == "LOCKED_ASOF" and (sender, receiver) not in {
        ("test2", r) for r in producers
    }:
        raise GateError("LOCKED_ASOF_MUST_ORIGINATE_DATA_ROLE")
    if kind == "FROZEN_FORECAST" and not (sender in producers and receiver in ("test1", "test9", "test10")):
        raise GateError("FORECAST_HANDOFF_DENIED")
    if kind == "AUDIT_RECEIPT" and not (sender == "test9" and receiver == "test1"):
        raise GateError("AUDIT_HANDOFF_DENIED")
    if kind == "FROZEN_FORECAST":
        model = payload.get("model")
        if MODEL_ROLES.get(model) != sender:
            raise GateError("MODEL_ROLE_IDENTITY_MISMATCH")
    return {"schema": "V47-HANDOFF-1", "run_id": run_id, "lottery": lottery,
            "sender": sender, "receiver": receiver, "kind": kind,
            "payload_sha256": digest(payload), "payload": payload,
            "claim": "UNVERIFIED_EXTERNAL_HANDOFF_SHADOW_ONLY"}


def verify_local_source_bytes(snapshot, sources):
    """Check two pinned local raw originals; NEVER conclude official authenticity."""
    validate_snapshot(snapshot)
    if not isinstance(sources, list) or len(sources) != 2:
        raise GateError("TWO_RAW_SOURCES_REQUIRED")
    seen_urls, seen_paths = set(), set()
    rows = []
    for s in sources:
        if not isinstance(s, dict) or set(s) != {"url", "path", "sha256", "published_at", "fetched_at"}:
            raise GateError("INVALID_SOURCE_SCHEMA")
        url = s["url"]
        path = Path(s["path"])
        if not isinstance(url, str) or not url.startswith("https://") or url in seen_urls:
            raise GateError("TWO_DISTINCT_HTTPS_SOURCES_REQUIRED")
        if not path.is_file() or str(path.resolve()) in seen_paths:
            raise GateError("TWO_DISTINCT_RAW_FILES_REQUIRED")
        seen_urls.add(url)
        seen_paths.add(str(path.resolve()))
        if not dt(s["published_at"]) <= dt(s["fetched_at"]) <= dt(snapshot["as_of"]):
            raise GateError("SOURCE_AFTER_ASOF")
        raw = path.read_bytes()
        observed = hashlib.sha256(raw).hexdigest()
        if observed != s["sha256"]:
            raise GateError("RAW_SHA256_MISMATCH")
        rows.append({"url": url, "sha256": observed, "published_at": s["published_at"],
                     "fetched_at": s["fetched_at"], "size_bytes": len(raw)})
    return {"lottery": snapshot["lottery"], "target_issue": str(snapshot["target_issue"]),
            "snapshot_sha256": digest(snapshot), "raw_evidence": rows,
            "local_byte_integrity": "PASS",
            "source_authenticity": "NOT_VERIFIED",
            "official_target_admission": "BLOCKED", "formal_A": 0}


def manifest(snapshots):
    """Stable shared RUN_ID, different immutable identity per game."""
    if not isinstance(snapshots, dict) or set(snapshots) != set(RULES):
        raise GateError("BOTH_GAMES_REQUIRED")
    games = {}
    for game in sorted(RULES):
        s = snapshots[game]
        if s.get("lottery") != game:
            raise GateError("GAME_SNAPSHOT_MISMATCH")
        checksum = validate_study_snapshot(s)
        games[game] = {
            "issue": str(s["target_issue"]), "as_of": s["as_of"],
            "sales_cutoff": s["sales_cutoff"], "target_draw_at": s["target_draw_at"],
            "snapshot_sha256": checksum,
        }
    models = {
        m: {
            "role": MODEL_ROLES[m],
            "version": VERSION,
            "parameters_sha256": digest(parameter_contract(m)),
            "model_source_sha256": model_source_sha256(),
        }
        for m in MODELS
    }
    tool_whitelist = {k: sorted(v) for k, v in TOOLS.items()}
    harness_source_sha = orchestration_source_sha256()
    identity = {
        "protocol": "V47-RUN-1",
        "games": games,
        "models": models,
        "tool_whitelist": tool_whitelist,
        "harness_source_sha256": harness_source_sha,
    }
    run_id = "V47-" + digest(identity)[:32]
    return {"schema": "V47-RUN-1", "run_id": run_id,
            "identity": identity, "identity_sha256": digest(identity),
            "games": games, "models": models,
            "tool_whitelist": tool_whitelist,
            "harness_source_sha256": harness_source_sha,
            "qualifications": {"challenger": "EXPLORATORY_UNREGISTERED",
                               "all_arms": "SHADOW_ONLY", "formal_A": 0},
            "official_evidence": "BLOCKED", "external_tsa": "NOT_RUN",
            "study_decision": "NO_EDGE"}


WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_events(
    run_id TEXT NOT NULL, lottery TEXT NOT NULL, stage TEXT NOT NULL,
    event_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(run_id,lottery,stage)
);
CREATE TRIGGER IF NOT EXISTS workflow_no_update BEFORE UPDATE ON workflow_events
BEGIN SELECT RAISE(ABORT, 'immutable workflow'); END;
CREATE TRIGGER IF NOT EXISTS workflow_no_delete BEFORE DELETE ON workflow_events
BEGIN SELECT RAISE(ABORT, 'immutable workflow'); END;
CREATE TABLE IF NOT EXISTS tsa_claims(
    run_id TEXT NOT NULL, lottery TEXT NOT NULL, prediction_batch_sha256 TEXT NOT NULL,
    request_sha256 TEXT NOT NULL, receipt_sha256 TEXT,
    verification TEXT NOT NULL CHECK(verification = 'NOT_VERIFIED'),
    PRIMARY KEY(run_id, lottery)
);
CREATE TRIGGER IF NOT EXISTS tsa_no_update BEFORE UPDATE ON tsa_claims
BEGIN SELECT RAISE(ABORT, 'immutable TSA claim'); END;
CREATE TRIGGER IF NOT EXISTS tsa_no_delete BEFORE DELETE ON tsa_claims
BEGIN SELECT RAISE(ABORT, 'immutable TSA claim'); END;
"""


def init_workflow(conn):
    # Preserve immutable guards for INSERT OR REPLACE on workflow/TSA rows.
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.executescript(WORKFLOW_SCHEMA)


def register_manifest(conn, value):
    """Persist the complete manifest preimage before any V47 prediction row."""
    if not isinstance(value, dict) or value.get("schema") != "V47-RUN-1":
        raise GateError("INVALID_V47_MANIFEST")
    identity = value.get("identity")
    if (not isinstance(identity, dict)
            or value.get("identity_sha256") != digest(identity)
            or value.get("run_id") != "V47-" + digest(identity)[:32]):
        raise GateError("V47_MANIFEST_DERIVATION_MISMATCH")
    for key in ("games", "models", "tool_whitelist", "harness_source_sha256"):
        if value.get(key) != identity.get(key):
            raise GateError("V47_MANIFEST_IDENTITY_PAYLOAD_MISMATCH")
    if set(value.get("models", {})) != set(MODELS) or set(value.get("games", {})) != set(RULES):
        raise GateError("V47_MANIFEST_INCOMPLETE")
    payload = canon(value)
    checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    existing = conn.execute(
        "SELECT manifest_sha256,payload FROM run_manifests WHERE run_id=?",
        (value["run_id"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO run_manifests(run_id,manifest_sha256,payload,evidence_class) "
            "VALUES(?,?,?,'SHADOW')",
            (value["run_id"], checksum, payload),
        )
    elif existing != (checksum, payload):
        raise GateError("CONFLICTING_V47_MANIFEST_RETRY")
    return checksum


def check_complete_batch(conn, run_id, lottery):
    """Exactly six frozen model rows and a matching persisted V4.7 manifest."""
    registered = validate_run_manifest_record(conn, run_id)
    if registered is None:
        raise GateError("V47_MANIFEST_REQUIRED")
    expected_game = registered["games"].get(lottery)
    context = conn.execute(
        "SELECT snapshot_sha256,target_issue FROM run_context WHERE run_id=? AND lottery=?",
        (run_id, lottery)).fetchone()
    if context is None:
        raise GateError("MISSING_LOCKED_RUN_CONTEXT")
    if (expected_game is None or expected_game.get("snapshot_sha256") != context[0]
            or expected_game.get("issue") != context[1]):
        raise GateError("RUN_MANIFEST_CONTEXT_MISMATCH")
    snapshot = load_registered_snapshot(conn, run_id, lottery)
    if (snapshot.get("target_issue") != context[1]
            or snapshot.get("as_of") != expected_game.get("as_of")
            or snapshot.get("sales_cutoff") != expected_game.get("sales_cutoff")):
        raise GateError("RUN_SNAPSHOT_CONTEXT_MISMATCH")
    rows = conn.execute(
        "SELECT model,payload,prediction_sha256,snapshot_sha256 FROM predictions "
        "WHERE run_id=? AND lottery=?", (run_id, lottery)).fetchall()
    if len(rows) != len(MODELS) or {x[0] for x in rows} != set(MODELS):
        raise GateError("INCOMPLETE_SIX_MODEL_BATCH")
    hashes = {}
    for model, payload, checksum, snap in rows:
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != checksum or snap != context[0]:
            raise GateError("FROZEN_PREDICTION_INTEGRITY_FAIL")
        p = json.loads(payload)
        # Independently replay against the persisted snapshot, not just payload hashes.
        validate_forecast(p, snapshot)
        model_identity = registered["models"].get(model)
        if (p.get("model") != model or p.get("target_issue") != context[1]
                or p.get("primary_d2") != p.get("candidates_1_to_5", [])[:2]
                or model_identity is None
                or p.get("version") != model_identity.get("version")
                or p.get("parameters_sha256") != model_identity.get("parameters_sha256")
                or p.get("model_source_sha256") != model_identity.get("model_source_sha256")):
            raise GateError("FROZEN_MODEL_IDENTITY_FAIL")
        hashes[model] = checksum
    return digest(hashes)


def append_stage(conn, run_id, lottery, stage, evidence):
    """Ordered, append-only, idempotent transitions; does not award formal PASS."""
    if lottery not in RULES or stage not in STAGES or not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("INVALID_STAGE_IDENTITY")
    if not isinstance(evidence, dict) or evidence.get("formal_A") not in (None, 0, False):
        raise GateError("FORMAL_A_FORBIDDEN")
    if evidence.get("status") in ("FORMAL", "A", "PASS_OFFICIAL", "TSA_VERIFIED"):
        raise GateError("UNSUPPORTED_AUTHORITY_CLAIM")
    record = {"run_id": run_id, "lottery": lottery, "stage": stage,
              "evidence": evidence, "class": "SHADOW"}
    payload, checksum = canon(record), digest(record)
    previous = conn.execute(
        "SELECT event_sha256,payload FROM workflow_events "
        "WHERE run_id=? AND lottery=? AND stage=?", (run_id, lottery, stage)).fetchone()
    if previous is not None:
        if previous != (checksum, payload):
            raise GateError("CONFLICTING_WORKFLOW_RETRY")
        return checksum
    done = [row[0] for row in conn.execute(
        "SELECT stage FROM workflow_events WHERE run_id=? AND lottery=? ORDER BY rowid",
        (run_id, lottery))]
    if done != list(STAGES[:len(done)]) or stage != STAGES[len(done)]:
        raise GateError("STAGE_ORDER_VIOLATION")
    if stage == "FREEZE":
        batch = check_complete_batch(conn, run_id, lottery)
        if evidence.get("batch_sha256") != batch:
            raise GateError("BATCH_HASH_MISMATCH")
    conn.execute(
        "INSERT INTO workflow_events VALUES(?,?,?,?,?)",
        (run_id, lottery, stage, checksum, payload))
    return checksum


def tsa_request(conn, run_id, lottery):
    """Creates immutable outgoing request record; NOT a receipt verification."""
    batch_sha = check_complete_batch(conn, run_id, lottery)
    request_sha = digest({"schema": "V47-TSA-REQUEST-1", "run_id": run_id,
                          "lottery": lottery, "batch_sha256": batch_sha})
    old = conn.execute("SELECT prediction_batch_sha256,request_sha256 FROM tsa_claims "
                       "WHERE run_id=? AND lottery=?", (run_id, lottery)).fetchone()
    if old is None:
        conn.execute("INSERT INTO tsa_claims VALUES(?,?,?,?,?,?)",
                     (run_id, lottery, batch_sha, request_sha, None, "NOT_VERIFIED"))
    elif old != (batch_sha, request_sha):
        raise GateError("TSA_REQUEST_CONTEXT_MISMATCH")
    return {"request_sha256": request_sha, "external_tsa": "NOT_VERIFIED",
            "formal_A": 0}


def score_readonly(db_path, run_id, official_result):
    """Read-only six-stream diagnostic; caller's results are NOT authenticated."""
    lottery = official_result.get("lottery")
    if lottery not in RULES:
        raise GateError("UNKNOWN_GAME")
    connection = sqlite3.connect("file:" + str(Path(db_path).resolve()) + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        checksum = check_complete_batch(connection, run_id, lottery)
        items = connection.execute(
            "SELECT model,payload FROM predictions WHERE run_id=? AND lottery=? ORDER BY model",
            (run_id, lottery)).fetchall()
    finally:
        connection.close()
    results = {model: score(json.loads(payload), official_result)
               for model, payload in items}
    control = results["random_null"]["D2"]
    return {"run_id": run_id, "lottery": lottery,
            "prediction_batch_sha256": checksum, "scores": results,
            "same_draw_d2_delta_vs_null": {
                model: row["D2"] - control for model, row in results.items()
                if model != "random_null"},
            "outcome_source": "CALLER_UNVERIFIED", "statistical_decision": "NO_EDGE",
            "formal_A": 0}
