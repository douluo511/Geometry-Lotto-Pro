"""SSQ issuer sorted-results evidence; physical order and ball group UNKNOWN.

Shanghai Welfare Lottery Center currently publishes sorted SSQ numbers in a
history table. Never recast sorted red numbers as actual ball-exit order.
Every attempt emits a create-only receipt, including failed HTTP/parse requests.
This module is research-only and never admits a predraw forecast.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from research.supercompute.automation.dlt_physical_source import (
    Blocked, _create_once, _sealed_bytes, fetch_http,
)
from research.supercompute.automation.official_source_gate import (
    OFFICIAL, SourceBlocked, official_rows,
)

PARSER = "SH_SSQ_SORTED_OFFICIAL_EVIDENCE_V1"
URL = OFFICIAL["SSQ"]["url"]
HOST = OFFICIAL["SSQ"]["host"]
MAX_BYTES = 1_200_000
ISSUE = re.compile(r"[0-9]{7}\Z")


def source_url(issue: str) -> str:
    if not isinstance(issue, str) or not ISSUE.fullmatch(issue):
        raise Blocked("ISSUE_FORMAT_INVALID")
    return URL


def parse_public_table(raw: bytes, expected_issue: str) -> dict:
    """Read issuer sorted results. Order/ball-set cannot be inferred."""
    source_url(expected_issue)
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise Blocked("SOURCE_BYTES_INVALID")
    try:
        rows = official_rows(raw, "SSQ")
    except SourceBlocked as exc:
        raise Blocked("ISSUER_TABLE_INVALID:" + str(exc)) from exc
    matching = [row for row in rows if row.issue == expected_issue]
    if len(matching) != 1:
        raise Blocked("ISSUE_ABSENT_OR_DUPLICATE_IN_ISSUER_WINDOW")
    row = matching[0]
    if row.draw_at[:4] != expected_issue[:4]:
        raise Blocked("ISSUE_DRAW_YEAR_CONFLICT")
    if (len(row.front) != 6 or len(set(row.front)) != 6 or
            tuple(sorted(row.front)) != row.front or
            not all(1 <= n <= 33 for n in row.front) or
            len(row.back) != 1 or not 1 <= row.back[0] <= 16):
        raise Blocked("DRAW_DOMAIN_INVALID")
    return {
        "schema": PARSER,
        "game": "SSQ",
        "issue": expected_issue,
        "draw_date": row.draw_at[:10],
        "red_sorted": list(row.front),
        "blue_number": row.back[0],
        "red_order": None,
        "red_ball_group": None,
        "blue_ball_group": None,
        "order_evidence": "NOT_PUBLISHED_IN_THIS_SOURCE",
        "ball_group_evidence": "NOT_PUBLISHED_IN_THIS_SOURCE",
        "observation_class": "SORTED_ONLY",
    }


def collect(issue: str, ledger: Path, *, fetcher=fetch_http) -> dict:
    url = source_url(issue)
    receipt = {
        "schema": PARSER,
        "game": "SSQ",
        "issue": issue,
        "requested_url": url,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "issuer_table_parser_sha256": sha256(
            (Path(__file__).parent / "official_source_gate.py").read_bytes()
        ).hexdigest(),
        "http_status": None,
        "response_sha256": None,
        "final_url": None,
        "status": "BLOCKED",
        "reason": None,
        "formal_A": 0,
        "predictive_edge": "NO_EDGE",
    }
    try:
        code, resolved_url, raw = fetcher(url)
        receipt["http_status"] = code
        receipt["final_url"] = resolved_url
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
            raise Blocked("HTTP_RESPONSE_BYTES_INVALID")
        digest = sha256(raw).hexdigest()
        receipt["response_sha256"] = digest
        _create_once(ledger / "raw" / (digest + ".bin"), raw)
        intended, arrived = urlsplit(url), urlsplit(resolved_url)
        if (arrived.scheme != "https" or arrived.hostname != HOST
                or arrived.path != intended.path or arrived.query != intended.query):
            raise Blocked("UNTRUSTED_SOURCE_REDIRECT")
        if code != 200:
            raise Blocked("OFFICIAL_HTTP_NON_200")
        parsed = parse_public_table(raw, issue)
        parsed.update({"source_url": resolved_url, "source_sha256": digest})
        path = ledger / "draws" / (issue + ".json")
        if path.exists():
            existing = _read_json(path)
            keys = ("game", "issue", "draw_date", "red_sorted", "blue_number",
                    "red_order", "red_ball_group", "blue_ball_group",
                    "order_evidence", "ball_group_evidence", "observation_class")
            if any(parsed.get(key) != existing.get(key) for key in keys):
                raise Blocked("DRAW_OBSERVATION_CONFLICT")
            receipt["status"] = "MATCHED_EXISTING_SORTED_ONLY"
        else:
            if not _create_once(path, _sealed_bytes(parsed)):
                raise Blocked("DRAW_CREATE_RACE")
            receipt["status"] = "RECORDED_SORTED_ONLY"
    except Exception as exc:
        receipt["status"] = "BLOCKED"
        receipt["reason"] = (str(exc) if isinstance(exc, Blocked)
                             else "NETWORK_OR_IO_FAILURE:" + type(exc).__name__)
    finally:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = ledger / "attempts" / issue / (stamp + "-" + uuid4().hex + ".json")
        _create_once(path, _sealed_bytes(receipt))
    return receipt


def _reject_duplicate_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Blocked("DUPLICATE_LEDGER_JSON_KEY")
        value[key] = item
    return value


def _read_json(path: Path) -> dict:
    item = json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=_reject_duplicate_pairs,
                      parse_constant=lambda token: (_ for _ in ()).throw(
                          Blocked("NONFINITE_LEDGER_NUMBER")))
    if not isinstance(item, dict):
        raise Blocked("INVALID_LEDGER_JSON_OBJECT")
    return item


def verify(ledger: Path) -> dict:
    count = 0
    seen_issues = set()
    for path in (ledger / "draws").glob("*.json"):
        row = _read_json(path)
        issue = row.get("issue")
        if not isinstance(issue, str) or path.name != issue + ".json":
            raise Blocked("DRAW_FILENAME_MISMATCH")
        if issue in seen_issues:
            raise Blocked("DUPLICATE_DRAW_ISSUE")
        seen_issues.add(issue)
        digest = row.get("source_sha256", "")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Blocked("SOURCE_HASH_INVALID")
        raw_path = ledger / "raw" / (digest + ".bin")
        if (not raw_path.is_file() or
                sha256(raw_path.read_bytes()).hexdigest() != digest):
            raise Blocked("MISSING_OR_TAMPERED_SOURCE_BYTES")
        parsed = parse_public_table(raw_path.read_bytes(), issue)
        # Compare canonical fields, including the explicit unknown physical fields.
        if any(row.get(key) != value for key, value in parsed.items()):
            raise Blocked("TAMPERED_DRAW_RECORD")
        if row.get("source_url") != URL:
            raise Blocked("SOURCE_URL_CONFLICT")
        count += 1
    attempts = 0
    for path in (ledger / "attempts").glob("*/*.json"):
        row = _read_json(path)
        if path.parent.name != row.get("issue") or row.get("schema") != PARSER:
            raise Blocked("ATTEMPT_IDENTITY_CONFLICT")
        digest = row.get("response_sha256")
        if digest is not None:
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise Blocked("ATTEMPT_HASH_INVALID")
            raw_path = ledger / "raw" / (digest + ".bin")
            if (not raw_path.is_file() or
                    sha256(raw_path.read_bytes()).hexdigest() != digest):
                raise Blocked("TAMPERED_ATTEMPT_SOURCE")
        attempts += 1
    return {"schema": PARSER, "game": "SSQ", "draws_verified": count,
            "attempts_verified": attempts,
            "physical_order_verified": 0, "ball_group_verified": 0,
            "formal_A": 0, "predictive_edge": "NO_EDGE"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.ledger), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.issue:
        parser.error("at least one explicit --issue required; do not infer future draws")
    failed = False
    for issue in args.issue:
        receipt = collect(issue, args.ledger)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        failed |= receipt["status"] == "BLOCKED"
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
