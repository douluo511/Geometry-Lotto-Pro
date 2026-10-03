from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests

from updater import Updater, _replace_path, _transaction_paths, recover_interrupted_update


class Receipt:
    def __init__(self, *, source_id: str, url: str, raw: bytes):
        self.value = {
            "source_id": source_id,
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "content_type": "application/octet-stream",
            "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "fetched_at": "2026-10-03T00:00:00+00:00",
            "attempts": ({"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": 200},),
            "raw_b64": "REMOVED_BY_UPDATER",
        }

    def to_dict(self):
        return dict(self.value)


class FakeNet:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get_bytes(self, url, *, source_id):
        self.calls.append({"url": url, "source_id": source_id})
        if not self.outcomes:
            raise RuntimeError("unexpected network request")
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        raw = bytes(value)
        return raw, Receipt(source_id=source_id, url=url, raw=raw)


def manifest_bytes(*, version: str, artifact: bytes, digest: str | None = None, artifact_bytes: int | None = None) -> bytes:
    return json.dumps({
        "schema": "guoxue-software-update-manifest-v1",
        "version": version,
        "artifact_url": "https://updates.example/Guoxue_Zhice_Windows_Verified.exe",
        "artifact_sha256": digest or hashlib.sha256(artifact).hexdigest(),
        "artifact_bytes": len(artifact) if artifact_bytes is None else artifact_bytes,
    }, separators=(",", ":")).encode("utf-8")


def updater_with(manifest: bytes, artifact: bytes | BaseException | None = None) -> Updater:
    outcomes = [manifest]
    if artifact is not None:
        outcomes.append(artifact)
    return Updater(
        manifest_url="https://updates.example/latest.json",
        trusted_hosts={"updates.example"},
        net=FakeNet(outcomes),
    )


def healthy_self_test(args, **kwargs):
    args = list(args)
    output = Path(args[args.index("--result-file") + 1])
    output.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    return type("Completed", (), {"returncode": 0})()


def failing_self_test(args, **kwargs):
    return type("Completed", (), {"returncode": 9})()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    args = p.parse_args()
    checks: dict[str, dict] = {}

    try:
        Updater(manifest_url="http://updates.example/latest.json", trusted_hosts={"updates.example"}, net=FakeNet([]))
        checks["manifest_https_trust_fail_closed"] = {"status": "FAIL"}
    except ValueError:
        checks["manifest_https_trust_fail_closed"] = {"status": "PASS"}

    artifact = b"MZ" + b"guoxue-candidate" * 512
    manifest = manifest_bytes(version="0.2.1", artifact=artifact)

    updater = updater_with(manifest, artifact)
    parsed, manifest_receipt = updater.fetch_manifest()
    downloaded, artifact_receipt = updater.download_artifact(parsed)
    checks["manifest_and_artifact_contract"] = {
        "status": "PASS"
        if downloaded == artifact
        and artifact_receipt.get("sha256") == hashlib.sha256(artifact).hexdigest()
        and "raw_b64" not in artifact_receipt
        and "raw_b64" not in manifest_receipt
        else "FAIL"
    }

    bad_manifest = manifest_bytes(version="0.2.1", artifact=artifact, digest="0" * 64)
    updater = updater_with(bad_manifest, artifact)
    parsed, _ = updater.fetch_manifest()
    try:
        updater.download_artifact(parsed)
        checks["bad_hash_fail_closed"] = {"status": "FAIL"}
    except RuntimeError:
        checks["bad_hash_fail_closed"] = {"status": "PASS"}

    truncated = artifact[:-13]
    updater = updater_with(manifest, truncated)
    parsed, _ = updater.fetch_manifest()
    try:
        updater.download_artifact(parsed)
        checks["truncated_download_fail_closed"] = {"status": "FAIL"}
    except RuntimeError:
        checks["truncated_download_fail_closed"] = {"status": "PASS"}

    with tempfile.TemporaryDirectory(prefix="guoxue-up-to-date-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-up-to-date"
        target.write_bytes(original)
        same = manifest_bytes(version="0.2.0", artifact=artifact)
        result = updater_with(same).install(target_exe=target, current_version="0.2.0")
        checks["non_monotonic_no_replace"] = {
            "status": "PASS" if result.get("action") == "UP_TO_DATE" and target.read_bytes() == original else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-update-ok-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-success"
        target.write_bytes(original)
        with patch("updater.subprocess.run", side_effect=healthy_self_test):
            result = updater_with(manifest, artifact).install(target_exe=target, current_version="0.2.0")
        stage, backup, health, journal = _transaction_paths(target)
        checks["normal_atomic_update"] = {
            "status": "PASS"
            if result.get("status") == "PASS"
            and result.get("action") == "UPDATED"
            and target.read_bytes() == artifact
            and not any(x.exists() for x in (stage, backup, health, journal))
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-offline-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-offline"
        target.write_bytes(original)
        updater = Updater(
            manifest_url="https://updates.example/latest.json",
            trusted_hosts={"updates.example"},
            net=FakeNet([requests.ConnectionError("offline")]),
        )
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["offline_manifest_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ABORTED_BEFORE_REPLACE"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-interrupt-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-interrupt"
        target.write_bytes(original)
        updater = updater_with(manifest, requests.ConnectionError("download interrupted"))
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["download_interruption_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL" and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-permission-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-permission"
        target.write_bytes(original)
        real_replace = _replace_path

        def deny_stage(src, dst):
            if str(src).endswith(".update-stage"):
                raise PermissionError("injected replace permission failure")
            return real_replace(src, dst)

        with patch("updater._replace_path", side_effect=deny_stage):
            result = updater_with(manifest, artifact).install(target_exe=target, current_version="0.2.0")
        checks["permission_replace_failure_rolls_back"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ROLLED_BACK"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-busy-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-busy"
        target.write_bytes(original)
        with patch("updater._wait_parent_exit", side_effect=RuntimeError("main occupied")):
            result = updater_with(manifest, artifact).install(
                target_exe=target, current_version="0.2.0", parent_pid=12345
            )
        checks["main_program_occupied_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ABORTED_BEFORE_REPLACE"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-health-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-health"
        target.write_bytes(original)
        with patch("updater.subprocess.run", side_effect=failing_self_test):
            result = updater_with(manifest, artifact).install(target_exe=target, current_version="0.2.0")
        checks["health_failure_rolls_back"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ROLLED_BACK"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="guoxue-rollback-fail-") as td:
        target = Path(td) / "Guoxue.exe"
        original = b"old-recovery"
        target.write_bytes(original)
        _, expected_backup, _, _ = _transaction_paths(target)
        rollback_attempts = {"count": 0}
        observed = []
        real_replace = _replace_path

        def fail_backup_restore(src, dst):
            src_path, dst_path = Path(src), Path(dst)
            observed.append({"src_name": src_path.name, "dst_name": dst_path.name})
            if src_path.name == expected_backup.name and dst_path.name == target.name:
                rollback_attempts["count"] += 1
                raise PermissionError("injected rollback failure")
            return real_replace(src, dst)

        with patch("updater.subprocess.run", side_effect=failing_self_test):
            with patch("updater._replace_path", side_effect=fail_backup_restore):
                failed = updater_with(manifest, artifact).install(target_exe=target, current_version="0.2.0")

        _, backup, _, journal = _transaction_paths(target)
        retained = backup.exists() and journal.exists()
        recovered = recover_interrupted_update(target)
        checks["rollback_failure_retains_recovery_state"] = {
            "status": "PASS"
            if failed.get("action") == "ROLLBACK_FAILED"
            and retained
            and rollback_attempts["count"] == 1
            else "FAIL",
            "failed_action": failed.get("action"),
            "retained_backup_and_journal": retained,
            "rollback_injection_count": rollback_attempts["count"],
            "observed_replaces": observed,
        }
        checks["restart_recovery_restores_previous_exe"] = {
            "status": "PASS"
            if recovered.get("status") == "PASS"
            and recovered.get("action") == "RECOVERED_ROLLBACK"
            and target.read_bytes() == original
            and not backup.exists()
            and not journal.exists()
            else "FAIL",
            "recovered_action": recovered.get("action"),
        }

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "guoxue-updater-gate-v1", "status": status, "checks": checks}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
