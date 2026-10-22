"""Cross-source semantic history comparator for parsed source rows.

This module validates parsed values and allowlisted host claims; it does not
fetch or parse source bytes and never authenticates an official source by itself.
"""
from __future__ import annotations

from datetime import timezone
from urllib.parse import urlsplit

from .core import (
    MIN_STUDY_HISTORY, RULES, SOURCE_HOSTS_BY_GAME, GateError, dt,
    validate_study_snapshot, _balls,
)


def _source_root(game: str, url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError) as exc:
        raise GateError("INVALID_SOURCE_URL") from exc
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
        raise GateError("HTTPS_SOURCE_URL_REQUIRED")
    for root in SOURCE_HOSTS_BY_GAME[game]:
        if host == root or host.endswith("." + root):
            return host, root
    raise GateError("SOURCE_HOST_NOT_ALLOWLISTED_FOR_GAME")


def _normalize_rows(game: str, rows: list[dict], as_of: str) -> list[dict]:
    if not isinstance(rows, list) or len(rows) < MIN_STUDY_HISTORY:
        raise GateError("SOURCE_HISTORY_REQUIRES_AT_LEAST_120_DRAWS")
    rules = RULES[game]
    normalized = []
    last_issue, last_drawn = -1, None
    for row in rows:
        required = {"issue", "front", "back", "drawn_at", "published_at"}
        if not isinstance(row, dict) or set(row) != required:
            raise GateError("INVALID_PARSED_SOURCE_ROW_SCHEMA")
        issue = str(row["issue"])
        if not issue.isdigit() or int(issue) <= last_issue:
            raise GateError("SOURCE_HISTORY_DUPLICATE_OR_OUT_OF_ORDER_ISSUE")
        _balls(row["front"], rules["pool"], rules["front"])
        _balls(row["back"], rules["back_pool"], rules["back"])
        drawn, published = dt(row["drawn_at"]), dt(row["published_at"])
        if not drawn <= published <= dt(as_of):
            raise GateError("SOURCE_HISTORY_AFTER_ASOF_OR_BAD_PUBLICATION_TIME")
        if last_drawn is not None and drawn < last_drawn:
            raise GateError("SOURCE_HISTORY_TIME_ORDER_VIOLATION")
        normalized.append({
            "issue": issue,
            "front": list(row["front"]),
            "back": list(row["back"]),
            "drawn_at_utc": drawn.astimezone(timezone.utc).isoformat(),
        })
        last_issue, last_drawn = int(issue), drawn
    return normalized


def compare_source_histories(snapshot: dict, source_a: dict, rows_a: list[dict],
                             source_b: dict, rows_b: list[dict]) -> dict:
    """Compare two allowlisted parsed histories with the locked snapshot, fail closed."""
    snapshot_sha = validate_study_snapshot(snapshot)
    game = snapshot["lottery"]
    for source in (source_a, source_b):
        if not isinstance(source, dict) or set(source) != {"url", "raw_sha256"}:
            raise GateError("INVALID_SOURCE_REFERENCE")
        if (not isinstance(source["raw_sha256"], str)
                or len(source["raw_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in source["raw_sha256"])):
            raise GateError("INVALID_RAW_SOURCE_SHA256")
    host_a, root_a = _source_root(game, source_a["url"])
    host_b, root_b = _source_root(game, source_b["url"])
    if source_a["url"] == source_b["url"] or root_a == root_b:
        raise GateError("TWO_DISTINCT_OFFICIAL_SOURCE_ROOTS_REQUIRED")
    a = _normalize_rows(game, rows_a, snapshot["as_of"])
    b = _normalize_rows(game, rows_b, snapshot["as_of"])
    snapshot_rows = _normalize_rows(game, [
        {"issue": d["issue"], "front": d["front"], "back": d["back"],
         "drawn_at": d["drawn_at"], "published_at": d["published_at"]}
        for d in snapshot["draws"]
    ], snapshot["as_of"])
    if a != b:
        raise GateError("OFFICIAL_SOURCE_HISTORY_CONFLICT")
    if a != snapshot_rows:
        raise GateError("SOURCE_HISTORY_DIFFERS_FROM_LOCKED_SNAPSHOT")
    return {
        "lottery": game,
        "target_issue": str(snapshot["target_issue"]),
        "snapshot_sha256": snapshot_sha,
        "history_rows": len(a),
        "source_roots": [root_a, root_b],
        "source_hosts": [host_a, host_b],
        "semantic_agreement": "MATCHED",
        "source_origin_authenticity": "NOT_VERIFIED",
        "source_parser_authenticity": "NOT_VERIFIED",
        "official_G01": "BLOCKED",
        "formal_A": 0,
        "decision": "NO_EDGE",
        "limitations": [
            "Rows were supplied by the caller; this module does not parse the raw bytes.",
            "URL host allowlisting and matching row values do not prove official origin or publication time.",
            "G01 stays BLOCKED until an audited source parser, preserved raw artifacts and independent provenance checks pass.",
        ],
    }
