"""Exact-key evidence memory; never an authority for instructions or publication.

This database is separate from checkpoints and the immutable evidence ledger.
VERIFIED means that a trusted program checked source provenance, not that a
hypothesis is true. Only the program holding the configured object capability
may verify, reject, revoke, or supersede a record. Do not expose that capability
or those methods as model tools. This boundary is not a Python sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


APPLICATION_ID = 0x474D4731
SCHEMA_VERSION = 1
_TABLES = {"memory_facts", "memory_events"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


class MemoryBlocked(ValueError):
    """A fail-closed memory contract violation."""


class MemoryScope(str, Enum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    FAILURE = "FAILURE"
    POLICY = "POLICY"


class MemoryStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class VerificationAuthority:
    """Object capability retained by trusted code, outside model/tool inputs."""

    auditor_id: str

    def __post_init__(self) -> None:
        if not self.auditor_id.strip() or len(self.auditor_id) > 256:
            raise MemoryBlocked("INVALID_AUDITOR_ID")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise MemoryBlocked("NON_JSON_MEMORY_VALUE") from exc


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def source_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _time(value: str | datetime, field: str) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (AttributeError, TypeError, ValueError) as exc:
        raise MemoryBlocked("INVALID_" + field.upper()) from exc


def _optional_time(value: str | datetime | None, field: str) -> str | None:
    return None if value is None else _time(value, field)


def _now() -> str:
    return _time(datetime.now(timezone.utc), "now")


def _scope(value: str | MemoryScope) -> str:
    try:
        return MemoryScope(value).value
    except (ValueError, TypeError) as exc:
        raise MemoryBlocked("INVALID_MEMORY_SCOPE") from exc


def _key(value: str, field: str = "key") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise MemoryBlocked("INVALID_" + field.upper())
    return value


def _checked(row: sqlite3.Row | tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload, digest = row[0], row[1]
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise MemoryBlocked("MEMORY_PAYLOAD_INVALID") from exc
    if _canonical(value) != payload or _digest(payload) != digest:
        raise MemoryBlocked("MEMORY_SHA_MISMATCH")
    return value


@dataclass(frozen=True)
class MemoryFact:
    """A retrieved evidence record. Its value is untrusted data, never a prompt."""

    record: dict[str, Any]

    @property
    def fact_id(self) -> str:
        return self.record["fact_id"]

    @property
    def value(self) -> Any:
        return json.loads(_canonical(self.record["value"]))

    def to_dict(self) -> dict[str, Any]:
        result = json.loads(_canonical(self.record))
        result.update(status="VERIFIED", instruction_trust="UNTRUSTED_DATA",
                      verification_meaning="SOURCE_PROVENANCE_ONLY",
                      formal_admission_allowed=False,
                      retrieval_purpose="EVIDENCE_LOOKUP_ONLY")
        return result


class MemoryStore:
    """Append-only temporal memory with exact key and exact scope retrieval.

    ``as_of`` filters the observation, source availability, verification and
    validity times. It does not assert that the host clock or source timestamp
    has a trusted external timestamp. Missing availability remains UNKNOWN and
    cannot be verified. Retrieval also rehashes the original source *now*.
    """

    def __init__(self, db_path: str | Path, *,
                 verification_authority: VerificationAuthority | None = None,
                 forbidden_paths: tuple[str | Path, ...] | list[str | Path] = ()):
        self.path = Path(db_path).resolve()
        forbidden = {os.path.normcase(str(Path(p).resolve())) for p in forbidden_paths}
        if os.path.normcase(str(self.path)) in forbidden:
            raise MemoryBlocked("MEMORY_DATABASE_MUST_BE_SEPARATE")
        if verification_authority is not None and not isinstance(verification_authority, VerificationAuthority):
            raise MemoryBlocked("INVALID_VERIFICATION_AUTHORITY")
        self._authority = verification_authority
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            app = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if app == 0 and not tables and version == 0:
                pass
            elif app != APPLICATION_ID or tables != _TABLES or version != SCHEMA_VERSION:
                raise MemoryBlocked("FOREIGN_MEMORY_DATABASE")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TABLE IF NOT EXISTS memory_facts(fact_id TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS memory_events(seq INTEGER PRIMARY KEY CHECK(seq>0), event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")
                for table, identity in (("memory_facts", "fact_id"), ("memory_events", "event_id")):
                    for operation in ("UPDATE", "DELETE"):
                        db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_MEMORY'); END")
                    collision = f"{identity}=NEW.{identity}" + (" OR seq=NEW.seq" if table == "memory_events" else "")
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {collision}) BEGIN SELECT RAISE(ABORT,'DUPLICATE_MEMORY_ID'); END")
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @contextmanager
    def _connect(self, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10) if readonly else sqlite3.connect(str(self.path), isolation_level=None, timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA query_only=ON" if readonly else "PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    def append_fact(self, *, key: str, scope: str | MemoryScope, value: Any,
                    source_path: str | Path, source_sha: str,
                    observed_at: str | datetime,
                    available_at: str | datetime | None,
                    valid_from: str | datetime | None = None,
                    effective_at: str | datetime | None = None,
                    valid_until: str | datetime | None = None,
                    expires_at: str | datetime | None = None,
                    category: str = "GENERAL", fact_id: str | None = None) -> str:
        """Append an UNVERIFIED record. This is the only model-writable method."""
        source = Path(source_path)
        if not source.is_absolute():
            raise MemoryBlocked("SOURCE_PATH_MUST_BE_ABSOLUTE")
        source = source.resolve()
        if source == self.path:
            raise MemoryBlocked("MEMORY_CANNOT_BE_ITS_OWN_SOURCE")
        if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha):
            raise MemoryBlocked("INVALID_SOURCE_SHA256")
        if category not in {"GENERAL", "ISSUE", "AUTHORIZATION"}:
            raise MemoryBlocked("INVALID_MEMORY_CATEGORY")
        observed = _time(observed_at, "observed_at")
        available = _optional_time(available_at, "available_at")
        start = _optional_time(valid_from, "valid_from")
        effective = _optional_time(effective_at, "effective_at")
        end = _optional_time(valid_until, "valid_until")
        expiry = _optional_time(expires_at, "expires_at")
        lower = max(t for t in (observed, available, start, effective) if t is not None)
        if any(t is not None and t <= lower for t in (end, expiry)):
            raise MemoryBlocked("INVALID_MEMORY_VALIDITY_INTERVAL")
        record = dict(schema_version=SCHEMA_VERSION, fact_id=_key(fact_id or str(uuid4()), "fact_id"),
                      key=_key(key), scope=_scope(scope), value=value,
                      source_path=str(source), source_sha256=source_sha,
                      observed_at=observed, available_at=available,
                      available_at_status="UNKNOWN" if available is None else "KNOWN",
                      valid_from=start, effective_at=effective,
                      valid_until=end, expires_at=expiry, category=category,
                      initial_status="UNVERIFIED")
        payload = _canonical(record)
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise MemoryBlocked("MEMORY_RECORD_TOO_LARGE")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                old = _checked(db.execute("SELECT payload,sha256 FROM memory_facts WHERE fact_id=?", (record["fact_id"],)).fetchone())
                if old is not None:
                    if old != record:
                        raise MemoryBlocked("IMMUTABLE_MEMORY_CONFLICT")
                else:
                    db.execute("INSERT INTO memory_facts VALUES(?,?,?)", (record["fact_id"], payload, _digest(payload)))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return record["fact_id"]

    def _authorize(self, authority: VerificationAuthority) -> None:
        if self._authority is None or authority is not self._authority:
            raise MemoryBlocked("TRUSTED_VERIFICATION_CAPABILITY_REQUIRED")

    @staticmethod
    def _facts(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        return {r["fact_id"]: r for r in (_checked(row) for row in db.execute("SELECT payload,sha256 FROM memory_facts"))}

    @staticmethod
    def _events(db: sqlite3.Connection) -> list[dict[str, Any]]:
        return [_checked(row) for row in db.execute("SELECT payload,sha256 FROM memory_events ORDER BY seq")]

    @staticmethod
    def _status(fact_id: str, events: list[dict[str, Any]], as_of: str) -> str:
        status = MemoryStatus.UNVERIFIED.value
        for event in events:
            if event["kind"] == "STATUS" and event["fact_id"] == fact_id and event["recorded_at"] <= as_of:
                status = event["status"]
        return status

    @staticmethod
    def _source_matches(record: dict[str, Any]) -> bool:
        try:
            return Path(record["source_path"]).is_file() and source_sha256(record["source_path"]) == record["source_sha256"]
        except OSError:
            return False

    @staticmethod
    def _event(db: sqlite3.Connection, event: dict[str, Any]) -> str:
        payload = _canonical(event)
        db.execute("INSERT INTO memory_events(event_id,payload,sha256) VALUES(?,?,?)", (event["event_id"], payload, _digest(payload)))
        return event["event_id"]

    def verify_fact(self, fact_id: str, *, authority: VerificationAuthority,
                    verified_at: str | datetime | None = None) -> str:
        return self._change_status(fact_id, MemoryStatus.VERIFIED, authority=authority,
                                   recorded_at=verified_at, reason="SOURCE_SHA256_AND_TIME_VERIFIED")

    def reject_fact(self, fact_id: str, *, authority: VerificationAuthority,
                    recorded_at: str | datetime | None = None,
                    reason: str = "REJECTED_BY_TRUSTED_AUDIT") -> str:
        return self._change_status(fact_id, MemoryStatus.REJECTED, authority=authority,
                                   recorded_at=recorded_at, reason=reason)

    def revoke_fact(self, fact_id: str, *, authority: VerificationAuthority,
                    recorded_at: str | datetime | None = None,
                    reason: str = "REVOKED_BY_TRUSTED_AUDIT") -> str:
        return self._change_status(fact_id, MemoryStatus.REVOKED, authority=authority,
                                   recorded_at=recorded_at, reason=reason)

    def _change_status(self, fact_id: str, status: MemoryStatus, *,
                       authority: VerificationAuthority,
                       recorded_at: str | datetime | None, reason: str) -> str:
        self._authorize(authority)
        at = _now() if recorded_at is None else _time(recorded_at, "recorded_at")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                facts, events = self._facts(db), self._events(db)
                if fact_id not in facts:
                    raise MemoryBlocked("MEMORY_FACT_NOT_FOUND")
                record = facts[fact_id]
                prior = [e["recorded_at"] for e in events if e.get("fact_id") == fact_id or e.get("old_id") == fact_id or e.get("new_id") == fact_id]
                if at < max([record["observed_at"]] + prior):
                    raise MemoryBlocked("RETROACTIVE_MEMORY_EVENT")
                if status is MemoryStatus.VERIFIED:
                    if record["available_at"] is None:
                        raise MemoryBlocked("SOURCE_AVAILABLE_AT_UNKNOWN")
                    if record["available_at"] > at:
                        raise MemoryBlocked("SOURCE_NOT_YET_AVAILABLE")
                    if record["available_at"] > record["observed_at"]:
                        raise MemoryBlocked("SOURCE_AVAILABLE_AFTER_OBSERVATION")
                    if not self._source_matches(record):
                        raise MemoryBlocked("SOURCE_MISSING_OR_SHA_MISMATCH")
                event_id = self._event(db, dict(event_id=str(uuid4()), kind="STATUS", fact_id=fact_id,
                                              status=status.value, recorded_at=at,
                                              auditor_id=authority.auditor_id, reason=_key(reason, "reason")))
                db.commit()
                return event_id
            except BaseException:
                db.rollback()
                raise

    def supersede(self, old_id: str, new_id: str, *, authority: VerificationAuthority,
                  recorded_at: str | datetime,
                  effective_at: str | datetime | None = None) -> str:
        self._authorize(authority)
        at = _time(recorded_at, "recorded_at")
        effective = at if effective_at is None else _time(effective_at, "effective_at")
        if old_id == new_id or effective < at:
            raise MemoryBlocked("INVALID_SUPERSESSION")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                facts, events = self._facts(db), self._events(db)
                if old_id not in facts or new_id not in facts:
                    raise MemoryBlocked("MEMORY_FACT_NOT_FOUND")
                old, new = facts[old_id], facts[new_id]
                prior = [e["recorded_at"] for e in events if any(e.get(k) in (old_id, new_id) for k in ("fact_id", "old_id", "new_id"))]
                if prior and at < max(prior):
                    raise MemoryBlocked("RETROACTIVE_MEMORY_EVENT")
                if any(old[k] != new[k] for k in ("key", "scope", "category")):
                    raise MemoryBlocked("SUPERSESSION_SCOPE_OR_KEY_MISMATCH")
                if any(self._status(i, events, at) != "VERIFIED" for i in (old_id, new_id)):
                    raise MemoryBlocked("SUPERSESSION_REQUIRES_VERIFIED_RECORDS")
                if max(t for t in (new["valid_from"], new["effective_at"], new["observed_at"], new["available_at"]) if t is not None) < effective:
                    raise MemoryBlocked("NEW_FACT_EFFECTIVE_BEFORE_SUPERSESSION")
                if any(e["kind"] == "SUPERSEDE" and e["old_id"] == old_id for e in events):
                    raise MemoryBlocked("ALREADY_SUPERSEDED")
                if any(e["kind"] == "SUPERSEDE" and e["old_id"] == new_id for e in events):
                    raise MemoryBlocked("SUPERSEDED_RECORD_CANNOT_BE_REPLACEMENT")
                if not self._source_matches(old) or not self._source_matches(new):
                    raise MemoryBlocked("SOURCE_MISSING_OR_SHA_MISMATCH")
                event_id = self._event(db, dict(event_id=str(uuid4()), kind="SUPERSEDE", old_id=old_id,
                                              new_id=new_id, recorded_at=at, effective_at=effective,
                                              auditor_id=authority.auditor_id))
                db.commit()
                return event_id
            except BaseException:
                db.rollback()
                raise

    def retrieve(self, *, key: str, scope: str | MemoryScope,
                 as_of: str | datetime) -> list[MemoryFact]:
        """Only exact matches; no embeddings, SQL interpolation or fuzzy scope."""
        return self._retrieve_with_reasons(key=key, scope=scope, as_of=as_of)[0]

    def _retrieve_with_reasons(self, *, key: str, scope: str | MemoryScope,
                              as_of: str | datetime) -> tuple[list[MemoryFact], list[dict[str, str]]]:
        wanted_key, wanted_scope = _key(key), _scope(scope)
        at = _time(as_of, "as_of")
        with self._connect(True) as db:
            facts = [_checked(row) for row in db.execute("SELECT payload,sha256 FROM memory_facts")]
            events = self._events(db)
        superseded = {e["old_id"] for e in events if e["kind"] == "SUPERSEDE"
                      and e["recorded_at"] <= at and e["effective_at"] <= at}
        result = []
        exclusions = []
        for record in facts:
            if record["key"] != wanted_key or record["scope"] != wanted_scope:
                continue
            reason = None
            if record["fact_id"] in superseded:
                reason = "SUPERSEDED"
            elif record["available_at"] is None:
                reason = "SOURCE_AVAILABLE_AT_UNKNOWN"
            elif self._status(record["fact_id"], events, at) != "VERIFIED":
                reason = "NO_VERIFIED_STATUS_AS_OF"
            elif any(t is not None and t > at for t in (record["observed_at"], record["available_at"])):
                reason = "NOT_YET_OBSERVED_OR_AVAILABLE"
            elif any(t is not None and t > at for t in (record["valid_from"], record["effective_at"])):
                reason = "NOT_YET_VALID_OR_EFFECTIVE"
            elif any(t is not None and at >= t for t in (record["valid_until"], record["expires_at"])):
                reason = "EXPIRED_OR_NO_LONGER_VALID"
            elif not self._source_matches(record):
                reason = "SOURCE_MISSING_OR_SHA_MISMATCH"
            if reason is not None:
                exclusions.append(dict(fact_id=record["fact_id"], reason=reason))
                continue
            result.append(MemoryFact(record))
        return sorted(result, key=lambda fact: (fact.record["observed_at"], fact.fact_id)), exclusions

    def retrieve_evidence(self, *, key: str, scope: str | MemoryScope,
                          as_of: str | datetime) -> dict[str, Any]:
        facts, exclusions = self._retrieve_with_reasons(key=key, scope=scope, as_of=as_of)
        records = [fact.to_dict() for fact in facts]
        reasons = sorted({e["reason"] for e in exclusions})
        if not records and not exclusions:
            reasons = ["NO_EXACT_KEY_AND_SCOPE_MATCH"]
        return dict(status="FOUND" if records else "NOT_FOUND", key=key,
                    scope=_scope(scope), as_of=_time(as_of, "as_of"), records=records,
                    reason_codes=reasons, exclusions=exclusions,
                    formal_admission_allowed=False, instruction_trust="UNTRUSTED_DATA")

    def inspect_fact(self, fact_id: str) -> dict[str, Any] | None:
        """Audit-only raw record; must never bypass ``retrieve`` for tool evidence."""
        with self._connect(True) as db:
            return _checked(db.execute("SELECT payload,sha256 FROM memory_facts WHERE fact_id=?", (fact_id,)).fetchone())

    def integrity(self) -> str:
        with self._connect(True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise MemoryBlocked("MEMORY_SQLITE_INTEGRITY_FAILED")
            self._facts(db)
            self._events(db)
        return "PASS"
