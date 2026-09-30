from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "SSQ"))

import updater as updater_module  # noqa: E402
from glp.util import atomic_json  # noqa: E402

EXPECTED_REPOSITORY = "douluo511/Geometry-Lotto-Pro-SSQ"
EXPECTED_SERVER = "https://github.com"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _require_independent_actions_context() -> dict[str, str]:
    context = {
        "github_actions": str(os.environ.get("GITHUB_ACTIONS") or ""),
        "repository": str(os.environ.get("GITHUB_REPOSITORY") or ""),
        "server": str(os.environ.get("GITHUB_SERVER_URL") or "").rstrip("/"),
        "sha": str(os.environ.get("GITHUB_SHA") or ""),
        "run_id": str(os.environ.get("GITHUB_RUN_ID") or ""),
        "runner_os": str(os.environ.get("RUNNER_OS") or ""),
    }
    if context["github_actions"].lower() != "true":
        raise RuntimeError("real release acceptance requires GitHub Actions")
    if context["repository"] != EXPECTED_REPOSITORY:
        raise RuntimeError("real release acceptance requires the independent SSQ repository")
    if context["server"] != EXPECTED_SERVER:
        raise RuntimeError("real release acceptance requires github.com")
    if not context["sha"] or not context["run_id"]:
        raise RuntimeError("GitHub Actions commit/run identity is missing")
    if context["runner_os"] != "Windows":
        raise RuntimeError("real release acceptance requires the Windows runner")
    return context


def _load_release(manifest_url: str) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes, dict[str, Any]]:
    manifest_raw, manifest_receipt = updater_module._bounded_get(
        manifest_url,
        kind="manifest",
        max_bytes=updater_module.MAX_MANIFEST_BYTES,
    )
    manifest = updater_module._parse_software_manifest(manifest_raw)
    artifact, artifact_receipt = updater_module._bounded_get(
        manifest["artifact_url"],
        kind="artifact",
        max_bytes=updater_module.MAX_ARTIFACT_BYTES,
    )
    digest = hashlib.sha256(artifact).hexdigest()
    if len(artifact) != manifest["artifact_bytes"]:
        raise RuntimeError("release artifact byte count does not match manifest")
    if digest != manifest["artifact_sha256"]:
        raise RuntimeError("release artifact SHA256 does not match manifest")
    return manifest, manifest_raw, manifest_receipt, artifact, artifact_receipt


def _exact_main_identity(path: Path, expected_version: str | None = None) -> dict[str, Any]:
    ok, proof = updater_module._exact_main_self_test(path, expected_version=expected_version)
    if not ok:
        raise RuntimeError(f"exact main self-test failed: {proof}")
    result = proof.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("exact main self-test result payload missing")
    if result.get("exe_sha256") != _sha256(path):
        raise RuntimeError("exact main self-test hash does not match file bytes")
    version = result.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("exact main self-test version missing")
    return {
        "version": version,
        "sha256": _sha256(path),
        "proof": proof,
    }


def run_acceptance(
    updater_exe: Path,
    candidate_exe: Path,
    base_manifest_url: str,
    release_manifest_url: str,
    evidence_dir: Path,
) -> dict[str, Any]:
    context = _require_independent_actions_context()
    updater_exe = updater_exe.resolve()
    candidate_exe = candidate_exe.resolve()
    evidence_dir = evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if not updater_exe.is_file() or not candidate_exe.is_file():
        raise FileNotFoundError("exact updater or candidate main EXE is missing")

    updater_hash = _sha256(updater_exe)
    candidate = _exact_main_identity(candidate_exe)

    base_manifest, base_manifest_raw, base_manifest_receipt, base_bytes, base_artifact_receipt = _load_release(
        base_manifest_url
    )
    release_manifest_raw, release_manifest_receipt = updater_module._bounded_get(
        release_manifest_url,
        kind="manifest",
        max_bytes=updater_module.MAX_MANIFEST_BYTES,
    )
    release_manifest = updater_module._parse_software_manifest(release_manifest_raw)

    if release_manifest["artifact_sha256"] != candidate["sha256"]:
        raise RuntimeError("release manifest is not bound to the current candidate EXE SHA256")
    if release_manifest["artifact_bytes"] != candidate_exe.stat().st_size:
        raise RuntimeError("release manifest is not bound to the current candidate EXE byte size")
    if release_manifest["version"] != candidate["version"]:
        raise RuntimeError("release manifest version does not match current candidate self-test version")
    updater_module._require_forward_version(base_manifest["version"], release_manifest["version"])

    target = evidence_dir / "updater-release-base-main.exe"
    target.write_bytes(base_bytes)
    if _sha256(target) != base_manifest["artifact_sha256"]:
        raise RuntimeError("base release target write-back hash mismatch")
    base_identity = _exact_main_identity(target, expected_version=base_manifest["version"])
    if base_identity["sha256"] != base_manifest["artifact_sha256"]:
        raise RuntimeError("base release exact EXE is not bound to its manifest")

    result_path = evidence_dir / "updater-software-release-network.json"
    data_dir = evidence_dir / "updater-software-release-data"
    env = os.environ.copy()
    env["GLP_DATA_DIR"] = str(data_dir)
    env["GLP_UPDATER_PARENT_PID"] = str(os.getpid())
    proc = subprocess.run(
        [
            str(updater_exe),
            "--mode", "software-update",
            "--result-file", str(result_path),
            "--target-exe", str(target),
            "--manifest-url", release_manifest_url,
        ],
        env=env,
        timeout=3600,
    )
    report = json.loads(result_path.read_text(encoding="utf-8-sig")) if result_path.is_file() else {}
    if (
        proc.returncode != 0
        or report.get("schema") != "ssq-independent-updater-v2"
        or report.get("mode") != "software-update"
        or report.get("status") != "PASS"
        or report.get("github_sha") != context["sha"]
        or report.get("github_run_id") != context["run_id"]
        or report.get("updater_exe_sha256") != updater_hash
        or report.get("parent_pid_match") is not True
    ):
        raise RuntimeError("exact updater software-update process did not PASS current-run binding")

    installed_hash = _sha256(target)
    if installed_hash != candidate["sha256"]:
        raise RuntimeError("exact updater did not install the current candidate EXE bytes")
    installed = _exact_main_identity(target, expected_version=candidate["version"])
    if installed["sha256"] != candidate["sha256"]:
        raise RuntimeError("installed exact main self-test hash mismatch")

    service = report.get("service_result")
    if not isinstance(service, dict) or service.get("status") != "PASS":
        raise RuntimeError("exact updater software-update service result did not PASS")
    if service.get("from_version") != base_manifest["version"]:
        raise RuntimeError("exact updater did not report the verified base version")
    if service.get("to_version") != candidate["version"]:
        raise RuntimeError("exact updater did not report the candidate version")

    updater_acceptance_path = evidence_dir / "UPDATER_EXACT_EXE_ACCEPTANCE.json"
    updater_acceptance = json.loads(
        updater_acceptance_path.read_text(encoding="utf-8-sig")
    ) if updater_acceptance_path.is_file() else {}
    if (
        updater_acceptance.get("schema") != "ssq-updater-exact-exe-acceptance-v2"
        or updater_acceptance.get("github_sha") != context["sha"]
        or updater_acceptance.get("github_run_id") != context["run_id"]
        or updater_acceptance.get("sha256") != updater_hash
        or updater_acceptance.get("updater_exact_exe") != "PASS"
        or type(updater_acceptance.get("hard_fail_count")) is not int
        or updater_acceptance.get("hard_fail_count") != 0
    ):
        raise RuntimeError("updater exact-EXE acceptance is not current-run/hash bound")

    updater_acceptance["software_release_network"] = "PASS"
    updater_acceptance["software_release_reason"] = (
        "exact updater upgraded verified prior release to current exact candidate via independent-repo HTTPS release"
    )
    updater_acceptance["updater_release_gate"] = "PASS"
    updater_acceptance["software_release_evidence"] = result_path.name
    updater_acceptance["software_release_evidence_sha256"] = _sha256(result_path)
    atomic_json(updater_acceptance_path, updater_acceptance)

    summary = {
        "schema": "ssq-updater-real-release-acceptance-v1",
        "status": "PASS",
        "github_sha": context["sha"],
        "github_run_id": context["run_id"],
        "repository": context["repository"],
        "updater_exe_sha256": updater_hash,
        "candidate_exe_sha256": candidate["sha256"],
        "candidate_version": candidate["version"],
        "base_version": base_manifest["version"],
        "base_manifest_url": base_manifest_url,
        "base_manifest_raw_sha256": hashlib.sha256(base_manifest_raw).hexdigest(),
        "base_manifest_receipt": base_manifest_receipt,
        "base_artifact_receipt": base_artifact_receipt,
        "release_manifest_url": release_manifest_url,
        "release_manifest_raw_sha256": hashlib.sha256(release_manifest_raw).hexdigest(),
        "release_manifest_receipt": release_manifest_receipt,
        "exact_updater_report": result_path.name,
        "exact_updater_report_sha256": _sha256(result_path),
        "installed_sha256": installed_hash,
        "installed_version": installed["version"],
    }
    atomic_json(evidence_dir / "UPDATER_REAL_RELEASE_ACCEPTANCE.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--updater-exe", type=Path, required=True)
    parser.add_argument("--candidate-exe", type=Path, required=True)
    parser.add_argument("--base-manifest-url", required=True)
    parser.add_argument("--release-manifest-url", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        summary = run_acceptance(
            args.updater_exe,
            args.candidate_exe,
            args.base_manifest_url,
            args.release_manifest_url,
            args.evidence_dir,
        )
        print(json.dumps(summary, ensure_ascii=True), flush=True)
        return 0
    except Exception as exc:
        failure = {
            "schema": "ssq-updater-real-release-acceptance-v1",
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "github_sha": os.environ.get("GITHUB_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
        }
        try:
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            atomic_json(args.evidence_dir / "UPDATER_REAL_RELEASE_ACCEPTANCE.json", failure)
        except Exception:
            pass
        print(json.dumps(failure, ensure_ascii=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
