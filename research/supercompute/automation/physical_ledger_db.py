"""Crash-safe SQLite materialized index of create-only SSQ/DLT issuer evidence.

Canonical originals are raw/<sha256>.bin, draws/<issue>.json and
attempts/<issue>/*.json on a durable Git evidence branch. SQLite is a
queryable derived index; never use it to manufacture raw observations.
No formal V4.7 prediction inputs or forecasts are written.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from research.supercompute.automation.ssq_physical_source import verify as ssq_verify
from research.supercompute.automation.dlt_physical_source import verify as dlt_verify

SCHEMA = "SSQDLT_PHYSICAL_SQLITE_V1"
GAMES = ("SSQ", "DLT")
DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_documents (
    game TEXT NOT NULL CHECK(game IN ('SSQ', 'DLT')),
    sha256 TEXT NOT NULL,
    body BLOB NOT NULL,
    PRIMARY KEY (game, sha256)
);
CREATE TABLE IF NOT EXISTS draws (
    game TEXT NOT NULL CHECK(game IN ('SSQ', 'DLT')),
    issue TEXT NOT NULL,
    draw_date TEXT NOT NULL,
    observation_class TEXT NOT NULL,
    ball_group INTEGER,
    raw_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY(game, issue),
    FOREIGN KEY(game, raw_sha256) REFERENCES raw_documents(game, sha256)
);
CREATE INDEX IF NOT EXISTS draws_by_date ON draws(game, draw_date, issue);
CREATE TABLE IF NOT EXISTS attempts (
    game TEXT NOT NULL CHECK(game IN ('SSQ', 'DLT')),
    receipt_path TEXT NOT NULL,
    issue TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    PRIMARY KEY(game, receipt_path)
);
CREATE INDEX IF NOT EXISTS attempt_by_issue ON attempts(game, issue, observed_at_utc);
"""


class IntegrityBlocked(ValueError):
    pass


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _reject_duplicates(pairs):
    ans = {}
    for key, val in pairs:
        if key in ans:
            raise IntegrityBlocked("JSON_DUPLICATE_KEY")
        ans[key] = val
    return ans


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_bytes().decode("utf-8"),
                         object_pairs_hook=_reject_duplicates,
                         parse_constant=lambda x: (_ for _ in ()).throw(
                             IntegrityBlocked("JSON_NONFINITE")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityBlocked("JSON_ENCODING_OR_SYNTAX_INVALID") from exc
    if not isinstance(obj, dict):
        raise IntegrityBlocked("JSON_ROOT_NOT_OBJECT")
    return obj


def _insert_exact(conn, table: str, columns: tuple[str, ...],
                  key_columns: tuple[str, ...], data: tuple) -> None:
    placeholders = ",".join("?" for _ in columns)
    cols = ",".join(columns)
    where = " AND ".join(f"{k}=?" for k in key_columns)
    insert = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
    conn.execute(insert, data)
    key_idx = [columns.index(key) for key in key_columns]
    row = conn.execute(f"SELECT {cols} FROM {table} WHERE {where}",
                       tuple(data[i] for i in key_idx)).fetchone()
    if row is None or tuple(row) != data:
        raise IntegrityBlocked(f"{table.upper()}_IMMUTABLE_CONFLICT")


def _collect_game(conn, game: str, path: Path) -> tuple[int, int, int]:
    if game == "SSQ":
        ssq_verify(path)
    else:
        dlt_verify(path)
    raw = 0
    draws = 0
    attempts = 0
    for file in sorted((path / "raw").glob("*.bin")):
        digest = sha256(file.read_bytes()).hexdigest()
        if file.stem != digest:
            raise IntegrityBlocked("RAW_FILENAME_HASH_CONFLICT")
        _insert_exact(conn, "raw_documents", ("game", "sha256", "body"),
                      ("game", "sha256"), (game, digest, file.read_bytes()))
        raw += 1
    for file in sorted((path / "draws").glob("*.json")):
        row = _read_json(file)
        if row.get("game") != game or file.stem != row.get("issue"):
            raise IntegrityBlocked("DRAW_GAME_OR_ISSUE_MISMATCH")
        source_hash = row.get("source_sha256", "")
        if not conn.execute("SELECT 1 FROM raw_documents WHERE game=? AND sha256=?",
                            (game, source_hash)).fetchone():
            raise IntegrityBlocked("DRAW_WITHOUT_RAW_SOURCE")
        observation = ("SORTED_ONLY" if game == "SSQ" else "ORDERED_PHYSICAL")
        if game == "SSQ":
            if (row.get("observation_class") != observation
                    or any(row.get(k) is not None for k in
                           ("red_order", "red_ball_group", "blue_ball_group"))):
                raise IntegrityBlocked("SSQ_PHYSICAL_DATA_FABRICATED")
            group = None
        else:
            group = row.get("ball_group")
            if type(group) is not int or not 1 <= group <= 9:
                raise IntegrityBlocked("DLT_GROUP_INVALID")
        _insert_exact(conn, "draws",
                      ("game", "issue", "draw_date", "observation_class",
                       "ball_group", "raw_sha256", "record_json"),
                      ("game", "issue"),
                      (game, row["issue"], row["draw_date"], observation,
                       group, source_hash, _canonical(row)))
        draws += 1
    for file in sorted((path / "attempts").glob("*/*.json")):
        row = _read_json(file)
        if file.parent.name != row.get("issue") or row.get("status") not in (
                "BLOCKED", "RECORDED", "MATCHED_EXISTING",
                "RECORDED_SORTED_ONLY", "MATCHED_EXISTING_SORTED_ONLY"):
            raise IntegrityBlocked("ATTEMPT_SCHEMA_INVALID")
        if row.get("schema") is None:
            raise IntegrityBlocked("ATTEMPT_PROTOCOL_INVALID")
        rel = file.relative_to(path).as_posix()
        _insert_exact(conn, "attempts",
                      ("game", "receipt_path", "issue", "status",
                       "observed_at_utc", "receipt_sha256", "receipt_json"),
                      ("game", "receipt_path"),
                      (game, rel, row["issue"], row["status"],
                       row["observed_at_utc"], sha256(file.read_bytes()).hexdigest(),
                       _canonical(row)))
        attempts += 1
    for table, actual, clause in (
            ("raw_documents", raw, "game=?"),
            ("draws", draws, "game=?"),
            ("attempts", attempts, "game=?")):
        present = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {clause}",
                               (game,)).fetchone()[0]
        if present != actual:
            raise IntegrityBlocked("SQLITE_CANONICAL_LEDGER_MISMATCH_" + table)
    return raw, draws, attempts


def sync(root: Path, db: Path, *, inject_failure_before_commit=False) -> dict:
    """All or nothing: SQLite transaction; existing data never rewritten."""
    root = root.resolve()
    db = db.resolve()
    if db == root or root in db.parents and any(
            folder == "raw" or folder == "draws" for folder in db.parts):
        raise IntegrityBlocked("SQLITE_PATH_INVALID")
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, timeout=20)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(DDL)
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone():
            row = conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()
            if row[0] != SCHEMA:
                raise IntegrityBlocked("UNSUPPORTED_SCHEMA_VERSION")
        else:
            conn.execute("INSERT INTO schema_version VALUES (1, ?)", (SCHEMA,))
        result = {}
        for game in GAMES:
            raw, draws, attempts = _collect_game(conn, game, root / game)
            result[game] = {"raw": raw, "draws": draws, "attempts": attempts}
        if inject_failure_before_commit:
            raise RuntimeError("INJECTED_CRASH_BEFORE_SQLITE_COMMIT")
        conn.commit()
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise IntegrityBlocked("SQLITE_INTEGRITY_CHECK_FAILED")
        if any(conn.execute("PRAGMA foreign_key_check").fetchall()):
            raise IntegrityBlocked("SQLITE_FOREIGN_KEY_CHECK_FAILED")
        return {"schema": SCHEMA, "status": "SQLITE_AND_CANONICAL_FILES_VERIFIED",
                "counts": result, "formal_A": 0, "predictive_edge": "NO_EDGE"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--db", required=True, type=Path)
    args = p.parse_args()
    report = sync(args.root, args.db)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
