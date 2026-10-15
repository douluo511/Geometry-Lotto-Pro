"""Append-only local RESEARCH ledger. No API in this module grants formal A.

SQLite protects against accidental SQL mutations, not a malicious file owner.
External authorization, time attestation and backup custody remain required.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .scoring import AdmissionBlocked, RULES, paired_exact_one_sided, validate_numbers

SLOTS = ("M04", "M05-1", "M05-2", "M05-3", "M05-4", "M05-5", "M06", "M07")
TABLES = ("registrations", "candidates", "draws", "heartbeats", "authorizations")
APPLICATION_ID = 0x47565034


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def instant(value):
    if type(value) is not str:
        raise AdmissionBlocked("INVALID_TIME")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionBlocked("INVALID_TIME") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise AdmissionBlocked("NAIVE_TIME")
    return result.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def identity(game, issue):
    if type(game) is not str or game not in RULES:
        raise AdmissionBlocked("UNKNOWN_GAME")
    if type(issue) is not str or not issue.strip() or len(issue) > 80:
        raise AdmissionBlocked("INVALID_ISSUE")


def validate_dans(game, dans):
    if type(dans) is not dict or set(dans) != {f"D{k}" for k in range(1, 6)}:
        raise AdmissionBlocked("MISSING_DAN_IDENTITY")
    for k in range(1, 6):
        validate_numbers(dans[f"D{k}"], k, RULES[game][0])


class Ledger:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            application_id = db.execute("PRAGMA application_id").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if (application_id not in (0, APPLICATION_ID) or tables - set(TABLES)
                    or (application_id == 0 and tables)):
                raise AdmissionBlocked("FOREIGN_DATABASE_REFUSED")
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0,1,2):
                raise AdmissionBlocked("UNKNOWN_LEDGER_SCHEMA")
            db.execute("PRAGMA journal_mode=WAL")
            for table, keys in (("registrations", "game TEXT, issue TEXT, PRIMARY KEY(game,issue)"),
                                ("candidates", "game TEXT, issue TEXT, slot TEXT, PRIMARY KEY(game,issue,slot)"),
                                ("draws", "game TEXT, issue TEXT, PRIMARY KEY(game,issue)"),
                                ("heartbeats", "run_id TEXT PRIMARY KEY"),
                                ("authorizations", "role TEXT, nonce TEXT, PRIMARY KEY(role,nonce)")):
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (payload TEXT NOT NULL, sha256 TEXT NOT NULL, {keys})")
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
                # BEFORE INSERT is essential: SQLite REPLACE must not bypass the
                # no-update trigger by deleting and reinserting a conflicting key.
                key_names = (("run_id",) if table == "heartbeats" else
                             ("role", "nonce") if table == "authorizations" else
                             ("game", "issue", "slot") if table == "candidates" else ("game", "issue"))
                where = " AND ".join(f"{key}=NEW.{key}" for key in key_names)
                db.execute(f"CREATE TRIGGER IF NOT EXISTS no_replace_{table} BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE {where}) BEGIN SELECT RAISE(ABORT, 'DUPLICATE_KEY'); END")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self, readonly=False):
        if readonly:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
            db.execute("PRAGMA query_only=ON")
        else:
            db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _get(db, table, keys):
        clause = " AND ".join(f"{key}=?" for key in keys)
        row = db.execute(f"SELECT payload,sha256 FROM {table} WHERE {clause}", tuple(keys.values())).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if digest(value) != row[1] or canonical(value) != row[0]:
            raise AdmissionBlocked("LEDGER_HASH_MISMATCH")
        if any(value.get(key) != expected for key, expected in keys.items()):
            raise AdmissionBlocked("LEDGER_IDENTITY_MISMATCH")
        return value

    @staticmethod
    def _insert(db, table, keys, value):
        old = Ledger._get(db, table, keys)
        if old is not None:
            if canonical(old) != canonical(value):
                raise AdmissionBlocked("IMMUTABLE_CONFLICT")
            return False
        columns = ("payload", "sha256", *keys)
        db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                   (canonical(value), digest(value), *keys.values()))
        return True

    def _transaction(self, operation):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                result = operation(db)
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    def register(self, game, issue, versions, deadline, m05_primary, *, now=None):
        identity(game, issue)
        if (type(versions) is not dict or set(versions) != set(SLOTS)
                or any(type(v) is not str or not v.strip() for v in versions.values())
                or m05_primary not in SLOTS[1:6]):
            raise AdmissionBlocked("INVALID_EIGHT_SLOT_REGISTRY")
        value = dict(game=game, issue=issue, versions=versions, deadline=deadline,
                     m05_primary=m05_primary, scope="RESEARCH_ONLY")
        def operation(db):
            for (previous_issue,) in db.execute("SELECT issue FROM registrations WHERE game=?", (game,)):
                previous = self._get(db, "registrations", dict(game=game, issue=previous_issue))
                if previous["versions"] != versions or previous["m05_primary"] != m05_primary:
                    raise AdmissionBlocked("NEW_VERSION_OR_PRIMARY_REQUIRES_SEPARATE_TRIAL_LEDGER")
            old = self._get(db, "registrations", dict(game=game, issue=issue))
            # An identical retry is safe even after the deadline.
            if old is None and instant(now or utc_now()) >= instant(deadline):
                raise AdmissionBlocked("LATE_REGISTRATION")
            return self._insert(db, "registrations", dict(game=game, issue=issue), value)
        instant(deadline)
        return self._transaction(operation)

    def freeze(self, game, issue, slot, version, dans, *, now=None, signed_research=None):
        """Freeze research bytes, optionally with atomic 01/04 nonce consumption.

        signed_research is {envelopes: {01:...,04:...}, trusted_keys: ...}.
        Even real cryptographic verification here does not provision formal trust,
        supply an external TSA, or convert this research record to formal A.
        """
        identity(game, issue)
        validate_dans(game, dans)
        value = dict(game=game, issue=issue, slot=slot, version=version, dans=dans,
                     scope="RESEARCH_ONLY")
        def operation(db):
            registry = self._get(db, "registrations", dict(game=game, issue=issue))
            if registry is None or slot not in registry["versions"] or registry["versions"][slot] != version:
                raise AdmissionBlocked("UNREGISTERED_SLOT_OR_VERSION")
            old = self._get(db, "candidates", dict(game=game, issue=issue, slot=slot))
            if old is None and self._get(db, "draws", dict(game=game, issue=issue)) is not None:
                raise AdmissionBlocked("POST_DRAW_CANDIDATE")
            if old is None and instant(now or utc_now()) >= instant(registry["deadline"]):
                raise AdmissionBlocked("LATE_CANDIDATE")
            if old is None and signed_research is not None:
                from .admission import verify_ed25519_authorization
                if (type(signed_research) is not dict
                        or type(signed_research.get("envelopes")) is not dict
                        or set(signed_research["envelopes"]) != {"01","04"}):
                    raise AdmissionBlocked("BOTH_SIGNED_ROLES_REQUIRED")
                for role in ("01","04"):
                    consumed = {row[0] for row in db.execute("SELECT nonce FROM authorizations WHERE role=?", (role,))}
                    result = verify_ed25519_authorization(
                        signed_research["envelopes"][role], expected_role=role,
                        payload_sha256=digest(value), trusted_keys=signed_research.get("trusted_keys"),
                        now=now or utc_now(), cutoff=registry["deadline"], consumed_nonces=consumed)
                    nonce = result["consume_nonce"]
                    self._insert(db, "authorizations", dict(role=role,nonce=nonce),
                                 dict(role=role,nonce=nonce,game=game,issue=issue,slot=slot,
                                      candidate_sha256=digest(value),claims_sha256=result["claims_sha256"],
                                      scope="RESEARCH_ONLY"))
            return self._insert(db, "candidates", dict(game=game, issue=issue, slot=slot), value)
        return self._transaction(operation)

    def record_research_draw(self, game, issue, front, provenance):
        """Store an untrusted research observation; provenance is never an A grant."""
        identity(game, issue)
        validate_numbers(front, RULES[game][1], RULES[game][0])
        if type(provenance) is not dict:
            raise AdmissionBlocked("MISSING_PROVENANCE")
        value = dict(game=game, issue=issue, front=sorted(front), provenance=provenance,
                     scope="RESEARCH_ONLY")
        def operation(db):
            if self._get(db, "registrations", dict(game=game, issue=issue)) is None:
                raise AdmissionBlocked("UNREGISTERED_ISSUE")
            return self._insert(db, "draws", dict(game=game, issue=issue), value)
        return self._transaction(operation)

    def heartbeat(self, run_id, payload):
        if type(run_id) is not str or not run_id:
            raise AdmissionBlocked("INVALID_RUN_ID")
        value = dict(payload, run_id=run_id)
        return self._transaction(lambda db: self._insert(db, "heartbeats", dict(run_id=run_id), value))

    def replay(self):
        """Read all expected issues in one read-only snapshot. Never train or freeze."""
        import math
        rows, missing, paired, cohorts = [], [], {}, {}
        with self.connect(readonly=True) as db:
            db.execute("BEGIN")
            registered = db.execute("SELECT game,issue FROM registrations ORDER BY game,issue").fetchall()
            for game, issue in registered:
                keys = dict(game=game, issue=issue)
                reg = self._get(db, "registrations", keys)
                cohort = dict(versions=reg["versions"], m05_primary=reg["m05_primary"])
                if game in cohorts and cohorts[game] != cohort:
                    raise AdmissionBlocked("MIXED_TRIAL_VERSIONS_OR_PRIMARY")
                cohorts[game] = cohort
                draw = self._get(db, "draws", keys)
                candidates = {slot: self._get(db, "candidates", dict(**keys, slot=slot)) for slot in SLOTS}
                absent = [slot for slot, value in candidates.items() if value is None]
                if draw is None or absent:
                    missing.append(dict(**keys, missing_slots=absent, missing_draw=draw is None))
                    continue
                # Validate from stored bytes again before scoring.
                validate_numbers(draw["front"], RULES[game][1], RULES[game][0])
                period = {}
                for slot, candidate in candidates.items():
                    if candidate["version"] != reg["versions"][slot]:
                        raise AdmissionBlocked("VERSION_MISMATCH")
                    validate_dans(game, candidate["dans"])
                    period[slot] = {}
                    for k in range(1, 6):
                        dan = f"D{k}"
                        hits = len(set(candidate["dans"][dan]) & set(draw["front"]))
                        period[slot][dan] = int(hits == k)
                        rows.append(dict(**keys, slot=slot, version=candidate["version"], dan=dan,
                                         hits=hits, full=int(hits == k),
                                         p0=math.comb(RULES[game][1], k)/math.comb(RULES[game][0], k)))
                for slot in SLOTS[:-1]:
                    pair = paired.setdefault((game, slot), dict(wins=0, losses=0, ties=0))
                    x, y = period[slot]["D2"], period["M07"]["D2"]
                    pair["wins" if x > y else "losses" if x < y else "ties"] += 1
        # Do not silently drop an absent expected issue to improve a comparison.
        comparisons = []
        if not missing:
            for (game, slot), pair in sorted(paired.items()):
                n = sum(pair.values())
                comparisons.append(dict(game=game, slot=slot, version=cohorts[game]["versions"][slot],
                                        null="M07", null_version=cohorts[game]["versions"]["M07"],
                                        m05_primary=cohorts[game]["m05_primary"],
                                        is_preselected_m05=(slot == cohorts[game]["m05_primary"]), n=n, **pair,
                                        paired_delta=(pair["wins"]-pair["losses"])/n,
                                        p_exploratory=paired_exact_one_sided(pair["wins"], pair["losses"])))
        return dict(scope="RESEARCH_ONLY", R2="BLOCKED", formal_A=0, decision="NO_EDGE",
                    expected_issues=len(registered), status="NOT_SCORABLE" if missing or not registered else "RESEARCH_ONLY",
                    missing=missing, cohorts=cohorts, scores=rows, comparisons=comparisons,
                    repository_independence="FAIL", final_gate="FAIL")
