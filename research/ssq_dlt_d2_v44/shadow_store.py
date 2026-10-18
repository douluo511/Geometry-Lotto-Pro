"""Isolated append-only saved-byte archive; never a prediction or A ledger.

The caller must independently replay saved official bytes before importing.
This layer repeats content/row binding checks, but cannot prove publication
time, publisher authenticity or pre-draw eligibility. SQLite triggers protect
against accidental SQL changes, not a malicious owner replacing the DB file.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import time

from .scoring import AdmissionBlocked, validate_numbers


APPLICATION_ID = 0x47565344
SCHEMA_VERSION = 1
VERIFICATION_SCOPE = "SAVED_BYTES_RECONSTRUCTION_ONLY"
STATUS = dict(scope="SHADOW_ARCHIVE_ONLY", R2="BLOCKED", formal_A=0,
              decision="NO_EDGE", formal_training_eligibility="BLOCKED",
              repository_independence="FAIL", final_gate="FAIL")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CORE = ("game", "issue", "date", "front", "back", "available_at")
_TABLE_SQL = {
    "snapshots": """CREATE TABLE snapshots (
        snapshot_sha256 TEXT NOT NULL PRIMARY KEY, archive_sha256 TEXT NOT NULL,
        manifest_bytes BLOB NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope='SHADOW_ARCHIVE_ONLY'))""",
    "artifacts": """CREATE TABLE artifacts (
        snapshot_sha256 TEXT NOT NULL REFERENCES snapshots(snapshot_sha256),
        file TEXT NOT NULL, raw BLOB NOT NULL, sha256 TEXT NOT NULL,
        size INTEGER NOT NULL CHECK(size>=0),
        PRIMARY KEY(snapshot_sha256,file))""",
    "rows": """CREATE TABLE rows (
        snapshot_sha256 TEXT NOT NULL REFERENCES snapshots(snapshot_sha256),
        game TEXT NOT NULL CHECK(game IN ('SSQ','DLT')), issue TEXT NOT NULL,
        available_at TEXT CHECK(available_at IS NULL),
        payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(snapshot_sha256,game,issue))""",
}
_KEYS = {"snapshots": ("snapshot_sha256",),
         "artifacts": ("snapshot_sha256", "file"),
         "rows": ("snapshot_sha256", "game", "issue")}
_TRIGGER_SQL = {}
for _table, _keys in _KEYS.items():
    for _action in ("UPDATE", "DELETE"):
        _name = f"immutable_{_table}_{_action}"
        _TRIGGER_SQL[_name] = (f"CREATE TRIGGER {_name} BEFORE {_action} ON {_table} "
                              "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
    _name = f"no_replace_{_table}"
    _where = " AND ".join(f"{key}=NEW.{key}" for key in _keys)
    _TRIGGER_SQL[_name] = (f"CREATE TRIGGER {_name} BEFORE INSERT ON {_table} "
                          f"WHEN EXISTS (SELECT 1 FROM {_table} WHERE {_where}) "
                          "BEGIN SELECT RAISE(ABORT, 'DUPLICATE_KEY'); END")


class ShadowStoreError(AdmissionBlocked):
    """Archive admission or integrity failure; no automatic repair or fallback."""


def _require(condition, code):
    if not condition:
        raise ShadowStoreError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ShadowStoreError("INVALID_JSON_VALUE") from exc


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ShadowStoreError("NONFINITE_JSON_VALUE")))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ShadowStoreError("INVALID_JSON") from exc


def _digest(value):
    return _sha(_canonical(value).encode("utf-8"))


def _hash(value):
    _require(type(value) is str and _SHA.fullmatch(value), "INVALID_SHA256")
    return value


def _relative(value):
    _require(type(value) is str and value and "\\" not in value
             and not re.search(r'[<>:"|?*\x00-\x1f]', value), "UNSAFE_ARTIFACT_PATH")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and str(path) == value, "UNSAFE_ARTIFACT_PATH")
    for part in path.parts:
        _require(part not in (".", "..") and not part.endswith((".", " ")),
                 "UNSAFE_ARTIFACT_PATH")
        stem = part.split(".")[0].casefold()
        _require(stem not in {"con", "prn", "aux", "nul"}
                 and not re.fullmatch(r"(?:com|lpt)[1-9]", stem), "UNSAFE_ARTIFACT_PATH")
    return value


def _counts(value):
    _require(type(value) is dict and set(value) == {"SSQ", "DLT"}
             and all(type(n) is int and n >= 0 for n in value.values())
             and sum(value.values()) > 0, "INVALID_ROW_COUNTS")
    return dict(value)


def _draw(row):
    _require(type(row) is dict and all(key in row for key in _CORE), "MISSING_ROW_FIELDS")
    game, issue, day = row["game"], row["issue"], row["date"]
    _require(type(game) is str and game in ("SSQ", "DLT"), "UNKNOWN_GAME")
    pattern = r"20[0-9]{5}" if game == "SSQ" else r"[0-9]{5}"
    _require(type(issue) is str and re.fullmatch(pattern, issue), "INVALID_ISSUE")
    _require(type(day) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day),
             "INVALID_DRAW_DATE")
    try:
        parsed = date.fromisoformat(day)
    except ValueError as exc:
        raise ShadowStoreError("INVALID_DRAW_DATE") from exc
    _require((issue[:4] if game == "SSQ" else "20" + issue[:2]) == str(parsed.year)
             and 1 <= int(issue[-3:]) <= 366, "ISSUE_DATE_MISMATCH")
    for zone, count, maximum in (("front", 6 if game == "SSQ" else 5, 33 if game == "SSQ" else 35),
                                 ("back", 1 if game == "SSQ" else 2, 16 if game == "SSQ" else 12)):
        validate_numbers(row[zone], count, maximum)
        _require(row[zone] == sorted(row[zone]), "UNSORTED_DRAW_NUMBERS")
    _require(row["available_at"] is None, "AVAILABLE_AT_MUST_REMAIN_NULL")
    return game, issue


def _check_no_promotion(original):
    _require(original.get("formal_training_eligible", False) is False
             and original.get("historical_predraw_asof_proven", False) is False,
             "FORMAL_PROMOTION_REFUSED")
    _require(all(original.get(field) is None for field in
                 ("available_at", "available_at_upper_bound", "available_at_upper_bound_evidence",
                  "publisher_publication_at", "actual_draw_at", "training_cutoff_at",
                  "available_at_evidence")), "ARCHIVE_TIME_MUST_REMAIN_NULL")
    sources = original.get("sources", [])
    _require(type(sources) is list and all(type(source) is dict
             and all(source.get(field) is None for field in
                     ("available_at", "publisher_exact_at", "availability_evidence")) for source in sources),
             "SOURCE_AVAILABLE_AT_MUST_REMAIN_NULL")


def _validate(verified):
    """Copy and rebind incoming rows to exact history/mapping file bytes."""
    _require(type(verified) is dict, "VERIFIED_SNAPSHOT_REQUIRED")
    snapshot_hash, archive_hash = (_hash(verified.get(key)) for key in
                                   ("snapshot_sha256", "archive_sha256"))
    _require(verified.get("verification_scope") == VERIFICATION_SCOPE,
             "WRONG_VERIFICATION_SCOPE")
    raw_manifest = verified.get("manifest_bytes")
    _require(type(raw_manifest) is bytes and _sha(raw_manifest) == snapshot_hash,
             "MANIFEST_HASH_MISMATCH")
    manifest = _json(raw_manifest)
    _require(type(manifest) is dict, "INVALID_MANIFEST")
    table, files = manifest.get("file_table"), verified.get("files")
    _require(type(table) is list and bool(table) and type(files) is dict, "INVALID_FILE_TABLE")
    declared, aliases = {}, set()
    for entry in table:
        _require(type(entry) is dict and {"file", "sha256", "size"} <= set(entry),
                 "INVALID_FILE_TABLE")
        name = _relative(entry["file"])
        _require(name != "manifest.json" and name.casefold() not in aliases,
                 "DUPLICATE_OR_SELF_REFERENCING_ARTIFACT")
        aliases.add(name.casefold())
        raw = files.get(name)
        _require(type(raw) is bytes and type(entry["size"]) is int
                 and len(raw) == entry["size"] and _sha(raw) == _hash(entry["sha256"]),
                 "ARTIFACT_HASH_OR_SIZE_MISMATCH")
        declared[name] = raw
    _require(set(files) == set(declared), "MISSING_OR_EXTRA_ARTIFACTS")
    counts = _counts(verified.get("counts"))
    _require(counts == _counts(manifest.get("row_counts")), "ROW_COUNTS_MISMATCH")
    _require({"history_snapshot.json", "row_mapping.json"} <= set(files),
             "HISTORY_OR_MAPPING_MISSING")
    history, mapping = (_json(files[name]) for name in ("history_snapshot.json", "row_mapping.json"))
    _require(type(history) is dict and type(history.get("games")) is dict
             and set(history["games"]) == {"SSQ", "DLT"} and type(mapping) is dict
             and type(mapping.get("rows")) is list, "INVALID_HISTORY_OR_MAPPING")
    originals = {}
    for game, group in history["games"].items():
        _require(type(group) is dict and type(group.get("rows")) is list, "INVALID_HISTORY_ROWS")
        _require(len(group["rows"]) == counts[game], "HISTORY_ROW_COUNTS_MISMATCH")
        for original in group["rows"]:
            key = _draw(original)
            _require(key[0] == game and key not in originals, "DUPLICATE_HISTORY_IDENTITY")
            _check_no_promotion(original)
            originals[key] = original
    mapped = {}
    for item in mapping["rows"]:
        key = _draw(item)
        _require(key not in mapped and key in originals
                 and item.get("row_id") == ":".join(key), "MAPPING_IDENTITY_MISMATCH")
        _require(all(item[field] == originals[key][field] for field in _CORE),
                 "MAPPING_HISTORY_MISMATCH")
        matches = item.get("matches")
        _require(type(matches) is list and bool(matches), "MISSING_ROW_MATCHES")
        seen_matches = set()
        for match in matches:
            _require(type(match) is dict and set(match) ==
                     {"raw_id", "record_json_pointer", "record_position"}, "INVALID_ROW_MATCH")
            _hash(match["raw_id"])
            position = match["record_position"]
            _require(type(position) is int and position >= 0
                     and match["record_json_pointer"] ==
                     ("/result/" if key[0] == "SSQ" else "/value/list/") + str(position),
                     "INVALID_ROW_MATCH")
            encoded = _canonical(match)
            _require(encoded not in seen_matches, "DUPLICATE_ROW_MATCH")
            seen_matches.add(encoded)
        mapped[key] = item
    _require(set(mapped) == set(originals), "MISSING_OR_EXTRA_MAPPING_ROWS")
    rows = verified.get("rows")
    _require(type(rows) is list and len(rows) == sum(counts.values()), "MISSING_OR_EXTRA_ROWS")
    normalized, seen = [], set()
    for supplied in rows:
        # JSON round-trip also prevents caller mutation of metadata after validation.
        row = _json(_canonical(supplied))
        key = _draw(row)
        _require(key not in seen and key in originals, "DUPLICATE_OR_UNKNOWN_ROW")
        seen.add(key)
        _require(set(row) == {*_CORE, "original_row", "matches"}, "UNEXPECTED_ROW_FIELDS")
        _require(all(row[field] == originals[key][field] for field in _CORE)
                 and row["original_row"] == originals[key], "ORIGINAL_ROW_BINDING_MISMATCH")
        _require(row["matches"] == mapped[key]["matches"], "ROW_MATCH_BINDING_MISMATCH")
        normalized.append(row)
    normalized.sort(key=lambda row: (row["game"], row["issue"]))
    metadata = dict(snapshot_sha256=snapshot_hash, archive_sha256=archive_hash,
                    counts=counts, row_count=len(normalized), artifact_count=len(declared),
                    verification_scope=VERIFICATION_SCOPE, **STATUS)
    return raw_manifest, declared, normalized, metadata


def _sql_shape(value):
    return " ".join(value.split()).rstrip(";")


def _check_schema(db):
    _require(db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
             "FOREIGN_DATABASE_REFUSED")
    _require(db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
             "UNKNOWN_SHADOW_SCHEMA")
    actual = {(kind, name): _sql_shape(sql) for kind, name, sql in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','trigger','view')")}
    expected = {("table", name): _sql_shape(sql) for name, sql in _TABLE_SQL.items()}
    expected.update({("trigger", name): _sql_shape(sql) for name, sql in _TRIGGER_SQL.items()})
    _require(actual == expected, "SHADOW_SCHEMA_INTEGRITY_MISMATCH")


def _preflight(path):
    # Even mode=ro may create a WAL -shm file. Check the main header and
    # immutable main-file schema first, without journal recovery or sidecars.
    # Our atomic initializer publishes only a fully checkpointed main schema.
    with path.open("rb") as stream:
        header = stream.read(100)
    _require(len(header) == 100 and header[:16] == b"SQLite format 3\x00"
             and int.from_bytes(header[68:72], "big") == APPLICATION_ID,
             "FOREIGN_DATABASE_REFUSED")
    # Immutable reads deliberately ignore WAL and do not take SQLite locks.
    # A legitimate concurrent checkpoint can briefly make that view incoherent.
    # Reopen within a bounded deadline; a malformed/foreign view never falls
    # through to ordinary SQLite recovery or creates an original-file sidecar.
    deadline = time.monotonic() + 2.0
    while True:
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            _check_schema(db)
            return
        except (sqlite3.DatabaseError, ShadowStoreError):
            if time.monotonic() >= deadline:
                raise
        finally:
            db.close()
        time.sleep(0.01)


class ShadowStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if self.path.exists():
            # Refuse unmarked, old research and foreign databases before WAL/DDL.
            try:
                with self.connect(readonly=True):
                    pass
            except sqlite3.DatabaseError as exc:
                raise ShadowStoreError("FOREIGN_DATABASE_REFUSED") from exc
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Build a complete database under our own exclusive temp
        # name. Publishing by hard link is atomic and cannot replace a winner or
        # an original file. A concurrent constructor never sees half a schema.
        handle, temporary_name = tempfile.mkstemp(prefix=".shadow-init-", suffix=".sqlite3", dir=self.path.parent)
        os.close(handle)
        temporary = Path(temporary_name)
        db = sqlite3.connect(temporary, timeout=10, isolation_level=None)
        initialized = False
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            for sql in (*_TABLE_SQL.values(), *_TRIGGER_SQL.values()):
                db.execute(sql)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.commit()
            initialized = True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
            if not initialized:
                temporary.unlink()
        try:
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                # A peer or foreign owner won the path. Validate without any
                # repair, overwrite or deletion of the existing target.
                ShadowStore(self.path)
        finally:
            temporary.unlink()

    @contextmanager
    def connect(self, readonly=False):
        _preflight(self.path)
        mode = "ro" if readonly else "rw"
        db = sqlite3.connect(self.path.as_uri() + "?mode=" + mode,
                             uri=True, timeout=10, isolation_level=None)
        try:
            _check_schema(db)
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA foreign_keys=ON")
            if readonly:
                db.execute("PRAGMA query_only=ON")
            else:
                db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    def _transaction(self, operation):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                _check_schema(db)
                result = operation(db)
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _insert_artifact(db, snapshot_hash, name, raw):
        db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)",
                   (snapshot_hash, name, raw, _sha(raw), len(raw)))

    @staticmethod
    def _insert_row(db, snapshot_hash, row):
        db.execute("INSERT INTO rows VALUES (?,?,?,?,?,?)",
                   (snapshot_hash, row["game"], row["issue"], None,
                    _canonical(row), _digest(row)))

    @staticmethod
    def _load(db, snapshot_hash):
        record = db.execute("SELECT archive_sha256,manifest_bytes,payload,sha256,scope "
                            "FROM snapshots WHERE snapshot_sha256=?", (snapshot_hash,)).fetchone()
        _require(record is not None, "SNAPSHOT_NOT_FOUND")
        archive_hash, manifest, payload, payload_hash, scope = record
        metadata = _json(payload)
        _require(_canonical(metadata) == payload and _digest(metadata) == payload_hash
                 and scope == STATUS["scope"], "SNAPSHOT_HASH_MISMATCH")
        files = {}
        for name, raw, digest, size in db.execute(
                "SELECT file,raw,sha256,size FROM artifacts WHERE snapshot_sha256=?", (snapshot_hash,)):
            _require(type(raw) is bytes and _sha(raw) == digest and len(raw) == size,
                     "ARTIFACT_HASH_OR_SIZE_MISMATCH")
            files[name] = raw
        rows = []
        for game, issue, available_at, value, digest in db.execute(
                "SELECT game,issue,available_at,payload,sha256 FROM rows WHERE snapshot_sha256=? "
                "ORDER BY game,issue", (snapshot_hash,)):
            row = _json(value)
            _require(_canonical(row) == value and _digest(row) == digest, "ROW_HASH_MISMATCH")
            _require(row.get("game") == game and row.get("issue") == issue
                     and available_at is None, "ROW_IDENTITY_MISMATCH")
            rows.append(row)
        checked = _validate(dict(snapshot_sha256=snapshot_hash, archive_sha256=archive_hash,
                                 manifest_bytes=manifest, files=files, rows=rows,
                                 counts=metadata.get("counts"), verification_scope=VERIFICATION_SCOPE))
        _require(checked[3] == metadata, "SNAPSHOT_METADATA_MISMATCH")
        return checked

    def append_snapshot(self, verified: dict) -> bool:
        manifest, files, rows, metadata = _validate(verified)
        snapshot_hash = metadata["snapshot_sha256"]
        def operation(db):
            if db.execute("SELECT 1 FROM snapshots WHERE snapshot_sha256=?", (snapshot_hash,)).fetchone():
                old = self._load(db, snapshot_hash)
                _require(old == (manifest, files, rows, metadata), "IMMUTABLE_SNAPSHOT_CONFLICT")
                return False
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?)",
                       (snapshot_hash, metadata["archive_sha256"], manifest,
                        _canonical(metadata), _digest(metadata), STATUS["scope"]))
            for name, raw in sorted(files.items()):
                self._insert_artifact(db, snapshot_hash, name, raw)
            for row in rows:
                self._insert_row(db, snapshot_hash, row)
            return True
        return self._transaction(operation)

    def _read(self, snapshot_hash):
        _hash(snapshot_hash)
        with self.connect(readonly=True) as db:
            db.execute("BEGIN")
            return self._load(db, snapshot_hash)

    def summary(self, snapshot_sha256) -> dict:
        """Verify the entire named snapshot; no implicit newest-snapshot lookup."""
        return self._read(snapshot_sha256)[3]

    def read_rows(self, snapshot_sha256) -> list:
        """Return full metadata with explicit archive-only labels on every row."""
        return [dict(row, **STATUS) for row in self._read(snapshot_sha256)[2]]
