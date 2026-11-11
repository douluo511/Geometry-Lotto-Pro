"""Read-only P1 original-source acquisition and independently audited fail-closed receipt.

Uses pinned EXISTING V4.7 official_intake and audit_intake_bundle from PR #467.
No forecasts, no prediction/frozen ledger modifications, no paid model calls.
GitHub runner/artifact are ephemeral; this does not authenticate draw schedules,
sale cutoff, trusted predraw time, or any prospective result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PINNED_V47_COMMIT = "27c519ec0ad251a9d86ebc3452277b158930299e"
VALID_GAMES = ("SSQ", "DLT")
REQUIRED_SOURCES = {
    "SSQ": frozenset({"national", "shanghai", "hebei"}),
    "DLT": frozenset({"national", "jiangsu", "gansu"}),
}
MAX_JSON = 32_000_000


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_pairs(pairs):
    record = {}
    for k, v in pairs:
        if k in record:
            raise ValueError("DUPLICATE_JSON_KEY")
        record[k] = v
    return record


def strict_json(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > MAX_JSON:
        raise ValueError("OVERSIZED_JSON")
    parsed = json.loads(
        data.decode("utf-8"), object_pairs_hook=_strict_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON"))
    )
    if not isinstance(parsed, dict):
        raise ValueError("ROOT_MUST_BE_OBJECT")
    return parsed


def check_guard(bundle: dict) -> dict:
    """No untrusted source bundle may silently promote either game to formal A."""
    if bundle.get("schema") != "V47-OFFICIAL-INTAKE-BUNDLE-1":
        raise ValueError("UNKNOWN_BUNDLE_PROTOCOL")
    if set(bundle.get("games", {})) != set(VALID_GAMES):
        raise ValueError("BOTH_GAMES_REQUIRED")
    if (type(bundle.get("formal_A")) is not int
            or bundle["formal_A"] != 0
            or bundle.get("official_target_admission") != "BLOCKED"
            or bundle.get("external_tsa") != "NOT_RUN"
            or bundle.get("decision") != "NO_EDGE"):
        raise ValueError("BUNDLE_FORMAL_ADMISSION_BYPASS")
    statuses = {}
    for game in VALID_GAMES:
        result = bundle["games"][game]
        if not isinstance(result, dict):
            raise ValueError("INVALID_GAME_RESULT:" + game)
        if (type(result.get("formal_A")) is not int
                or result["formal_A"] != 0
                or result.get("official_target_admission") != "BLOCKED"
                or result.get("decision") != "NO_EDGE"):
            raise ValueError("GAME_FORMAL_ADMISSION_BYPASS:" + game)
        status = result.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("MISSING_SOURCE_STATUS:" + game)
        statuses[game] = status
    return statuses


def source_diagnostics(bundle: dict) -> dict:
    """Machine-readable source blockers: no reinterpretation or date repair."""
    result = {}
    for game in VALID_GAMES:
        sources = bundle["games"][game].get("sources")
        if not isinstance(sources, list) or len(sources) != 3:
            raise ValueError("THREE_ORIGINAL_SOURCES_REQUIRED:" + game)
        diagnostics = {}
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("INVALID_SOURCE_RECEIPT")
            source_id = source.get("source_id")
            if source_id not in REQUIRED_SOURCES[game] or source_id in diagnostics:
                raise ValueError("DUPLICATE_OR_UNKNOWN_SOURCE")
            count = source.get("draw_count")
            raw = source.get("raw_artifacts")
            if type(count) is not int or count < 0 or not isinstance(raw, list):
                raise ValueError("INVALID_SOURCE_COUNTS")
            http_statuses = []
            for artifact in raw:
                if not isinstance(artifact, dict):
                    raise ValueError("INVALID_SOURCE_HTTP_ARTIFACT")
                status = artifact.get("http_status")
                if type(status) is not int or not 100 <= status <= 599:
                    raise ValueError("INVALID_SOURCE_HTTP_STATUS")
                http_statuses.append(status)
            error = source.get("error")
            if error is not None and not isinstance(error, str):
                raise ValueError("INVALID_SOURCE_ERROR")
            diagnostics[source_id] = {
                "parsed_draws": count,
                "original_http_responses": len(http_statuses),
                "http_statuses": sorted(set(http_statuses)),
                "blocker": error[:500] if error else None,
            }
        if set(diagnostics) != REQUIRED_SOURCES[game]:
            raise ValueError("MISSING_REQUIRED_INDEPENDENT_SOURCE:" + game)
        result[game] = diagnostics
    return result


def assess(bundle: dict, audit: dict, code_sha: str) -> dict:
    statuses = check_guard(bundle)
    diagnostics = source_diagnostics(bundle)
    if code_sha != PINNED_V47_COMMIT:
        raise ValueError("UNREVIEWED_V47_CODE")
    if (audit.get("schema") != "V47-INTAKE-BUNDLE-AUDIT-1"
            or audit.get("status") != "PASS"
            or audit.get("purpose") != "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY"):
        raise ValueError("BUNDLE_BYTES_NOT_INDEPENDENTLY_VERIFIED")
    if audit.get("admission_guard") != {
        "official_target_admission": "BLOCKED",
        "external_tsa": "NOT_RUN", "formal_A": 0, "decision": "NO_EDGE"
    }:
        raise ValueError("INDEPENDENT_AUDITOR_ADMISSION_BYPASS")
    if (type(audit.get("verified_artifact_records")) is not int
            or audit["verified_artifact_records"] < 1):
        raise ValueError("NO_VERIFIABLE_HTTP_BYTES")
    return {
        "schema": "SSQDLT_P1_LIVE_SOURCE_PROBE_V1",
        "status": "RAW_CUSTODY_PASS_TARGET_BLOCKED",
        "official_history_status_by_game": statuses,
        "source_diagnostics_by_game": diagnostics,
        "official_source_authenticity": "NOT_VERIFIED",
        "official_target_and_cutoff": "BLOCKED",
        "trusted_predraw_seal": "NOT_RUN",
        "complete_d2_roster_scored": False,
        "prospective_full_hits_verified": 0,
        "formal_A": 0,
        "edge": "NO_EDGE",
        "p1_forecast_gate": "UNVERIFIED",
        "pinned_v47_commit": code_sha,
        "raw_body_records_verified": audit["verified_artifact_records"],
        "http_non200_diagnostic_records": audit.get("diagnostic_non_200_responses"),
        "source_manifest_sha256": audit["bundle_manifest_sha256"],
        "research_only": True,
        "paid_model_calls": 0,
        "limitations": [
            "Live HTTPS fetch alone is not independent source-history consensus.",
            "HTTP Last-Modified or local clock is not an authenticated draw/sale time.",
            "GitHub Actions artifacts expire and cannot replace permanent evidence.",
            "No actual future V4.7 predraw seal or independent outcome score.",
        ],
    }


def _run(args: list[str], *, cwd: Path, timeout: int, prefix: Path) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        completed = subprocess.run(
            args, cwd=cwd, capture_output=True, timeout=timeout, check=False
        )
        out, err, rc = completed.stdout, completed.stderr, completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        err = exc.stderr or b""
        rc = None
        timed_out = True
    prefix.with_suffix(".stdout.bin").write_bytes(out)
    prefix.with_suffix(".stderr.bin").write_bytes(err)
    return {
        "argv": args[1:],
        "status": "TIMEOUT" if timed_out else "EXITED",
        "exit_code": rc,
        "stdout_sha256": digest(out), "stderr_sha256": digest(err),
        "stdout_bytes": len(out), "stderr_bytes": len(err),
        "started_at_untrusted": started,
        "completed_at_untrusted": datetime.now(timezone.utc).isoformat(),
    }


def run(v47_root: Path, output_dir: Path, *, timeout: int = 720) -> dict:
    v47_root = v47_root.resolve(strict=True)
    if output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    output_dir.mkdir(parents=True)
    report = {
        "schema": "SSQDLT_P1_EXECUTION_RECEIPT_V1",
        "status": "FAIL_CLOSED", "formal_A": 0, "edge": "NO_EDGE",
        "code_sha_expected": PINNED_V47_COMMIT, "paid_model_calls": 0
    }
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=v47_root,
            timeout=15, text=True
        ).strip()
        report["code_sha_actual"] = sha
        if sha != PINNED_V47_COMMIT:
            raise ValueError("CODE_SHA_NOT_PINNED")

        manifest_root = output_dir / "live-evidence"
        report["intake_process"] = _run([
            sys.executable, "-m", "research.harness_v46.official_intake",
            "--game", "ALL", "--output-dir", str(manifest_root),
        ], cwd=v47_root, timeout=timeout, prefix=output_dir / "intake-process")

        if not (manifest_root / "intake.json").is_file():
            raise ValueError("RAW_INTAKE_MANIFEST_NOT_CREATED")
        # A blocked source intake may exit 2: this is a scientific blocker,
        # not permission to skip exact byte audit.
        if report["intake_process"]["exit_code"] not in (0, 2):
            raise ValueError("INTAKE_PROCESS_CRASHED_OR_TIMED_OUT")
        report["audit_process"] = _run([
            sys.executable, "-m", "research.harness_v46.audit_intake_bundle",
            "--bundle-dir", str(manifest_root),
        ], cwd=v47_root, timeout=180, prefix=output_dir / "audit-process")
        if report["audit_process"]["exit_code"] != 0:
            raise ValueError("INDEPENDENT_BYTE_AUDITOR_FAILED")
        bundle = strict_json(manifest_root / "intake.json")
        audit = strict_json(manifest_root / "intake-audit.json")
        report["gate"] = assess(bundle, audit, sha)
        report["status"] = report["gate"]["status"]
        # Source and target admission is blocked, even if byte custody passed.
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report["blocker"] = f"{type(exc).__name__}:{exc}"
    finally:
        (output_dir / "p1-execution.json").write_text(
            json.dumps(report, indent=2, sort_keys=True,
                       ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v47-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=720)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_seconds <= 900:
        parser.error("timeout must be between 30 and 900 seconds")
    report = run(args.v47_root, args.output_dir, timeout=args.timeout_seconds)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "RAW_CUSTODY_PASS_TARGET_BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
