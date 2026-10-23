"""Explicit date-only model input, SHADOW/A0 only; no source or clock authority.

Capture hashes are caller assertions bound into the snapshot identity. This
structural validator does not fetch bytes, replay a parser, authenticate the
target schedule, establish publication time, or replace independent gates.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone

from .core import MIN_STUDY_HISTORY, RULES, GateError, _balls, digest, dt


CONTRACT = "V47-DATE-OBSERVED-SHADOW-1"
CHINA = timezone(timedelta(hours=8))
OBSERVATION_FIELDS = frozenset({
    "schema", "manifest_sha256", "parser_source_sha256", "raw_sha256s",
    "observed_at_local_untrusted", "history_policy", "selected_rows_sha256",
})
ROW_FIELDS = frozenset({"issue", "draw_date", "front", "back"})
PROVENANCE_QUALIFICATIONS = {
    "source_authenticity": "CALLER_UNVERIFIED",
    "publication_time": "UNKNOWN",
    "evidence_class": "SHADOW",
    "formal_A": 0,
    "decision": "NO_EDGE",
    "official_G01": "BLOCKED",
}


def _sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _issue_key(value):
    # Compare arbitrary positive issue strings without lossy numeric coercion.
    if (not isinstance(value, str) or not value or value[0] == "0"
            or any(char not in "0123456789" for char in value)):
        raise GateError("OBSERVED_SNAPSHOT_INVALID_ISSUE")
    return len(value), value


def _timestamp(value):
    if not isinstance(value, str):
        raise GateError("OBSERVED_SNAPSHOT_INVALID_TIMESTAMP")
    return dt(value)


def _draw_date(value):
    if not isinstance(value, str):
        raise GateError("OBSERVED_SNAPSHOT_INVALID_DRAW_DATE")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise GateError("OBSERVED_SNAPSHOT_INVALID_DRAW_DATE") from exc
    if parsed.isoformat() != value:
        raise GateError("OBSERVED_SNAPSHOT_NONCANONICAL_DRAW_DATE")
    return parsed


def validate_observed_snapshot(snapshot):
    """Validate local consistency, never official admission or trusted time."""
    if (not isinstance(snapshot, dict)
            or snapshot.get("snapshot_contract") != CONTRACT
            or snapshot.get("lottery") not in RULES):
        raise GateError("INVALID_OBSERVED_SNAPSHOT_CONTRACT_OR_GAME")

    provenance = snapshot.get("provenance")
    if (not isinstance(provenance, dict)
            or type(provenance.get("formal_A")) is not int
            or any(provenance.get(key) != value
                   for key, value in PROVENANCE_QUALIFICATIONS.items())):
        raise GateError("OBSERVED_SNAPSHOT_CANNOT_ASSERT_AUTHORITY")

    observation = snapshot.get("capture_observation")
    if (not isinstance(observation, dict) or set(observation) != OBSERVATION_FIELDS
            or observation["schema"] != "V47-RAW-OBSERVATION-1"
            or observation["history_policy"] != "LATEST_120_VALIDATED_DRAWS_V1"):
        raise GateError("INVALID_OBSERVED_CAPTURE_CONTRACT")
    if any(not _sha256(observation[key]) for key in
           ("manifest_sha256", "parser_source_sha256", "selected_rows_sha256")):
        raise GateError("INVALID_OBSERVED_CAPTURE_SHA256")
    raw_hashes = observation["raw_sha256s"]
    if (not isinstance(raw_hashes, list) or not raw_hashes
            or any(not _sha256(value) for value in raw_hashes)
            or len(set(raw_hashes)) != len(raw_hashes)):
        raise GateError("INVALID_OBSERVED_RAW_SHA256_SET")

    as_of, cutoff, target_time = (_timestamp(snapshot.get(key)) for key in
                                  ("as_of", "sales_cutoff", "target_draw_at"))
    observed_at = _timestamp(observation["observed_at_local_untrusted"])
    if not observed_at <= as_of < cutoff <= target_time:
        raise GateError("OBSERVED_SNAPSHOT_TIME_LOCK_VIOLATION")
    target_key = _issue_key(snapshot.get("target_issue"))
    observed_date = observed_at.astimezone(CHINA).date()
    as_of_date = as_of.astimezone(CHINA).date()

    draws = snapshot.get("draws")
    if not isinstance(draws, list) or len(draws) != MIN_STUDY_HISTORY:
        raise GateError("OBSERVED_HISTORY_REQUIRES_EXACTLY_120_DRAWS")
    rules = RULES[snapshot["lottery"]]
    previous_issue, previous_date = None, None
    for row in draws:
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise GateError("INVALID_OBSERVED_DRAW_SCHEMA")
        issue_key = _issue_key(row["issue"])
        drawn_date = _draw_date(row["draw_date"])
        _balls(row["front"], rules["pool"], rules["front"])
        _balls(row["back"], rules["back_pool"], rules["back"])
        if previous_issue is not None and issue_key <= previous_issue:
            raise GateError("OBSERVED_HISTORY_DUPLICATE_OR_OUT_OF_ORDER_ISSUE")
        if previous_date is not None and drawn_date <= previous_date:
            raise GateError("OBSERVED_HISTORY_DATE_ORDER_VIOLATION")
        # A date states an interval, never an exact event/publication time.
        # Reject same-day input rather than estimating a usual draw hour.
        if not drawn_date < observed_date <= as_of_date:
            raise GateError("OBSERVED_HISTORY_NOT_STRICTLY_BEFORE_CAPTURE_DATE")
        if issue_key >= target_key:
            raise GateError("OBSERVED_TARGET_NOT_STRICTLY_FUTURE")
        previous_issue, previous_date = issue_key, drawn_date
    if observation["selected_rows_sha256"] != digest(draws):
        raise GateError("OBSERVED_SELECTED_ROWS_SHA256_MISMATCH")
    return digest(snapshot)
