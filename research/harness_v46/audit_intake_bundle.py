"""Independent, read-only integrity audit for a saved V4.7 official-intake bundle.

This audit verifies byte preservation and admission guards only. It does not authenticate a
source's official origin, publication time, draw schedule, target issue, or prediction.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

from .core import MAX_RAW_SOURCE_BYTES, GateError

BUNDLE_SCHEMA = "V47-OFFICIAL-INTAKE-BUNDLE-1"
AUDIT_SCHEMA = "V47-INTAKE-BUNDLE-AUDIT-1"
# Audit source-root identity independently of the intake worker that authored the manifest.
SOURCE_IDS_BY_GAME = {
    "SSQ": frozenset({"national", "shanghai", "hebei"}),
    "DLT": frozenset({"national", "jiangsu", "gansu"}),
}


def _audit_request_bytes(game: str, source_id: str, artifact: dict, raw: bytes) -> None:
    """Independently bind fixed-route request bytes, including failed sources."""
    fields = {"request_method", "request_body_base64", "request_body_sha256"}
    endpoint = "https://www.gstc.org.cn/workapi/prize_history_list"
    present = fields.intersection(artifact)
    api = artifact.get("url") == endpoint or artifact.get("requested_url") == endpoint
    media_type = str(artifact.get("content_type") or "").split(";", 1)[0].strip().lower()
    json_response = game == "DLT" and source_id == "gansu" and (
        raw.lstrip()[:1] in (b"{", b"[") or media_type.rpartition("/")[2] == "json"
        or media_type.endswith("+json")
    )
    if "response_location" in artifact and not present:
        raise ValueError("orphan response location")
    if not present and not api and not json_response:
        return
    if (game != "DLT" or source_id != "gansu" or present != fields
            or artifact.get("url") != endpoint or artifact.get("requested_url") != endpoint
            or artifact.get("request_method") != "POST"):
        raise ValueError("request identity")
    body = base64.b64decode(artifact["request_body_base64"], validate=True)
    if hashlib.sha256(body).hexdigest() != artifact["request_body_sha256"]:
        raise ValueError("request SHA")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate request key")
            obj[key] = value
        return obj
    value = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {"type_id", "page_no", "page_size"}
            or value["type_id"] != "001" or type(value["page_no"]) is not int
            or not 1 <= value["page_no"] <= 7 or type(value["page_size"]) is not int
            or value["page_size"] != 20):
        raise ValueError("request schema")
    if "response_location" in artifact and not isinstance(artifact["response_location"], str):
        raise ValueError("response location")


def _physical_root(path: str | Path) -> Path:
    """Resolve and inspect Windows evidence through extended-length paths."""
    absolute = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        absolute = ("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\")
                    else "\\\\?\\" + absolute)
    return Path(absolute).resolve()


def _is_link_or_reparse_point(path: Path) -> bool:
    """Reject symlinks and Windows junctions under Python 3.11 alike."""
    try:
        if path.is_symlink():
            return True
        metadata = path.lstat()
    except OSError:
        return True
    return bool(getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _has_unsafe_path_component(root: Path, relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return any(_is_link_or_reparse_point(root / Path(*parts[:i]))
               for i in range(1, len(parts) + 1))


def _evidence_tree_entries(directory: Path, *, check=None, depth=0):
    """List untrusted evidence trees without traversing links or junctions."""
    if check is not None and depth > 32:
        raise GateError("AUDIT_DELEGATED_TREE_DEPTH_LIMIT")
    for child in directory.iterdir():
        if check is not None:
            check()
        yield child
        if not _is_link_or_reparse_point(child) and child.is_dir():
            yield from _evidence_tree_entries(child, check=check, depth=depth + 1)


def _iter_artifacts(bundle: dict):
    games = bundle.get("games", {})
    if not isinstance(games, dict):
        return
    for game, result in games.items():
        if not isinstance(result, dict):
            continue
        if result.get("status") == "WORKER_OUTPUT_QUARANTINED" or "worker_output_capture" in result:
            # Forensic process output cannot become HTTP records even if a
            # tampered manifest adds source-like fields or deletes the envelope.
            continue
        sources = result.get("sources", [])
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                artifacts = source.get("raw_artifacts", [])
                if isinstance(artifacts, list):
                    for artifact in artifacts:
                        if isinstance(artifact, dict):
                            yield game, str(source.get("source_id") or "unknown"), artifact
        for field in ("unadmitted_raw_artifacts", "transport_failures"):
            artifacts = result.get(field, [])
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if isinstance(artifact, dict):
                        yield game, str(
                            artifact.get("_source_id") or artifact.get("source_id") or "unknown"
                        ), artifact


def _audit_worker_captures(bundle: dict, root: Path, errors: list[str], *, read_bytes=None, check=None) -> dict:
    """Check process-output bytes independently; never count them as HTTP records."""
    records = verified = unavailable = 0
    paths: set[str] = set()
    incomplete_games = []
    games = bundle.get("games")
    if not isinstance(games, dict):
        return {"records": 0, "verified": 0, "unavailable": 0, "paths": paths,
                "incomplete_games": []}
    for game, result in games.items():
        if check is not None:
            check()
        if not isinstance(result, dict):
            continue
        if "worker_output_capture" not in result and result.get("status") != "WORKER_OUTPUT_QUARANTINED":
            continue
        # An arbitrary failed worker JSON must never be laundered into model
        # rows/HTTP artifacts by moving it into this diagnostic-only envelope.
        empty_fields = {
            "sources": [], "source_summaries": [], "source_count": 0,
            "unadmitted_raw_artifacts": [], "transport_failures": [],
            "raw_artifact_count": 0, "consensus_draws": [], "consensus_draw_count": 0,
            "primary_history_draws": [], "primary_history_draw_count": 0,
            "unverified_primary_history_draw_count": 0,
        }
        if (result.get("status") != "WORKER_OUTPUT_QUARANTINED"
                or result.get("history_validation_tier") != "UNVERIFIED_WORKER_OUTPUT"
                or result.get("official_history_admission") != "BLOCKED"
                or result.get("lottery") != game
                or result.get("source_origin_authenticity") != "NOT_VERIFIED"
                or result.get("publication_time_authenticity") != "NOT_VERIFIED"
                or result.get("parser_to_raw_binding") != "NOT_VERIFIED"
                or result.get("raw_byte_sha_validation") != "NOT_RUN_UNTRUSTED_PROCESS_OUTPUT"
                or any(result.get(name) != expected or type(result.get(name)) is not type(expected)
                       for name, expected in empty_fields.items())):
            errors.append(f"WORKER_OUTPUT_QUARANTINE_GUARD_INVALID:{game}")
        if "worker_output_capture" not in result:
            errors.append(f"WORKER_OUTPUT_CAPTURE_MISSING:{game}")
            continue
        capture = result["worker_output_capture"]
        if (game not in SOURCE_IDS_BY_GAME or not isinstance(capture, dict)
                or capture.get("schema") != "V47-UNTRUSTED-WORKER-OUTPUT-1"
                or capture.get("trust") != "UNTRUSTED_PROCESS_OUTPUT"
                or capture.get("raw_http_evidence") != "NOT_VALIDATED"
                or type(capture.get("capture_complete")) is not bool
                or (capture.get("returncode") is not None
                    and type(capture["returncode"]) is not int)
                or (capture.get("capture_complete") is True
                    and type(capture.get("returncode")) is not int)):
            errors.append(f"WORKER_OUTPUT_CAPTURE_SCHEMA_INVALID:{game}")
            continue
        if not capture["capture_complete"]:
            incomplete_games.append(game)
        streams = capture.get("streams")
        if (not isinstance(streams, list) or len(streams) != 2
                or any(not isinstance(stream, dict) for stream in streams)
                or any(not isinstance(stream.get("stream"), str) for stream in streams)
                or {stream.get("stream") for stream in streams} != {"stdout", "stderr"}):
            errors.append(f"WORKER_OUTPUT_STREAM_SET_INVALID:{game}")
            continue
        for stream in streams:
            if check is not None:
                check()
            records += 1
            name = stream["stream"]
            if stream.get("capture_status") == "NOT_CAPTURED":
                unavailable += 1
                if (set(stream) != {"stream", "capture_status"}
                        or capture["capture_complete"]):
                    errors.append(f"WORKER_OUTPUT_NOT_CAPTURED_CONFLICT:{game}:{name}")
                continue
            expected_keys = {"stream", "capture_status", "byte_representation",
                             "sha256", "size_bytes", "artifact_path"}
            if (set(stream) != expected_keys or stream.get("capture_status") != "CAPTURED"
                    or not isinstance(stream.get("byte_representation"), str)
                    or stream.get("byte_representation") not in {
                        "ORIGINAL_PIPE_BYTES", "UTF8_REENCODED_TEXT"}):
                errors.append(f"WORKER_OUTPUT_STREAM_SCHEMA_INVALID:{game}:{name}")
                continue
            sha, size, rel = stream["sha256"], stream["size_bytes"], stream["artifact_path"]
            if (not isinstance(sha, str) or len(sha) != 64
                    or any(c not in "0123456789abcdef" for c in sha)
                    or type(size) is not int or size < 0):
                errors.append(f"WORKER_OUTPUT_BYTES_METADATA_INVALID:{game}:{name}")
                continue
            canonical = f"diagnostics/{game}/worker/{name}/{sha}.bin"
            if not isinstance(rel, str) or rel != canonical:
                errors.append(f"WORKER_OUTPUT_NONCANONICAL_PATH:{game}:{name}")
                continue
            unresolved = root / Path(*PurePosixPath(rel).parts)
            if _has_unsafe_path_component(root, rel):
                errors.append(f"WORKER_OUTPUT_FILE_UNSAFE_OR_MISSING:{game}:{name}")
                continue
            try:
                candidate = unresolved.resolve()
            except (OSError, RuntimeError):
                errors.append(f"WORKER_OUTPUT_FILE_UNSAFE_OR_MISSING:{game}:{name}")
                continue
            if not candidate.is_relative_to(root) or not candidate.is_file():
                errors.append(f"WORKER_OUTPUT_FILE_UNSAFE_OR_MISSING:{game}:{name}")
                continue
            try:
                raw = candidate.read_bytes() if read_bytes is None else read_bytes(candidate)
            except OSError:
                errors.append(f"WORKER_OUTPUT_FILE_UNREADABLE:{game}:{name}")
                continue
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
                errors.append(f"WORKER_OUTPUT_BYTES_MISMATCH:{game}:{name}")
                continue
            verified += 1
            paths.add(rel)
    return {"records": records, "verified": verified, "unavailable": unavailable,
            "paths": paths, "incomplete_games": incomplete_games}


def audit_bundle(bundle_dir: str | Path, *, read_bytes=None, check=None) -> dict:
    """Return an audit receipt; never modify the intake manifest or raw source bytes."""
    root = _physical_root(bundle_dir)
    if check is not None:
        check()
    manifest_path = root / "intake.json"
    errors: list[str] = []
    bundle = None
    manifest_sha256 = None
    if not manifest_path.is_file():
        errors.append("INTAKE_MANIFEST_MISSING")
    else:
        raw_manifest = manifest_path.read_bytes() if read_bytes is None else read_bytes(manifest_path)
        manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
        try:
            bundle = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append("INTAKE_MANIFEST_INVALID_JSON")

    if isinstance(bundle, dict):
        if bundle.get("schema") != BUNDLE_SCHEMA:
            errors.append("INTAKE_BUNDLE_SCHEMA_MISMATCH")
        if type(bundle.get("formal_A")) is not int or bundle.get("formal_A") != 0:
            errors.append("FORMAL_A_NOT_ZERO")
        if bundle.get("official_target_admission") != "BLOCKED":
            errors.append("OFFICIAL_TARGET_ADMISSION_NOT_BLOCKED")
        if bundle.get("external_tsa") != "NOT_RUN":
            errors.append("EXTERNAL_TSA_STATUS_NOT_NOT_RUN")
        if bundle.get("decision") != "NO_EDGE":
            errors.append("DECISION_NOT_NO_EDGE")
        if not isinstance(bundle.get("games"), dict):
            errors.append("GAMES_FIELD_INVALID")
        elif not bundle["games"]:
            errors.append("GAMES_EMPTY")
        elif not set(bundle["games"]).issubset({"SSQ", "DLT"}):
            errors.append("UNKNOWN_GAME_IN_BUNDLE")
        else:
            for game, result in bundle["games"].items():
                if not isinstance(result, dict):
                    errors.append(f"GAME_RESULT_INVALID:{game}")
                    continue
                if type(result.get("formal_A")) is not int or result.get("formal_A") != 0:
                    errors.append(f"GAME_FORMAL_A_NOT_ZERO:{game}")
                if result.get("official_target_admission") != "BLOCKED":
                    errors.append(f"GAME_TARGET_ADMISSION_NOT_BLOCKED:{game}")
                if result.get("external_tsa") != "NOT_RUN":
                    errors.append(f"GAME_EXTERNAL_TSA_STATUS_NOT_NOT_RUN:{game}")
                if result.get("decision") != "NO_EDGE":
                    errors.append(f"GAME_DECISION_NOT_NO_EDGE:{game}")

    artifact_records = 0
    verified_records = 0
    unique_paths: set[str] = set()
    diagnostic_http_responses = 0
    unpreserved_oversized_records = 0
    if isinstance(bundle, dict):
        for game, source_id, artifact in _iter_artifacts(bundle):
            if check is not None:
                check()
            artifact_records += 1
            if game not in SOURCE_IDS_BY_GAME or source_id not in SOURCE_IDS_BY_GAME[game]:
                errors.append(f"RAW_ARTIFACT_SOURCE_ID_INVALID:{game}:{source_id}")
                continue
            status = artifact.get("http_status")
            if type(status) is int and status != 200:
                diagnostic_http_responses += 1

            rel = artifact.get("artifact_path")
            body_preserved = artifact.get("body_preserved")
            size = artifact.get("size_bytes")
            expected_sha = artifact.get("raw_sha256")

            if rel is None and body_preserved is False and type(size) is int and size > MAX_RAW_SOURCE_BYTES:
                # A payload too large to retain is incomplete byte evidence: record
                # the limitation but never certify a fully preserved raw bundle.
                unpreserved_oversized_records += 1
                errors.append(f"RAW_ARTIFACT_UNPRESERVED_OVERSIZED:{game}:{source_id}")
                continue
            if not isinstance(rel, str) or not rel:
                errors.append(f"RAW_ARTIFACT_PATH_MISSING:{game}:{source_id}")
                continue
            pure = PurePosixPath(rel)
            if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
                errors.append(f"RAW_ARTIFACT_PATH_UNSAFE:{game}:{source_id}:{rel}")
                continue
            if not isinstance(expected_sha, str) or len(expected_sha) != 64 or any(
                c not in "0123456789abcdef" for c in expected_sha
            ):
                errors.append(f"RAW_ARTIFACT_SHA_INVALID:{game}:{source_id}:{rel}")
                continue
            # SHA equality alone is not enough: require provenance in the
            # untrusted manifest to match the exact path generated by write_bundle.
            canonical_path = (
                PurePosixPath("raw") / game / source_id / (expected_sha + ".bin")
            )
            if pure != canonical_path:
                errors.append(f"RAW_ARTIFACT_NONCANONICAL_SOURCE_PATH:{game}:{source_id}:{rel}")
                continue
            unresolved = root / Path(*pure.parts)
            if _has_unsafe_path_component(root, rel):
                errors.append(f"RAW_ARTIFACT_LINK_OR_REPARSE_POINT_NOT_ALLOWED:{game}:{source_id}:{rel}")
                continue
            candidate = unresolved.resolve()
            if not candidate.is_relative_to(root) or candidate == root:
                errors.append(f"RAW_ARTIFACT_PATH_ESCAPES_BUNDLE:{game}:{source_id}:{rel}")
                continue
            if not candidate.is_file():
                errors.append(f"RAW_ARTIFACT_FILE_MISSING:{game}:{source_id}:{rel}")
                continue
            if type(size) is not int or size < 0:
                errors.append(f"RAW_ARTIFACT_SIZE_INVALID:{game}:{source_id}:{rel}")
                continue
            raw = candidate.read_bytes() if read_bytes is None else read_bytes(candidate)
            if len(raw) != size:
                errors.append(f"RAW_ARTIFACT_SIZE_MISMATCH:{game}:{source_id}:{rel}")
                continue
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                errors.append(f"RAW_ARTIFACT_SHA256_MISMATCH:{game}:{source_id}:{rel}")
                continue
            try:
                _audit_request_bytes(game, source_id, artifact, raw)
            except (ValueError, TypeError, UnicodeError):
                errors.append(f"RAW_ARTIFACT_POST_REQUEST_INVALID:{game}:{source_id}:{rel}")
                continue
            if body_preserved is False:
                errors.append(f"RAW_ARTIFACT_PRESERVATION_FLAG_CONFLICT:{game}:{source_id}:{rel}")
                continue
            unique_paths.add(rel)
            verified_records += 1

    diagnostic = _audit_worker_captures(bundle, root, errors, read_bytes=read_bytes, check=check) if isinstance(bundle, dict) else {
        "records": 0, "verified": 0, "unavailable": 0, "paths": set(), "incomplete_games": []
    }
    if artifact_records == 0 and diagnostic["verified"] == 0:
        errors.append("NO_RAW_ARTIFACT_RECORDS_FOUND")

    # Detect unlisted SHA-named files even when every referenced manifest
    # entry matches; an archive should not silently carry extra draw-like bytes.
    raw_dir = root / "raw"
    if raw_dir.exists():
        if _is_link_or_reparse_point(raw_dir):
            errors.append("LINK_OR_REPARSE_POINT_IN_RAW_EVIDENCE_TREE:raw")
        else:
            for raw_file in _evidence_tree_entries(raw_dir, check=check):
                rel = raw_file.relative_to(root).as_posix()
                if _is_link_or_reparse_point(raw_file):
                    errors.append(f"LINK_OR_REPARSE_POINT_IN_RAW_EVIDENCE_TREE:{rel}")
                elif raw_file.is_file() and rel not in unique_paths:
                    errors.append(f"UNREFERENCED_RAW_ARTIFACT:{rel}")

    diagnostic_dir = root / "diagnostics"
    if diagnostic_dir.exists():
        if _is_link_or_reparse_point(diagnostic_dir):
            errors.append("LINK_OR_REPARSE_POINT_IN_WORKER_OUTPUT_TREE:diagnostics")
        else:
            for saved in _evidence_tree_entries(diagnostic_dir, check=check):
                rel = saved.relative_to(root).as_posix()
                if _is_link_or_reparse_point(saved):
                    errors.append(f"LINK_OR_REPARSE_POINT_IN_WORKER_OUTPUT_TREE:{rel}")
                elif saved.is_file() and rel not in diagnostic["paths"]:
                    errors.append(f"UNREFERENCED_WORKER_OUTPUT_FILE:{rel}")

    return {
        "schema": AUDIT_SCHEMA,
        "auditor_source_sha256": hashlib.sha256(Path(__file__).read_bytes() if read_bytes is None else read_bytes(Path(__file__))).hexdigest(),
        "status": "PASS" if not errors else "FAIL",
        "purpose": "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY",
        "bundle_manifest_sha256": manifest_sha256,
        "artifact_records": artifact_records,
        "verified_artifact_records": verified_records,
        "unique_raw_file_paths": len(unique_paths),
        "diagnostic_non_200_responses": diagnostic_http_responses,
        "unpreserved_oversized_records": unpreserved_oversized_records,
        "worker_output_stream_records": diagnostic["records"],
        "verified_worker_output_stream_records": diagnostic["verified"],
        "unavailable_worker_output_streams": diagnostic["unavailable"],
        "incomplete_worker_output_games": diagnostic["incomplete_games"],
        "worker_output_validation_scope": "PROCESS_OUTPUT_BYTES_ONLY_HTTP_CLAIMS_UNVALIDATED",
        "worker_output_limitations": [
            "Diagnostic stream hashes certify preserved process output only, never embedded HTTP, source, row or timestamp claims.",
            "Incomplete captures cannot recover HTTP bytes that the worker never emitted before timeout or termination.",
        ] if diagnostic["records"] else [],
        "http_raw_evidence_status": (
            "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY" if artifact_records
            else "NOT_PRESENT_OR_UNVALIDATED_PROCESS_OUTPUT_ONLY"
        ),
        "admission_guard": {
            "official_target_admission": "BLOCKED",
            "external_tsa": "NOT_RUN",
            "formal_A": 0,
            "decision": "NO_EDGE",
        },
        "errors": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, help="Directory containing intake.json and raw/")
    args = parser.parse_args(argv)
    root = _physical_root(args.bundle_dir)
    root.mkdir(parents=True, exist_ok=True)
    report = audit_bundle(root)
    output = root / "intake-audit.json"
    # Raw artifacts and audit receipts are write-once; never erase an earlier
    # failed audit or replace a previously recorded auditor-source hash.
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
