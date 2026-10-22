"""Independent, read-only integrity audit for a saved V4.7 official-intake bundle.

This audit verifies byte preservation and admission guards only. It does not authenticate a
source's official origin, publication time, draw schedule, target issue, or prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from .core import MAX_RAW_SOURCE_BYTES, GateError

BUNDLE_SCHEMA = "V47-OFFICIAL-INTAKE-BUNDLE-1"
AUDIT_SCHEMA = "V47-INTAKE-BUNDLE-AUDIT-1"
# Audit source-root identity independently of the intake worker that authored the manifest.
SOURCE_IDS_BY_GAME = {
    "SSQ": frozenset({"national", "shanghai", "hebei"}),
    "DLT": frozenset({"national", "jiangsu", "gansu"}),
}


def _iter_artifacts(bundle: dict):
    games = bundle.get("games", {})
    if not isinstance(games, dict):
        return
    for game, result in games.items():
        if not isinstance(result, dict):
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


def audit_bundle(bundle_dir: str | Path) -> dict:
    """Return an audit receipt; never modify the intake manifest or raw source bytes."""
    root = Path(bundle_dir).resolve()
    manifest_path = root / "intake.json"
    errors: list[str] = []
    bundle = None
    manifest_sha256 = None
    if not manifest_path.is_file():
        errors.append("INTAKE_MANIFEST_MISSING")
    else:
        raw_manifest = manifest_path.read_bytes()
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
            if unresolved.is_symlink():
                errors.append(f"RAW_ARTIFACT_SYMLINK_NOT_ALLOWED:{game}:{source_id}:{rel}")
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
            raw = candidate.read_bytes()
            if len(raw) != size:
                errors.append(f"RAW_ARTIFACT_SIZE_MISMATCH:{game}:{source_id}:{rel}")
                continue
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                errors.append(f"RAW_ARTIFACT_SHA256_MISMATCH:{game}:{source_id}:{rel}")
                continue
            if body_preserved is False:
                errors.append(f"RAW_ARTIFACT_PRESERVATION_FLAG_CONFLICT:{game}:{source_id}:{rel}")
                continue
            unique_paths.add(rel)
            verified_records += 1

    if artifact_records == 0:
        errors.append("NO_RAW_ARTIFACT_RECORDS_FOUND")

    # Detect unlisted SHA-named files even when every referenced manifest
    # entry matches; an archive should not silently carry extra draw-like bytes.
    raw_dir = root / "raw"
    if raw_dir.exists():
        for raw_file in raw_dir.rglob("*.bin"):
            rel = raw_file.relative_to(root).as_posix()
            if rel not in unique_paths:
                errors.append(f"UNREFERENCED_RAW_ARTIFACT:{rel}")

    return {
        "schema": AUDIT_SCHEMA,
        "auditor_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "PASS" if not errors else "FAIL",
        "purpose": "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY",
        "bundle_manifest_sha256": manifest_sha256,
        "artifact_records": artifact_records,
        "verified_artifact_records": verified_records,
        "unique_raw_file_paths": len(unique_paths),
        "diagnostic_non_200_responses": diagnostic_http_responses,
        "unpreserved_oversized_records": unpreserved_oversized_records,
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
    root = Path(args.bundle_dir)
    root.mkdir(parents=True, exist_ok=True)
    report = audit_bundle(root)
    output = root / "intake-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
