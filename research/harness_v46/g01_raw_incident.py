"""G01 official-history incident triage from archived RAW HTTP bytes only.

This tool audits *one saved local zip*. It makes NO web request, authorizes
NO official source, fixes NO dates, cannot see data not retained in the zip,
and NEVER admits past or future forecasting evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath

from .core import GateError, digest

REPORT_SCHEMA = "V47-G01-RAW-INCIDENT-REPORT-1"
MANIFEST = "intake.json"
AUDIT = "intake-audit.json"
MAX_ENTRIES = 256
MAX_ENTRY_BYTES = 25_000_000
MAX_TOTAL_BYTES = 90_000_000
ISSUE_ROW = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
    r"<td[^>]*>\s*(\d{5})\s*</td>\s*"
    r"<td[^>]*>\s*([\d\s]+?)\s*</td>",
    re.IGNORECASE | re.DOTALL,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_checked(z: zipfile.ZipFile, key: str, *, max_bytes=MAX_ENTRY_BYTES) -> bytes:
    try:
        info = z.getinfo(key)
        if info.is_dir() or info.file_size > max_bytes:
            raise GateError("INVALID_OR_OVERSIZED_ARCHIVE_MEMBER")
        with z.open(info) as file:
            value = file.read(max_bytes + 1)
    except KeyError as exc:
        raise GateError("MISSING_RAW_ARTIFACT" if key.startswith("raw/") else
                        "MISSING_G01_MANIFEST") from exc
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise GateError("RAW_ARCHIVE_UNREADABLE") from exc
    if len(value) > max_bytes:
        raise GateError("INVALID_OR_OVERSIZED_ARCHIVE_MEMBER")
    return value


def _load_json(data: bytes) -> dict:
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise GateError("INVALID_G01_JSON_MANIFEST") from exc
    if not isinstance(value, dict):
        raise GateError("INVALID_G01_JSON_MANIFEST")
    return value


def _all_members(z: zipfile.ZipFile) -> set[str]:
    info = z.infolist()
    if len(info) > MAX_ENTRIES or sum(i.file_size for i in info) > MAX_TOTAL_BYTES:
        raise GateError("G01_ARCHIVE_EXCEEDS_BOUNDS")
    names = [i.filename for i in info]
    if len(set(names)) != len(names):
        raise GateError("DUPLICATE_ARCHIVE_MEMBER")
    for name in names:
        p = PurePosixPath(name)
        if (p.is_absolute() or not p.parts or
                any(x in ("", ".", "..") for x in p.parts) or "\\" in name):
            raise GateError("INVALID_ARCHIVE_MEMBER_PATH")
    return set(names)


def _jiangsu_rows(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise GateError("JIANGSU_RAW_HTML_ENCODING_UNKNOWN") from exc
    text = html.unescape(text)
    matches = ISSUE_ROW.findall(text)
    return [(issue, day, " ".join(numbers.split()))
            for day, issue, numbers in matches]


def _date_incidents(rows: dict[str, dict]) -> list[dict]:
    incidents = []
    prior_issue, prior_day = None, None
    for issue in sorted(rows, key=int):
        item = rows[issue]
        day = item["draw_date"]
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            incidents.append({"lottery": "DLT", "source_id": "jiangsu",
                              "issue": issue, "draw_date": day,
                              "reason": "INVALID_DATE_IN_RAW_HTML",
                              "raw_sha256": item["raw_sha256"]})
            continue
        base = {"lottery": "DLT", "source_id": "jiangsu", "issue": issue,
                "draw_date": day, "raw_sha256": item["raw_sha256"]}
        if parsed.weekday() not in (0, 2, 5):
            incidents.append({**base, "reason": "NON_REGULAR_DRAW_WEEKDAY"})
        if prior_day is not None:
            previous = date.fromisoformat(prior_day)
            if parsed == previous:
                incidents.append({**base, "reason": "DRAW_DATE_REPEATED_ACROSS_ISSUES",
                                  "other_issue": prior_issue})
            elif parsed < previous:
                incidents.append({**base, "reason": "DRAW_DATE_REVERSED_ACROSS_ISSUES",
                                  "other_issue": prior_issue})
        prior_issue, prior_day = issue, day
    return incidents


def analyze_zip(intake_zip: str | Path) -> dict:
    """Replay archive checks fail-closed, never update original zip or draw data."""
    path = Path(intake_zip)
    try:
        archive_bytes = path.read_bytes()
    except OSError as exc:
        raise GateError("G01_ARCHIVE_FILE_NOT_READABLE") from exc
    if not archive_bytes or len(archive_bytes) > MAX_TOTAL_BYTES:
        raise GateError("G01_ARCHIVE_EXCEEDS_BOUNDS")
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise GateError("G01_ARCHIVE_NOT_ZIP") from exc
    with z:
        members = _all_members(z)
        intake_bytes = _read_checked(z, MANIFEST)
        audit = _load_json(_read_checked(z, AUDIT))
        intake = _load_json(intake_bytes)
        if audit.get("schema") != "V47-INTAKE-BUNDLE-AUDIT-1":
            raise GateError("G01_ARCHIVE_AUDIT_SCHEMA_MISMATCH")
        if (audit.get("status") != "PASS" or audit.get("errors") != [] or
                audit.get("bundle_manifest_sha256") != _sha(intake_bytes)):
            raise GateError("G01_ARCHIVE_AUDIT_OR_BUNDLE_MISMATCH")
        if (intake.get("formal_A") != 0 or intake.get("decision") != "NO_EDGE" or
                intake.get("official_target_admission") != "BLOCKED"):
            raise GateError("RAW_ARCHIVE_FORMAL_ADMISSION_FORBIDDEN")
        games = intake.get("games")
        if not isinstance(games, dict) or set(games) != {"SSQ", "DLT"}:
            raise GateError("G01_ARCHIVE_TWO_GAMES_REQUIRED")
        source_status = {}
        declared = set()
        http_incidents = []
        jiangsu = {}
        for game in ("SSQ", "DLT"):
            data = games[game]
            if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
                raise GateError("INVALID_G01_ARCHIVED_SOURCE_SCHEMA")
            source_status[game] = data.get("status")
            if (data.get("formal_A") != 0 or data.get("decision") != "NO_EDGE"
                    or not str(data.get("official_history_admission", "")).startswith("BLOCKED")):
                raise GateError("RAW_ARCHIVE_FORMAL_ADMISSION_FORBIDDEN")
            for source in data["sources"]:
                source_id = source.get("source_id")
                artifacts = source.get("raw_artifacts")
                if (not isinstance(source_id, str) or not source_id or
                        not isinstance(artifacts, list)):
                    raise GateError("INVALID_G01_ARCHIVED_SOURCE_SCHEMA")
                for meta in artifacts:
                    raw_path = meta.get("artifact_path")
                    sha = meta.get("raw_sha256")
                    expected = f"raw/{game}/{source_id}/{sha}.bin"
                    if (not isinstance(raw_path, str) or raw_path != expected or
                            not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha)
                            or raw_path in declared):
                        raise GateError("G01_ARCHIVE_RAW_ARTIFACT_IDENTITY_CONFLICT")
                    declared.add(raw_path)
                    if raw_path not in members:
                        raise GateError("MISSING_RAW_ARTIFACT")
                    raw = _read_checked(z, raw_path)
                    if _sha(raw) != sha or len(raw) != meta.get("size_bytes"):
                        raise GateError("RAW_ARTIFACT_SHA_MISMATCH")
                    status = meta.get("http_status")
                    if type(status) is not int:
                        raise GateError("INVALID_G01_RAW_HTTP_STATUS")
                    if status != 200:
                        http_incidents.append({
                            "lottery": game, "source_id": source_id,
                            "http_status": status,
                            "raw_sha256": sha, "raw_size_bytes": len(raw),
                            "requested_url": meta.get("requested_url", meta.get("url"))
                        })
                    if game == "DLT" and source_id == "jiangsu" and status == 200:
                        for issue, day, numbers in _jiangsu_rows(raw):
                            item = {"draw_date": day, "balls_verbatim": numbers,
                                    "raw_sha256": sha}
                            if issue in jiangsu and jiangsu[issue]["draw_date"] != day:
                                raise GateError("JIANGSU_ISSUE_CONFLICT_IN_ARCHIVED_PAGES")
                            jiangsu.setdefault(issue, item)
        raw_members = {x for x in members if x.startswith("raw/")}
        if raw_members != declared:
            raise GateError("G01_ARCHIVE_UNDECLARED_OR_MISSING_RAW_FILES")
        count = len(declared)
        if any(audit.get(k) != count for k in
               ("artifact_records", "verified_artifact_records", "unique_raw_file_paths")):
            raise GateError("G01_ARCHIVE_AUDIT_RAW_COUNT_CONFLICT")
    result = {
        "schema": REPORT_SCHEMA,
        "zip_sha256": _sha(archive_bytes),
        "intake_manifest_sha256": _sha(intake_bytes),
        "raw_artifact_count": count,
        "raw_integrity": "PASS_ALL_ARCHIVED_BYTES",
        "source_status": source_status,
        "http_incidents": sorted(http_incidents,
                                 key=lambda x: (x["lottery"], x["source_id"], x["raw_sha256"])),
        "calendar_incidents": _date_incidents(jiangsu),
        "jiangsu_raw_issue_rows_seen": len(jiangsu),
        "independent_source_authentication": False,
        "confirmed_corrected_draw_dates": False,
        "official_history_admission": "BLOCKED",
        "qualified_prospective": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
        "limitations": [
            "Bytes/checksums do not independently authenticate HTTPS source identity or historical publication time.",
            "Calendar conflicts are incident diagnoses only; do not silently rewrite official raw rows.",
            "Reported source statuses come from a single saved collector manifest, not an independent official consensus.",
            "No historical official G01 admission, authentic future draw schedule, external TSA, or lottery prediction advantage is established."
        ],
    }
    result["report_sha256"] = digest(result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only G01 ZIP raw-incident replay")
    parser.add_argument("--intake-zip", required=True)
    args = parser.parse_args(argv)
    try:
        result = analyze_zip(args.intake_zip)
    except (GateError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
