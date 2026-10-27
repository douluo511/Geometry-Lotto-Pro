"""Bounded local audit coordination, never a formal lottery/deployment gate.

Role labels and review notes are supplied claims, not authenticated identities.
Local hashes/triggers are not WORM: privileged rewrites and tail deletion cannot
be externally excluded. Resource bounds are cooperative, not process isolation.
No handler launches programs, uses a network, or replays forecasting code.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from . import core, audit_intake_bundle

GateError = core.GateError
MAX_REQUEST, MAX_RECORD = 16_384, 140_000
MAX_FILE, MAX_TOTAL = 32_000_000, 256_000_000
MAX_FILES, MAX_ROWS, MAX_SECONDS = 4_000, 20_000, 45
KINDS = ("source_integrity", "journal_integrity", "intake_integrity", "frozen_inventory", "container_readiness")
DEPENDENCIES = {"source_integrity": (), "journal_integrity": ("source_integrity",),
                "intake_integrity": ("journal_integrity",), "frozen_inventory": ("journal_integrity",),
                "container_readiness": ()}
ROLES = {"orchestrator", "researcher", "developer", "executor", "reviewer"}
PHASES = ("DISCOVER", "PLAN", "AUTHORIZE", "EXECUTE_STARTED", "VERIFY", "RECORD", "NEXT")
OUTCOMES = {"LOCAL_CHECK_OK", "FAILED", "BLOCKED"}
HEX40, HEX64 = re.compile(r"[0-9a-f]{40}\Z"), re.compile(r"[0-9a-f]{64}\Z")
_LOCK = threading.RLock()
_TABLES = {
    "sessions": "session_id TEXT PRIMARY KEY, session_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL",
    "tasks": "task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, UNIQUE(session_id,kind), UNIQUE(session_id,ordinal)",
    "events": "event_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, task_id TEXT NOT NULL, phase TEXT NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, UNIQUE(task_id,phase), UNIQUE(task_id,sequence)",
    "evidence": "evidence_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL",
    "facts": "fact_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, evidence_id TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL",
    "reviews": "review_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL",
}
_KEYS = {"sessions": ("session_id", "session_key"), "tasks": ("task_id",),
         "events": ("event_id",), "evidence": ("evidence_id", "task_id"),
         "facts": ("fact_id",), "reviews": ("review_id",)}


def _fail(reason):
    raise GateError("AGENT_AUDIT_" + reason)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail("JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _nonfinite(value):
    _fail("NONFINITE_JSON")


def _float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        _fail("NONFINITE_JSON")
    return parsed


def _parse(raw, limit=MAX_RECORD):
    if not isinstance(raw, (str, bytes)) or len(raw) > limit:
        _fail("JSON_SIZE_LIMIT")
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite, parse_float=_float)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise GateError("AGENT_AUDIT_INVALID_JSON") from exc


def _encoded(value):
    try:
        raw = core.canon(value).encode("utf-8")
        _parse(raw, max(len(raw), MAX_RECORD))
        return raw
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise GateError("AGENT_AUDIT_INVALID_VALUE") from exc


def _physical(path):
    value = os.fspath(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\" + value
    return Path(value)


def _is_reparse(path):
    try:
        meta = _physical(path).lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GateError("AGENT_AUDIT_PATH_METADATA_UNREADABLE") from exc
    return stat.S_ISLNK(meta.st_mode) or bool(getattr(meta, "st_file_attributes", 0) &
                                           getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _component(value):
    if (not value or value in {".", ".."} or value[-1:] in {".", " "}
            or any(c in value for c in ':\\\x00<>"|?*') or any(ord(c) < 32 for c in value)
            or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
            or re.fullmatch(r"(?:COM|LPT)[1-9](?:\..*)?", value, re.I)):
        _fail("UNSAFE_PATH_COMPONENT")


def _path(path):
    raw = os.fspath(path)
    if not isinstance(raw, str) or raw.startswith(("\\\\", "//")):
        _fail("UNC_OR_DEVICE_PATH_FORBIDDEN")
    candidate = Path(raw)
    for part in candidate.parts:
        if part != candidate.anchor:
            _component(part)
    absolute = candidate.absolute()
    # Inspect before resolve: resolving would erase junction/symlink evidence.
    for part in reversed((absolute, *absolute.parents)):
        if _is_reparse(part):
            _fail("REPARSE_PATH_FORBIDDEN")
    return absolute


def _relative(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        _fail("INVALID_RELATIVE_PATH")
    p = PurePosixPath(value)
    if p.is_absolute() or p.as_posix() != value:
        _fail("NONCANONICAL_RELATIVE_PATH")
    for part in p.parts:
        _component(part)
    return p


class _Budget:
    def __init__(self):
        self.started, self.bytes, self.files = time.monotonic(), 0, 0

    def check(self):
        if time.monotonic() - self.started > MAX_SECONDS:
            _fail("COOPERATIVE_TIME_LIMIT")

    def visit(self):
        self.check()
        self.files += 1
        if self.files > MAX_FILES:
            _fail("FILE_OR_VISIT_COUNT_LIMIT")

    def read(self, path, limit=MAX_FILE):
        self.check()
        p = _physical(_path(path))
        if not p.is_file():
            _fail("FILE_MISSING")
        if p.stat().st_size > limit:
            _fail("FILE_SIZE_LIMIT")
        self.files += 1
        if self.files > MAX_FILES:
            _fail("FILE_COUNT_LIMIT")
        with p.open("rb") as stream:
            raw = stream.read(limit + 1)
        self.bytes += len(raw)
        self.check()
        if len(raw) > limit or self.bytes > MAX_TOTAL:
            _fail("BYTE_LIMIT")
        return raw


def _tree(root, budget):
    result, pending, count = {}, [root], 0
    while pending:
        budget.check()
        for physical in _physical(pending.pop()).iterdir():
            count += 1
            if count > MAX_FILES * 2:
                _fail("TREE_ENTRY_LIMIT")
            text = str(physical)
            if os.name == "nt" and text.startswith("\\\\?\\"):
                text = text[4:]
            child = _path(text)
            relative = child.relative_to(root).as_posix()
            if len(_relative(relative).parts) > 32:
                _fail("TREE_DEPTH_LIMIT")
            if _physical(child).is_dir():
                pending.append(child)
            elif _physical(child).is_file():
                result[relative] = child
                if len(result) > MAX_FILES:
                    _fail("TREE_FILE_LIMIT")
            else:
                _fail("UNSUPPORTED_FILE_TYPE")
    return result


def _source_pin(root):
    root, budget = _path(root), _Budget()
    capture_bytes = budget.read(root / "source_capture.json", 2_000_000)
    tree_bytes = budget.read(root / "source_tree.json", 3_000_000)
    capture, tree = _parse(capture_bytes, 2_000_000), _parse(tree_bytes, 3_000_000)
    if (not isinstance(capture, dict) or not isinstance(tree, dict)
            or not HEX40.fullmatch(str(capture.get("head", "")))
            or not HEX40.fullmatch(str(capture.get("tree", ""))) or tree.get("sha") != capture["tree"]
            or not isinstance(capture.get("files"), list) or not 0 < len(capture["files"]) <= MAX_FILES
            or not isinstance(tree.get("tree"), list) or len(tree["tree"]) > MAX_FILES * 2
            or tree.get("truncated", False)):
        _fail("SOURCE_CAPTURE_SCHEMA")
    declared = {}
    for entry in capture["files"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "git_blob", "sha256"}
                or not HEX40.fullmatch(str(entry["git_blob"])) or not HEX64.fullmatch(str(entry["sha256"]))):
            _fail("SOURCE_FILE_SCHEMA")
        name = _relative(entry["path"]).as_posix()
        if name in declared or name in {"source_capture.json", "source_tree.json"}:
            _fail("SOURCE_DUPLICATE_PATH")
        declared[name] = entry
    blobs, seen = {}, set()
    for entry in tree["tree"]:
        if not isinstance(entry, dict):
            _fail("SOURCE_TREE_SCHEMA")
        name = _relative(entry.get("path")).as_posix()
        if name in seen or not HEX40.fullmatch(str(entry.get("sha", ""))):
            _fail("SOURCE_TREE_DUPLICATE_OR_SHA")
        seen.add(name)
        if entry.get("type") == "blob" and entry.get("mode") in {"100644", "100755"}:
            blobs[name] = entry["sha"]
        elif entry.get("type") != "tree" or entry.get("mode") != "040000":
            _fail("SOURCE_TREE_LINK_OR_SUBMODULE")
    if set(blobs) != set(declared):
        _fail("SOURCE_TREE_CAPTURE_SET_MISMATCH")
    actual = _tree(root, budget)
    extra = set(actual) - set(declared) - {"source_capture.json", "source_tree.json"}
    if any(not ("__pycache__" in PurePosixPath(p).parts and p.endswith(".pyc")) for p in extra):
        _fail("SOURCE_UNDECLARED_FILES")
    if not set(declared).issubset(actual):
        _fail("SOURCE_MISSING_FILES")
    for name, entry in declared.items():
        raw = budget.read(root / Path(*PurePosixPath(name).parts))
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if blob != entry["git_blob"] or blob != blobs[name] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            _fail("SOURCE_BYTES_MISMATCH")
    return {"source_root": str(root), "declared_head": capture["head"], "declared_tree": capture["tree"],
            "file_count": len(declared), "source_capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
            "source_tree_sha256": hashlib.sha256(tree_bytes).hexdigest(),
            "files_digest": core.digest(sorted(declared.values(), key=lambda x: x["path"])),
            "scope": "LOCAL_FILE_GIT_BLOB_AND_SHA256_CONSISTENCY",
            "git_directory_tree_authentication": "NOT_VERIFIED", "source_origin_authenticity": "NOT_VERIFIED"}


def _controller_pin():
    from . import closed_loop
    budget = _Budget()
    paths = {"controller": Path(__file__), "core": Path(core.__file__),
             "intake_auditor": Path(audit_intake_bundle.__file__),
             "executed_journal_checker": Path(closed_loop.__file__),
             # The running process owns this entry, which is commonly a Linux
             # toolchain symlink. Pin the physical binary and original invocation;
             # caller-provided workspace/source/evidence paths remain strict.
             "interpreter": Path(sys.executable).resolve(strict=True)}
    return {"files": {name: {"path": str(_path(path)), "sha256": hashlib.sha256(budget.read(path)).hexdigest()}
                      for name, path in paths.items()}, "interpreter_invocation": sys.executable, "python_version": sys.version,
            "implementation": sys.implementation.name}


def _sidecars(ledger):
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = _physical(_path(str(ledger) + suffix))
        if sidecar.exists() and (suffix != "-journal" or sidecar.stat().st_size):
            _fail("SQLITE_SIDECAR_REFUSED")


@contextlib.contextmanager
def _connection(workspace, write=False, create=False):
    root = _path(workspace)
    ledger = root / "ledger.sqlite3"
    with _LOCK:
        _path(ledger)
        _sidecars(ledger)
        if create:
            _physical(root).mkdir(parents=True, exist_ok=True)
        if not create and not _physical(ledger).is_file():
            _fail("LEDGER_MISSING")
        if _physical(ledger).is_file():
            with _physical(ledger).open("rb") as stream:
                header = stream.read(100)
            if len(header) >= 20 and (header[18] == 2 or header[19] == 2):
                _fail("SQLITE_WAL_MODE_REFUSED")
        if write:
            conn = sqlite3.connect(str(_physical(ledger)), timeout=30, isolation_level=None)
        else:
            uri = "file:" + quote(str(_physical(ledger)), safe="/:") + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
        try:
            conn.execute("PRAGMA trusted_schema=OFF")
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
                _fail("SQLITE_WAL_MODE_REFUSED")
            conn.execute("PRAGMA recursive_triggers=ON")
            conn.execute("PRAGMA synchronous=FULL" if write else "PRAGMA query_only=ON")
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_FILE)
            deadline, ticks = time.monotonic() + MAX_SECONDS, [0]
            def progress():
                ticks[0] += 1
                return int(ticks[0] > 100_000 or time.monotonic() > deadline)
            conn.set_progress_handler(progress, 1000)
            if write:
                if create:
                    conn.execute("BEGIN IMMEDIATE")
                    _initialize(conn)
                    conn.commit()
                else:
                    _schema_check(conn)
                conn.set_authorizer(_write_authorizer)
            if not write:
                conn.execute("BEGIN")
            yield conn
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()


def _initialize(conn):
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'agent_audit_%'").fetchone():
        _schema_check(conn)
        return
    for short, columns in _TABLES.items():
        table = "agent_audit_" + short
        conn.execute("CREATE TABLE " + table + " (" + columns + ")")
        conditions = [key + "=NEW." + key for key in _KEYS[short]]
        if short == "tasks":
            conditions += ["(session_id=NEW.session_id AND kind=NEW.kind)", "(session_id=NEW.session_id AND ordinal=NEW.ordinal)"]
        elif short == "events":
            conditions += ["(task_id=NEW.task_id AND phase=NEW.phase)", "(task_id=NEW.task_id AND sequence=NEW.sequence)"]
        for operation in ("update", "delete", "replace"):
            when = (" WHEN EXISTS(SELECT 1 FROM " + table + " WHERE " + " OR ".join(conditions) + ")"
                    if operation == "replace" else "")
            conn.execute("CREATE TRIGGER " + table + "_no_" + operation + " BEFORE "
                         + ("INSERT" if operation == "replace" else operation.upper()) + " ON " + table + when
                         + " BEGIN SELECT RAISE(ABORT,'agent audit append only'); END")


def _schema_check(conn):
    # SQLite's own stored representation of the fixed declarations is the
    # reference. Guard names alone would accept no-op or side-effect triggers.
    reference = sqlite3.connect(":memory:")
    try:
        _initialize(reference)
        query = ("SELECT name,type,tbl_name,sql FROM sqlite_master "
                 "WHERE name LIKE 'agent_audit_%' OR tbl_name LIKE 'agent_audit_%' ORDER BY name")
        expected = reference.execute(query).fetchall()
    finally:
        reference.close()
    count, largest = conn.execute(
        "SELECT count(*),coalesce(max(length(CAST(sql AS BLOB))),0) FROM sqlite_master "
        "WHERE name LIKE 'agent_audit_%' OR tbl_name LIKE 'agent_audit_%'").fetchone()
    if count != len(expected) or largest > MAX_RECORD:
        _fail("AUDIT_SCHEMA_OR_EXTRA_TRIGGER_MISMATCH")
    if conn.execute(query).fetchall() != expected:
        _fail("AUDIT_SCHEMA_DEFINITION_MISMATCH")


def _write_authorizer(action, name, column, database, trigger):
    own = {"agent_audit_" + short for short in _TABLES}
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
        if action != sqlite3.SQLITE_INSERT or name not in own or trigger is not None:
            return sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TRIGGER,
                  sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_VIEW,
                  sqlite3.SQLITE_CREATE_VTABLE, sqlite3.SQLITE_DROP_TABLE,
                  sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_INDEX,
                  sqlite3.SQLITE_DROP_VIEW, sqlite3.SQLITE_DROP_VTABLE,
                  sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and str(column).lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _insert(conn, short, columns, value):
    raw = _encoded(value)
    if len(raw) > MAX_RECORD:
        _fail("RECORD_SIZE_LIMIT")
    fields = list(columns) + ["payload", "checksum"]
    conn.execute("INSERT INTO agent_audit_" + short + " (" + ",".join(fields) + ") VALUES ("
                 + ",".join("?" for _ in fields) + ")", [*columns.values(), raw.decode("utf-8"), core.digest(value)])


def _rows(conn, short, session_id):
    cursor = conn.execute("SELECT * FROM agent_audit_" + short + " WHERE session_id=?", (session_id,))
    columns = [d[0] for d in cursor.description]
    result, total = [], 0
    for raw in cursor:
        total += sum(len(v) for v in raw if isinstance(v, (str, bytes)))
        if len(result) >= MAX_ROWS or total > MAX_TOTAL:
            _fail("ROW_OR_BYTE_LIMIT")
        row = dict(zip(columns, raw))
        parsed = _parse(row["payload"])
        if not isinstance(parsed, dict) or core.canon(parsed) != row["payload"] or core.digest(parsed) != row["checksum"]:
            _fail("CANONICAL_HASH_MISMATCH")
        for key, value in row.items():
            if key not in {"payload", "checksum", "event_id"} and parsed.get(key) != value:
                _fail("ROW_IDENTITY_MISMATCH")
        result.append((row, parsed))
    return result


def _task_id(session_id, kind):
    return "V47AT-" + core.digest([session_id, kind])[:32]


def _event(conn, session, task, phase, previous=None, **fields):
    value = {"schema": "V47-LOCAL-AGENT-AUDIT-EVENT-1", "session_id": session["session_id"],
             "task_id": task["task_id"], "kind": task["kind"], "phase": phase, "sequence": PHASES.index(phase),
             "previous_checksum": previous, "source_digest": core.digest(session["source_pin"]),
             "controller_digest": core.digest(session["controller_pin"]),
             "actor": session["actors"]["executor"], "attempt": 1, **fields}
    _insert(conn, "events", {k: value[k] for k in ("session_id", "task_id", "phase", "sequence")}, value)
    return core.digest(value)


def _tasks(session):
    sid = session["session_id"]
    return [{"schema": "V47-LOCAL-AGENT-AUDIT-TASK-1", "session_id": sid, "task_id": _task_id(sid, kind),
             "kind": kind, "ordinal": i, "dependencies": [_task_id(sid, k) for k in DEPENDENCIES[kind]],
             "source_digest": core.digest(session["source_pin"]), "controller_digest": core.digest(session["controller_pin"]),
             "author": session["actors"]["developer"], "proposer": session["actors"]["orchestrator"],
             "executor": session["actors"]["executor"]} for i, kind in enumerate(KINDS)]


def _authorization(session, task):
    return {"scope": "FIXED_LOCAL_READ_ONLY_AUDIT", "actor": session["actors"]["executor"],
            "session_id": session["session_id"], "task_id": task["task_id"], "action": task["kind"],
            "source_digest": task["source_digest"], "controller_digest": task["controller_digest"],
            "dependencies": task["dependencies"], "authority": "SUPPLIED_LOCAL_ROLE_CLAIM_NOT_AUTHENTICATED"}


def _validate_actors(actors):
    if (not isinstance(actors, dict) or set(actors) != ROLES
            or any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in actors.values())
            or actors["reviewer"] in [v for k, v in actors.items() if k != "reviewer"]):
        _fail("ACTOR_BINDING_INVALID_OR_SELF_REVIEW")


def _validate(conn, workspace, session_id):
    _schema_check(conn)
    sessions = _rows(conn, "sessions", session_id)
    if len(sessions) != 1:
        _fail("SESSION_MISSING_OR_DUPLICATE")
    session = sessions[0][1]
    if session_id != "V47AS-" + core.digest({k: v for k, v in session.items() if k != "session_id"})[:32]:
        _fail("SESSION_IDENTITY_MISMATCH")
    _validate_actors(session.get("actors"))
    if session.get("schema") != "V47-LOCAL-AGENT-AUDIT-SESSION-1":
        _fail("SESSION_SCHEMA")
    expected = _tasks(session)
    if sorted((p for _, p in _rows(conn, "tasks", session_id)), key=lambda t: t["ordinal"]) != expected:
        _fail("FIXED_TASK_BINDING_MISMATCH")
    tasks = {t["task_id"]: {**t, "state": "PLANNED", "outcome": None, "result": {}} for t in expected}
    groups = {tid: [] for tid in tasks}
    for row, event in _rows(conn, "events", session_id):
        if event.get("task_id") not in tasks:
            _fail("EVENT_TASK_IDENTITY_MISMATCH")
        groups[event["task_id"]].append((row, event))
    evidence = {}
    for row, ev in _rows(conn, "evidence", session_id):
        tid = ev.get("task_id")
        if tid not in tasks or ev.get("evidence_id") in evidence:
            _fail("EVIDENCE_TASK_BINDING")
        canonical = f"audit_evidence/{session_id}/{tid}.json"
        if (ev.get("evidence_path") != canonical or ev.get("kind") != tasks[tid]["kind"]
                or ev.get("actor") != session["actors"]["executor"] or ev.get("attempt") != 1
                or ev.get("source_digest") != core.digest(session["source_pin"])
                or ev.get("controller_digest") != core.digest(session["controller_pin"])):
            _fail("EVIDENCE_IDENTITY_MISMATCH")
        raw = _Budget().read(_path(workspace) / Path(*_relative(canonical).parts), MAX_RECORD)
        envelope = _parse(raw)
        if (not isinstance(envelope, dict) or raw != _encoded(envelope)
                or hashlib.sha256(raw).hexdigest() != ev.get("file_sha256")
                or envelope != {k: v for k, v in ev.items() if k not in {"file_sha256", "evidence_path"}}
                or ev.get("evidence_id") != "V47AE-" + core.digest({k: v for k, v in envelope.items() if k != "evidence_id"})[:32]
                or ev.get("result_digest") != core.digest(ev.get("result")) or ev.get("outcome") not in OUTCOMES
                or type(ev.get("capture_complete")) is not bool or not ev["capture_complete"] and ev["outcome"] != "BLOCKED"):
            _fail("EVIDENCE_BYTES_OR_RESULT_MISMATCH")
        evidence[ev["evidence_id"]] = ev
    for tid, entries in groups.items():
        entries.sort(key=lambda x: x[0]["event_id"])
        phases = [v.get("phase") for _, v in entries]
        if phases != list(PHASES[:len(phases)]) or not 3 <= len(phases) <= len(PHASES):
            _fail("INVALID_PHASE_ORDER")
        previous, task = None, tasks[tid]
        for index, (row, event) in enumerate(entries):
            if (event.get("schema") != "V47-LOCAL-AGENT-AUDIT-EVENT-1" or event.get("kind") != task["kind"]
                    or event.get("sequence") != index or event.get("previous_checksum") != previous
                    or event.get("attempt") != 1 or event.get("actor") != session["actors"]["executor"]
                    or event.get("source_digest") != task["source_digest"] or event.get("controller_digest") != task["controller_digest"]):
                _fail("EVENT_CHAIN_OR_ACTOR_MISMATCH")
            if index == 2 and event.get("authorization") != _authorization(session, task):
                _fail("LOCAL_AUTHORIZATION_BINDING")
            if index == 3:
                if event.get("authorization_digest") != core.digest(_authorization(session, task)):
                    _fail("EXECUTION_AUTHORIZATION_BINDING")
                deps = event.get("dependency_evidence")
                if not isinstance(deps, dict) or set(deps) != set(task["dependencies"]):
                    _fail("DEPENDENCY_BINDING")
                for dep, checksum in deps.items():
                    found = next((e for e in evidence.values() if e["task_id"] == dep), None)
                    if found is None or checksum != core.digest(found):
                        _fail("DEPENDENCY_EVIDENCE_MISMATCH")
            if index >= 4:
                ev = evidence.get(event.get("evidence_id"))
                if ev is None or ev["task_id"] != tid or event.get("evidence_digest") != core.digest(ev) or event.get("outcome") != ev["outcome"]:
                    _fail("EVENT_EVIDENCE_BINDING")
            previous = row["checksum"]
        task["last_checksum"] = previous
        if len(entries) == 4:
            task["state"] = "UNKNOWN_RUNNING"
        elif len(entries) not in {3, 7}:
            _fail("PARTIAL_TERMINAL_TRANSACTION")
        elif len(entries) == 7:
            ev = evidence[entries[-1][1]["evidence_id"]]
            task.update({k: ev[k] for k in ("outcome", "result", "evidence_id", "evidence_path", "capture_complete")})
            task["state"] = "FINISHED"
    for ev in evidence.values():
        if tasks[ev["task_id"]]["state"] != "FINISHED":
            _fail("ORPHAN_EVIDENCE")
    facts, known = [], {}
    for row, fact in sorted(_rows(conn, "facts", session_id), key=lambda x: x[1].get("ordinal", -1)):
        fid, ev = fact.get("fact_id"), evidence.get(fact.get("evidence_id"))
        if (fid != "V47AF-" + core.digest({k: v for k, v in fact.items() if k != "fact_id"})[:32] or ev is None
                or fact.get("evidence_digest") != core.digest(ev) or fact.get("ordinal") != len(facts)
                or fact.get("status") not in {"HYPOTHESIS", "REFUTED", "VERIFIED_LOCAL"}
                or fact.get("actor") not in session["actors"].values()):
            _fail("FACT_BINDING_MISMATCH")
        if fact["status"] == "VERIFIED_LOCAL":
            if (fact.get("origin") != "DETERMINISTIC_HANDLER" or ev["outcome"] != "LOCAL_CHECK_OK" or not ev["capture_complete"]
                    or fact["actor"] != session["actors"]["executor"] or fact.get("text") != "Local deterministic check: " + ev["kind"]
                    or fact.get("refutes") is not None):
                _fail("FACT_LOCAL_VERIFICATION_INVALID")
        elif fact.get("origin") != "ACTOR_CLAIM":
            _fail("FACT_CLAIM_ORIGIN_INVALID")
        if (fact["status"] == "REFUTED" and fact.get("refutes") not in known
                or fact["status"] != "REFUTED" and fact.get("refutes") is not None):
            _fail("FACT_REFUTATION_BINDING")
        known[fid] = fact
        facts.append(fact)
    aggregate = core.digest({"session": session, "tasks": [tasks[t["task_id"]] for t in expected]})
    reviews = []
    for _, review in _rows(conn, "reviews", session_id):
        if (review.get("review_id") != "V47AR-" + core.digest({k: v for k, v in review.items() if k != "review_id"})[:32]
                or review.get("actor") != session["actors"]["reviewer"] or review.get("result_digest") != aggregate
                or review.get("review_authority") != "NOT_VERIFIED" or review.get("formal_A") != 0
                or review.get("role_identity_authenticated") is not False
                or review.get("note_sha256") != hashlib.sha256(review.get("note", "").encode("utf-8")).hexdigest()):
            _fail("REVIEW_BINDING_MISMATCH")
        reviews.append(review)
    return session, list(tasks.values()), evidence, facts, reviews, aggregate


def create_session(workspace, *, key, actors, source_root):
    _validate_actors(actors)
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", key):
        _fail("SESSION_KEY_INVALID")
    root = _path(workspace)
    session = {"schema": "V47-LOCAL-AGENT-AUDIT-SESSION-1", "session_key": key, "actors": dict(actors),
               "source_pin": _source_pin(source_root), "controller_pin": _controller_pin(),
               "role_identity_authenticated": False, "formal_A": 0, "decision": "NO_EDGE", "DEPLOYMENT_PASS": "NOT_VERIFIED"}
    session["session_id"] = "V47AS-" + core.digest(session)[:32]
    with _connection(root, write=True, create=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _initialize(conn)
        existing = conn.execute("SELECT session_id FROM agent_audit_sessions WHERE session_key=?", (key,)).fetchone()
        if existing:
            if _validate(conn, root, existing[0])[0] != session:
                _fail("IDEMPOTENCY_BINDING_CONFLICT")
        else:
            _insert(conn, "sessions", {k: session[k] for k in ("session_id", "session_key")}, session)
            for task in _tasks(session):
                _insert(conn, "tasks", {k: task[k] for k in ("task_id", "session_id", "kind", "ordinal")}, task)
                previous = None
                for phase in PHASES[:3]:
                    previous = _event(conn, session, task, phase, previous,
                                      **({"authorization": _authorization(session, task)} if phase == "AUTHORIZE" else {}))
        conn.commit()
    return {**session, "tasks": _tasks(session)}


def _append_fact(conn, session, actor, text, ev, status, facts, refutes=None, origin="ACTOR_CLAIM"):
    fact = {"schema": "V47-LOCAL-AGENT-AUDIT-FACT-1", "session_id": session["session_id"], "actor": actor,
            "text": text, "status": status, "refutes": refutes, "evidence_id": ev["evidence_id"],
            "evidence_digest": core.digest(ev), "origin": origin, "ordinal": len(facts)}
    fact["fact_id"] = "V47AF-" + core.digest(fact)[:32]
    _insert(conn, "facts", {k: fact[k] for k in ("fact_id", "session_id", "evidence_id")}, fact)
    return fact


def _save_result(workspace, session, task, result):
    complete = True
    try:
        raw = _encoded(result)
        if len(raw) > 100_000:
            complete = False
            result = {"outcome": "BLOCKED", "reason": "RESULT_CAPTURE_SIZE_LIMIT", "original_serialized_bytes": len(raw),
                      "original_sha256": hashlib.sha256(raw).hexdigest()}
        elif not isinstance(result, dict) or result.get("outcome") not in OUTCOMES:
            _fail("HANDLER_RESULT_SCHEMA")
        elif result.get("capture_complete", True) is not True:
            complete = False
            result = {**result, "outcome": "BLOCKED"}
    except GateError:
        complete = False
        result = {"outcome": "BLOCKED", "reason": "HANDLER_RESULT_NOT_CAPTURABLE"}
    envelope = {"schema": "V47-LOCAL-AGENT-AUDIT-EVIDENCE-1", "session_id": session["session_id"], "task_id": task["task_id"],
                "kind": task["kind"], "attempt": 1, "actor": session["actors"]["executor"], "source_digest": task["source_digest"],
                "controller_digest": task["controller_digest"], "outcome": result["outcome"], "capture_complete": complete,
                "result": result, "result_digest": core.digest(result)}
    envelope["evidence_id"] = "V47AE-" + core.digest(envelope)[:32]
    relative = f"audit_evidence/{session['session_id']}/{task['task_id']}.json"
    path = _path(workspace) / Path(*_relative(relative).parts)
    _path(path)
    _physical(path.parent).mkdir(parents=True, exist_ok=True)
    _path(path)
    data = _encoded(envelope)
    if len(data) > MAX_RECORD:
        _fail("EVIDENCE_SIZE_LIMIT")
    # A partial/orphan file after a crash is retained; it is never overwritten.
    with _physical(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {**envelope, "evidence_path": relative, "file_sha256": hashlib.sha256(data).hexdigest()}


def run_session(workspace, session_id, *, actor):
    root = _path(workspace)
    while True:
        with _connection(root, write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            session, tasks, evidence, facts, _, _ = _validate(conn, root, session_id)
            if actor != session["actors"]["executor"]:
                _fail("EXECUTOR_BINDING_MISMATCH")
            if any(t["state"] == "UNKNOWN_RUNNING" for t in tasks):
                break
            task = next((t for t in tasks if t["state"] == "PLANNED"), None)
            if task is None:
                break
            dependencies = {tid: next(e for e in evidence.values() if e["task_id"] == tid) for tid in task["dependencies"]}
            previous = _event(conn, session, task, "EXECUTE_STARTED", task["last_checksum"],
                              authorization_digest=core.digest(_authorization(session, task)),
                              dependency_evidence={tid: core.digest(ev) for tid, ev in dependencies.items()})
            conn.commit()  # Durable once-only claim before calling any handler.
        try:
            if _controller_pin() != session["controller_pin"]:
                result = {"outcome": "FAILED", "reason": "SOURCE_CONTROLLER_OR_INTERPRETER_DRIFT"}
            elif _source_pin(session["source_pin"]["source_root"]) != session["source_pin"]:
                result = {"outcome": "FAILED", "reason": "SOURCE_CAPTURE_DRIFT"}
            elif any(e["outcome"] != "LOCAL_CHECK_OK" for e in dependencies.values()):
                result = {"outcome": "BLOCKED", "reason": "DEPENDENCY_NOT_LOCALLY_VERIFIED"}
            else:
                started = time.monotonic()
                result = _perform(task["kind"], root, session)
                if time.monotonic() - started > MAX_SECONDS:
                    result = {"outcome": "BLOCKED", "reason": "COOPERATIVE_TIME_LIMIT", "capture_complete": False}
        except (GateError, OSError, sqlite3.DatabaseError, ValueError) as exc:
            result = {"outcome": "FAILED", "reason": "SOURCE_OR_LOCAL_CHECK_REFUSED", "error": str(exc)[:2000]}
        # KeyboardInterrupt/SystemExit propagate, retaining the committed claim.
        with _connection(root, write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current, now, _, current_facts, _, _ = _validate(conn, root, session_id)
            claimed = next(t for t in now if t["task_id"] == task["task_id"])
            if claimed["state"] != "UNKNOWN_RUNNING" or claimed["last_checksum"] != previous:
                _fail("EXECUTION_CLAIM_CHANGED")
            ev = _save_result(root, current, task, result)
            _insert(conn, "evidence", {k: ev[k] for k in ("evidence_id", "session_id", "task_id")}, ev)
            for phase in PHASES[4:]:
                previous = _event(conn, current, task, phase, previous, evidence_id=ev["evidence_id"],
                                  evidence_digest=core.digest(ev), outcome=ev["outcome"])
            if ev["outcome"] == "LOCAL_CHECK_OK" and ev["capture_complete"]:
                _append_fact(conn, current, actor, "Local deterministic check: " + task["kind"], ev,
                             "VERIFIED_LOCAL", current_facts, origin="DETERMINISTIC_HANDLER")
            _validate(conn, root, session_id)
            conn.commit()
    return report_session(root, session_id)


def _perform(kind, workspace, session):
    if kind not in KINDS:
        _fail("UNKNOWN_FIXED_HANDLER")
    if kind == "source_integrity":
        return {"outcome": "LOCAL_CHECK_OK", "source": _source_pin(session["source_pin"]["source_root"]),
                "reason": "LOCAL_CAPTURE_BLOBS_AND_BYTES_MATCH_NOT_OFFICIAL_ORIGIN"}
    if kind == "container_readiness":
        available = {name: shutil.which(name) is not None for name in ("docker", "podman")}
        return {"outcome": "BLOCKED", "reason": ("DOCKER_PODMAN_CLI_UNAVAILABLE" if not any(available.values())
                else "DOCKER_PODMAN_ENGINE_NOT_VERIFIED_NO_PROCESS_LAUNCHED"), "cli_present": available,
                "engine": "NOT_VERIFIED", "deployment": "NOT_VERIFIED"}
    if kind == "intake_integrity":
        return _intake(workspace)
    with _connection(workspace) as conn:
        if kind == "journal_integrity":
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operational_events'").fetchone():
                return {"outcome": "BLOCKED", "reason": "OPERATIONAL_JOURNAL_ABSENT", "event_count": 0}
            selected = ("length(CAST(coalesce(tick_id,'') AS BLOB))+"
                        "length(CAST(coalesce(event_type,'') AS BLOB))+"
                        "length(CAST(coalesce(lottery,'') AS BLOB))+"
                        "length(CAST(coalesce(event_payload,'') AS BLOB))+"
                        "length(CAST(coalesce(event_sha256,'') AS BLOB))")
            count, total, largest = conn.execute("SELECT count(*),coalesce(sum(" + selected + "),0),"
                                                "coalesce(max(" + selected + "),0) FROM operational_events").fetchone()
            if count > MAX_ROWS or total > MAX_TOTAL or largest > MAX_FILE:
                return {"outcome": "BLOCKED", "reason": "JOURNAL_ROW_OR_BYTE_LIMIT", "capture_complete": False}
            from .closed_loop import _operational_check_journal
            unfinished, ticks = _operational_check_journal(conn)
            return {"outcome": "LOCAL_CHECK_OK", "event_count": count, "tick_count": ticks, "unfinished_ticks": unfinished,
                    "scope": "STORED_LOCAL_EVENT_HASHES_AND_ORDER_ONLY"}
        inventory, total, started = {}, 0, time.monotonic()
        for table in ("run_manifests", "run_snapshots", "predictions", "game_runs", "game_predictions"):
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                inventory[table] = {"rows": 0, "present": False}
                continue
            cursor = conn.execute('SELECT * FROM "' + table + '"')
            columns, rows = [d[0] for d in cursor.description], []
            for row in cursor:
                encoded = _encoded([({"blob_hex": v.hex()} if isinstance(v, bytes) else v) for v in row])
                total += len(encoded)
                if len(rows) >= MAX_ROWS or total > MAX_TOTAL or len(encoded) > MAX_FILE or time.monotonic() - started > MAX_SECONDS:
                    return {"outcome": "BLOCKED", "reason": "FROZEN_INVENTORY_LIMIT", "capture_complete": False}
                rows.append(hashlib.sha256(encoded).hexdigest())
            inventory[table] = {"rows": len(rows), "present": True, "columns": columns, "stored_rows_digest": core.digest(sorted(rows))}
        return {"outcome": "LOCAL_CHECK_OK", "inventory": inventory, "scope": "STORED_BYTE_INVENTORY_ONLY_NO_MODEL_REPLAY_OR_FUTURE_EDGE"}


def _intake(workspace):
    with _connection(workspace) as conn:
        latest = conn.execute("SELECT tick_id FROM operational_events WHERE event_type='STARTED' ORDER BY event_id DESC LIMIT 1").fetchone()
    if not latest:
        return {"outcome": "BLOCKED", "reason": "LATEST_INTAKE_ABSENT"}
    if not isinstance(latest[0], str) or not re.fullmatch(r"V47T-[0-9a-f]{32}", latest[0]):
        _fail("INTAKE_TICK_ID_INVALID")
    root, receipts, budget = _path(workspace) / "operational_intake" / latest[0], {}, _Budget()
    for game in ("SSQ", "DLT"):
        bundle = _path(root / game)
        if not _physical(bundle / "intake.json").is_file():
            receipts[game] = {"status": "MISSING"}
            continue
        for path in _tree(bundle, budget).values():
            budget.read(path)
        manifest = _parse(budget.read(bundle / "intake.json"), MAX_FILE)
        if not isinstance(manifest, dict):
            _fail("INTAKE_MANIFEST_SCHEMA")
        def bounded_read(path):
            value = os.fspath(path)
            # Only internally produced extended drive paths are normalized;
            # all resulting components still pass the strong reparse guard.
            if os.name == "nt" and value.startswith("\\\\?\\") and not value.startswith("\\\\?\\UNC\\"):
                value = value[4:]
            logical = _path(value)
            auditor = _path(audit_intake_bundle.__file__)
            if logical != auditor and not logical.is_relative_to(bundle):
                _fail("DELEGATED_READ_OUTSIDE_BUNDLE")
            return budget.read(logical)
        receipts[game] = audit_intake_bundle.audit_bundle(bundle, read_bytes=bounded_read, check=budget.visit)
        budget.check()
    outcome = "LOCAL_CHECK_OK" if all(r.get("status") == "PASS" for r in receipts.values()) else "FAILED"
    if all(r.get("status") == "MISSING" for r in receipts.values()):
        outcome = "BLOCKED"
    return {"outcome": outcome, "tick_id": latest[0], "receipts": receipts,
            "scope": "LATEST_LOCAL_TICK_BUNDLE_BYTE_INTEGRITY_ONLY"}


def report_session(workspace, session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r"V47AS-[0-9a-f]{32}", session_id):
        _fail("SESSION_ID_INVALID")
    with _connection(workspace) as conn:
        session, tasks, evidence, facts, reviews, aggregate = _validate(conn, workspace, session_id)
    return {"schema": "V47-LOCAL-AGENT-AUDIT-REPORT-1", "session_id": session_id, "session_key": session["session_key"],
            "actors": session["actors"], "tasks": tasks, "facts": facts, "reviews": reviews, "result_digest": aggregate,
            "role_identity_authenticated": False, "review_authority": "NOT_VERIFIED", "formal_A": 0,
            "decision": "NO_EDGE", "DEPLOYMENT_PASS": "NOT_VERIFIED",
            "local_integrity_limits": "NOT_WORM_PRIVILEGED_REWRITE_AND_TAIL_DELETION_NOT_EXTERNALLY_EXCLUDED",
            "execution_limits": "COOPERATIVE_BOUNDS_NOT_PROCESS_ISOLATION"}


def remember(workspace, session_id, *, actor, text, evidence_id, status, refutes=None):
    if status not in {"HYPOTHESIS", "REFUTED"}:
        _fail("MEMORY_CANNOT_SELF_VERIFY")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        _fail("MEMORY_TEXT_INVALID")
    with _connection(workspace, write=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        session, _, evidence, facts, _, _ = _validate(conn, workspace, session_id)
        if actor not in session["actors"].values() or evidence_id not in evidence:
            _fail("MEMORY_ACTOR_OR_SESSION_EVIDENCE_INVALID")
        if status == "REFUTED" and refutes not in {f["fact_id"] for f in facts} or status == "HYPOTHESIS" and refutes is not None:
            _fail("REFUTATION_TARGET_INVALID")
        result = _append_fact(conn, session, actor, text, evidence[evidence_id], status, facts, refutes)
        _validate(conn, workspace, session_id)
        conn.commit()
    return result


def record_review(workspace, session_id, *, actor, result_digest, note):
    if not isinstance(note, str) or not note.strip() or len(note) > 8000:
        _fail("REVIEW_NOTE_INVALID")
    with _connection(workspace, write=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        session, tasks, _, _, _, aggregate = _validate(conn, workspace, session_id)
        if actor != session["actors"]["reviewer"] or result_digest != aggregate or any(t["state"] != "FINISHED" for t in tasks):
            _fail("REVIEW_ACTOR_OR_EXACT_RESULT_INVALID")
        review = {"schema": "V47-LOCAL-AGENT-AUDIT-REVIEW-CLAIM-1", "session_id": session_id, "actor": actor,
                  "result_digest": aggregate, "note": note, "note_sha256": hashlib.sha256(note.encode("utf-8")).hexdigest(),
                  "review_authority": "NOT_VERIFIED", "role_identity_authenticated": False, "formal_A": 0,
                  "decision": "NO_EDGE", "DEPLOYMENT_PASS": "NOT_VERIFIED"}
        review["review_id"] = "V47AR-" + core.digest(review)[:32]
        if not conn.execute("SELECT 1 FROM agent_audit_reviews WHERE review_id=?", (review["review_id"],)).fetchone():
            _insert(conn, "reviews", {k: review[k] for k in ("review_id", "session_id")}, review)
        conn.commit()
    return review


def load_request(path):
    request = _parse(_Budget().read(_path(path), MAX_REQUEST), MAX_REQUEST)
    if not isinstance(request, dict):
        _fail("REQUEST_NOT_OBJECT")
    return request


def dispatch(workspace, request, *, source_root=None):
    schemas = {"plan": ({"operation", "key", "actors"}, set()), "run": ({"operation", "session_id", "actor"}, set()),
               "report": ({"operation", "session_id"}, set()),
               "review": ({"operation", "session_id", "actor", "result_digest", "note"}, set()),
               "remember": ({"operation", "session_id", "actor", "text", "evidence_id", "status"}, {"refutes"})}
    if not isinstance(request, dict) or not isinstance(request.get("operation"), str) or request["operation"] not in schemas:
        _fail("UNKNOWN_REQUEST_OPERATION")
    required, optional = schemas[request["operation"]]
    if not required.issubset(request) or set(request) - required - optional or len(_encoded(request)) > MAX_REQUEST:
        _fail("REQUEST_SCHEMA_OR_SIZE_INVALID")
    operation, args = request["operation"], {k: v for k, v in request.items() if k != "operation"}
    if operation == "plan":
        return create_session(workspace, source_root=source_root or Path(__file__).parents[2], **args)
    if operation == "report":
        return report_session(workspace, **args)
    if operation == "run":
        return run_session(workspace, **args)
    if operation == "review":
        return record_review(workspace, **args)
    return remember(workspace, **args)
