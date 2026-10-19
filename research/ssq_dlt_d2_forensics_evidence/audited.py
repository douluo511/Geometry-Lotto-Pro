"""Durable, fail-closed custody for the unchanged scientific verifier.

The START and before manifests are fsynced before verification.  Every handled
failure receives after manifests and a failure receipt.  An interrupted process
without a terminal receipt remains INCOMPLETE.  This is local audit evidence,
not an external timestamp, lottery experiment, or proof of predictive skill.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
import traceback
import uuid

from . import verify


SCHEMA = "D2_DURABLE_VERIFICATION_SESSION_1"
NATIVE_PASS = "PASS_SEMANTIC_PRESENTATION_ADAPTER_WITH_NATIVE_INTEGRITY_CHECKS"
AUDITED_PASS = "PASS_AUDITED_VERIFICATION_NOT_PREDICTIVE_EDGE"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def _write_new(path, value):
    """No replacement or partial success claims; file contents reach fsync."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _parse(path):
    return verify.frozen_protocol.parse(Path(path).read_bytes())


def _error(exc, *, _seen=None, _depth=0):
    # Exception causes/contexts are writable and can contain cycles.  Failure
    # reporting must not itself recurse forever and erase the primary failure.
    seen = set() if _seen is None else _seen
    try:
        message = str(exc)
    except BaseException as formatting_error:
        message = "<str() raised " + type(formatting_error).__name__ + ">"
    value = {"type": type(exc).__name__, "message": message}
    if id(exc) in seen or _depth >= 32:
        value["truncated"] = ("EXCEPTION_REFERENCE_ALREADY_RECORDED" if id(exc) in seen
                              else "EXCEPTION_DEPTH_LIMIT_32")
        return value
    seen.add(id(exc))
    try:
        value["traceback"] = "".join(traceback.format_exception(exc))
    except BaseException as formatting_error:
        value["traceback"] = "<traceback formatting raised " + type(formatting_error).__name__ + ">"
    if isinstance(exc, BaseExceptionGroup):
        value["exceptions"] = [_error(item, _seen=seen, _depth=_depth + 1) for item in exc.exceptions]
    if exc.__cause__ is not None:
        value["cause"] = _error(exc.__cause__, _seen=seen, _depth=_depth + 1)
    elif exc.__context__ is not None and not exc.__suppress_context__:
        value["context"] = _error(exc.__context__, _seen=seen, _depth=_depth + 1)
    return value


def _snapshot(directory, *, only_python=False):
    """Hash bytes without following symlinks/junctions or opening SQLite."""
    directory = Path(directory)
    files, errors = {}, []
    if not directory.is_dir():
        return {"files": {}, "errors": [{"path": ".", "error": "DIRECTORY_REQUIRED"}]}

    def visit(where):
        try:
            entries = sorted(os.scandir(where), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append({"path": Path(where).relative_to(directory).as_posix(), "error": _error(exc)})
            return
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(directory).as_posix()
            if only_python and entry.name == "__pycache__":
                continue
            try:
                # Windows DirEntry may cache st_ino=0 from directory enumeration;
                # compare two actual path stat calls rather than that cache.
                before = path.stat(follow_symlinks=False)
                if stat.S_ISLNK(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
                    errors.append({"path": relative, "error": "REPARSE_POINT_REFUSED"})
                    files[relative] = {"kind": "reparse_point"}
                elif stat.S_ISDIR(before.st_mode):
                    if not only_python:
                        files[relative] = {"kind": "directory"}
                    visit(path)
                elif stat.S_ISREG(before.st_mode):
                    if only_python and path.suffix != ".py":
                        continue
                    checksum = _sha(path)
                    after = path.stat(follow_symlinks=False)
                    files[relative] = {"kind": "file", "size": after.st_size, "sha256": checksum}
                    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                        errors.append({"path": relative, "error": "FILE_CHANGED_WHILE_HASHING"})
                else:
                    files[relative] = {"kind": "unsupported"}
                    errors.append({"path": relative, "error": "UNSUPPORTED_FILE_KIND"})
            except OSError as exc:
                errors.append({"path": relative, "error": _error(exc)})

    visit(directory)
    return {"files": files, "errors": errors}


def source_snapshot():
    """Science, adapter, audit CLI, and tests; additions/deletions are visible."""
    root = Path(verify.frozen_protocol.ROOT)
    files, errors = {}, []
    for namespace in ("ssq_dlt_d2_forensics", "ssq_dlt_d2_next", "ssq_dlt_v45",
                      "ssq_dlt_d2_forensics_evidence"):
        prefix = "research/" + namespace + "/"
        snapshot = _snapshot(root / "research" / namespace, only_python=True)
        files.update({prefix + key: value for key, value in snapshot["files"].items()})
        errors.extend({"path": prefix + row["path"], "error": row["error"]} for row in snapshot["errors"])
    return {"files": files, "errors": errors}


def _capture(callback):
    try:
        value = callback()
        if not isinstance(value, dict) or set(value) != {"files", "errors"}:
            raise ValueError("SNAPSHOT_SCHEMA_REQUIRED")
        return value
    except BaseException as exc:
        return {"files": {}, "errors": [{"path": ".", "error": _error(exc)}]}


def _diff(before, after):
    left, right = before["files"], after["files"]
    return {"added": {key: right[key] for key in sorted(right.keys() - left.keys())},
            "removed": {key: left[key] for key in sorted(left.keys() - right.keys())},
            "modified": {key: {"before": left[key], "after": right[key]}
                         for key in sorted(left.keys() & right.keys()) if left[key] != right[key]}}


def _pin_check(study, sources):
    try:
        pins = _parse(Path(study) / "plan.json")["source_sha256"]
        if not isinstance(pins, dict) or not pins:
            raise ValueError("NONEMPTY_FROZEN_SOURCE_PINS_REQUIRED")
        mismatches = {key: {"expected": expected, "actual": sources["files"].get(key)}
                      for key, expected in pins.items()
                      if sources["files"].get(key, {}).get("sha256") != expected}
        return {"status": "PASS" if not mismatches else "FAIL", "count": len(pins), "mismatches": mismatches}
    except BaseException as exc:
        return {"status": "FAIL", "error": _error(exc)}


def _safe_session(study, session):
    # Reject a whole study-parent subtree as well as study ancestors.  No
    # journal file can become an input of this or the surrounding old study.
    if session.is_relative_to(study.parent) or study.is_relative_to(session):
        raise ValueError("SESSION_MUST_BE_OUTSIDE_STUDY_PARENT_SUBTREE_AND_ANCESTORS")
    if not session.parent.is_dir():
        raise ValueError("SESSION_PARENT_MUST_EXIST")


def _passed(before, after, input_diff, source_diff, errors, native):
    return (not errors and not before["inputs"]["errors"] and not before["sources"]["errors"]
            and not after["inputs"]["errors"] and not after["sources"]["errors"]
            and before["frozen_source_pins"]["status"] == "PASS"
            and after["frozen_source_pins"]["status"] == "PASS"
            and not any(input_diff.values()) and not any(source_diff.values())
            and isinstance(native, dict) and native.get("status") == NATIVE_PASS)


def audit(study, session, *, verifier=None, source_provider=None):
    """Persist a full session; handled operation failures return FAIL receipts.

    Unsafe output paths/existing sessions are rejected before any write.  An
    unwritable journal or an uncatchable process termination cannot manufacture
    a terminal receipt.  ``inspect`` keeps such a session INCOMPLETE.
    Dependency injection is for tiny synthetic tests and is labeled explicitly.
    """
    study, session = Path(study).resolve(), Path(session).resolve()
    _safe_session(study, session)
    session.mkdir(exist_ok=False)
    injected = verifier is not None or source_provider is not None
    operation = verifier or verify.verify_study
    provider = source_provider or source_snapshot
    start = {"schema": SCHEMA, "status": "INCOMPLETE", "started_at": _now(),
             "run_id": str(uuid.uuid4()), "study": str(study), "session": str(session),
             "python": sys.version, "os": platform.platform(), "formal_A": 0, "decision": "NO_EDGE",
             "timestamp_custody": "LOCAL_ONLY_NOT_EXTERNAL_TSA",
             "injected_dependencies": injected,
             "experiment_rerun": False, "original_sqlite_opened_by_journal": False,
             "durability": "EACH_RECORD_FLUSH_AND_FILE_FSYNC; DIRECTORY_FSYNC_NOT_CLAIMED"}
    _write_new(session / "START.json", start)
    before = {"recorded_at": _now(), "inputs": _capture(lambda: _snapshot(study)),
              "sources": _capture(provider)}
    before["frozen_source_pins"] = _pin_check(study, before["sources"])
    _write_new(session / "before.json", before)
    native, errors = None, []
    native_path = session / "native-verification.json"
    try:
        if before["inputs"]["errors"] or before["sources"]["errors"]:
            raise ValueError("BEFORE_MANIFEST_INCOMPLETE_OR_UNSAFE")
        if before["frozen_source_pins"]["status"] != "PASS":
            raise ValueError("FROZEN_SOURCE_PIN_MISMATCH_BEFORE_VERIFICATION")
        native = operation(study, native_path)
        if not native_path.is_file() or _parse(native_path) != native:
            raise ValueError("NATIVE_RECEIPT_MISSING_OR_RETURN_MISMATCH")
        if native.get("status") != NATIVE_PASS:
            raise ValueError("NATIVE_VERIFIER_DID_NOT_PASS")
    except BaseException as exc:
        errors.append(_error(exc))
    after = {"recorded_at": _now(), "inputs": _capture(lambda: _snapshot(study)),
             "sources": _capture(provider)}
    after["frozen_source_pins"] = _pin_check(study, after["sources"])
    _write_new(session / "after.json", after)
    input_diff, source_diff = _diff(before["inputs"], after["inputs"]), _diff(before["sources"], after["sources"])
    passed = _passed(before, after, input_diff, source_diff, errors, native)
    receipt = {"schema": SCHEMA, "status": AUDITED_PASS if passed else "FAIL", "completed_at": _now(),
               "run_id": start["run_id"], "study": str(study), "session": str(session),
               "start_sha256": _sha(session / "START.json"), "before_sha256": _sha(session / "before.json"),
               "after_sha256": _sha(session / "after.json"), "input_diff": input_diff, "source_diff": source_diff,
               "errors": errors, "native_result": native,
               "native_receipt_sha256": _sha(native_path) if native_path.is_file() else None,
               "all_inputs_unchanged": before["inputs"] == after["inputs"],
               "all_sources_unchanged": before["sources"] == after["sources"],
               "injected_dependencies": injected, "formal_A": 0, "decision": "NO_EDGE",
               "qualified_prospective_samples_added": 0, "experiment_rerun": False,
               "original_sqlite_opened_by_journal": False,
               "scope": "DURABLE_VERIFICATION_CUSTODY_ONLY_NOT_LOTTERY_IMPROVEMENT",
               "limits": ["Local file hashes are not external timestamp or tamper-proof custody.",
                          "Hard power loss and malicious operating-system behavior are not tested.",
                          "An interrupted run without a complete receipt stays INCOMPLETE.",
                          "Before/after hashes cannot detect a transient change restored between snapshots."]}
    _write_new(session / "receipt.json", receipt)
    return receipt


def inspect(session):
    """Read only.  Missing terminal records never become PASS."""
    session = Path(session).resolve()
    try:
        start = _parse(session / "START.json")
    except (OSError, ValueError) as exc:
        return {"status": "INCOMPLETE", "reason": "START_MISSING_OR_UNREADABLE", "error": _error(exc)}
    required = [session / name for name in ("before.json", "after.json", "receipt.json")]
    if not all(path.is_file() for path in required):
        return {"status": "INCOMPLETE", "reason": "TERMINAL_RECORDS_MISSING",
                "missing": [path.name for path in required if not path.is_file()], "run_id": start.get("run_id")}
    try:
        before, after, receipt = (_parse(path) for path in required)
        if start.get("schema") != SCHEMA or start.get("status") != "INCOMPLETE" or receipt.get("schema") != SCHEMA:
            raise ValueError("SESSION_SCHEMA_OR_START_STATUS_MISMATCH")
        for key, name in (("start_sha256", "START.json"), ("before_sha256", "before.json"), ("after_sha256", "after.json")):
            if receipt[key] != _sha(session / name):
                raise ValueError("JOURNAL_SHA_MISMATCH " + name)
        if start["run_id"] != receipt["run_id"]:
            raise ValueError("SESSION_RUN_ID_MISMATCH")
        input_diff, source_diff = _diff(before["inputs"], after["inputs"]), _diff(before["sources"], after["sources"])
        if input_diff != receipt["input_diff"] or source_diff != receipt["source_diff"]:
            raise ValueError("JOURNAL_DIFF_MISMATCH")
        native_path = session / "native-verification.json"
        if receipt["native_receipt_sha256"] is not None:
            if _sha(native_path) != receipt["native_receipt_sha256"] or _parse(native_path) != receipt["native_result"]:
                raise ValueError("NATIVE_RECEIPT_SHA_OR_RETURN_MISMATCH")
        elif receipt["status"] == AUDITED_PASS:
            raise ValueError("PASS_REQUIRES_NATIVE_RECEIPT")
        expected = AUDITED_PASS if _passed(before, after, input_diff, source_diff, receipt["errors"], receipt["native_result"]) else "FAIL"
        if receipt["status"] != expected:
            raise ValueError("TERMINAL_STATUS_NOT_DERIVED_FROM_EVIDENCE")
        return {"status": receipt["status"], "receipt_sha256": _sha(session / "receipt.json"),
                "run_id": start["run_id"], "read_only_inspection": True,
                "injected_dependencies": start["injected_dependencies"], "formal_A": 0, "decision": "NO_EDGE"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "FAIL", "reason": "JOURNAL_INTEGRITY_OR_SCHEMA_FAILURE", "error": _error(exc),
                "read_only_inspection": True, "formal_A": 0, "decision": "NO_EDGE"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("audit")
    run.add_argument("--study", required=True, type=Path)
    run.add_argument("--session", required=True, type=Path)
    read = commands.add_parser("inspect")
    read.add_argument("--session", required=True, type=Path)
    args = parser.parse_args(argv)
    answer = audit(args.study, args.session) if args.command == "audit" else inspect(args.session)
    print(json.dumps({key: answer[key] for key in ("status", "formal_A", "decision") if key in answer}, ensure_ascii=False))
    return 0 if answer["status"] == AUDITED_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
