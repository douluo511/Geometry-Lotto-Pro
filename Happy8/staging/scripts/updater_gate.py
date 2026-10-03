from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.updater import Updater, _update_transaction_paths, recover_interrupted_update


class FakeResponse:
    def __init__(self, *, url: str, content: bytes, content_type: str, status_code: int = 200):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.happy8_attempts = ({"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": status_code},)


class FakeNet:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise RuntimeError("unexpected network request")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def manifest_bytes(*, version: str, artifact: bytes, digest: str | None = None) -> bytes:
    value = {
        "schema": "happy8-update-manifest-v1",
        "version": version,
        "artifact_url": "https://updates.example/Happy8.exe",
        "artifact_sha256": digest or hashlib.sha256(artifact).hexdigest(),
        "artifact_bytes": len(artifact),
    }
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def updater_with(manifest: bytes, artifact: bytes | None = None) -> Updater:
    responses = [
        FakeResponse(
            url="https://updates.example/latest.json",
            content=manifest,
            content_type="application/json",
        )
    ]
    if artifact is not None:
        responses.append(
            FakeResponse(
                url="https://updates.example/Happy8.exe",
                content=artifact,
                content_type="application/octet-stream",
            )
        )
    return Updater(
        manifest_url="https://updates.example/latest.json",
        trusted_hosts={"updates.example"},
        net=FakeNet(responses),
    )


def _healthy_self_test(args, **kwargs):
    values = list(args)
    result_file = Path(values[values.index("--result-file") + 1])
    result_file.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    return type("Completed", (), {"returncode": 0})()


def _failing_self_test(args, **kwargs):
    return type("Completed", (), {"returncode": 9})()


def main() -> int:
    checks = {}

    try:
        Updater(
            manifest_url="http://updates.example/latest.json",
            trusted_hosts={"updates.example"},
            net=FakeNet([]),
        )
        checks["manifest_https_trust_fail_closed"] = {"status": "FAIL"}
    except ValueError:
        checks["manifest_https_trust_fail_closed"] = {"status": "PASS"}

    artifact = b"MZ" + b"candidate" * 500
    manifest = manifest_bytes(version="0.2.1", artifact=artifact)
    updater = updater_with(manifest, artifact)
    parsed, _ = updater.fetch_manifest()
    downloaded, receipt = updater.download_artifact(parsed)
    checks["manifest_and_hash_contract"] = {
        "status": "PASS"
        if downloaded == artifact and receipt.get("sha256") == hashlib.sha256(artifact).hexdigest()
        else "FAIL"
    }

    bad_manifest = manifest_bytes(version="0.2.1", artifact=artifact, digest="0" * 64)
    updater = updater_with(bad_manifest, artifact)
    parsed, _ = updater.fetch_manifest()
    try:
        updater.download_artifact(parsed)
        checks["bad_artifact_hash_fail_closed"] = {"status": "FAIL"}
    except RuntimeError:
        checks["bad_artifact_hash_fail_closed"] = {"status": "PASS"}

    truncated = artifact[:-7]
    updater = updater_with(manifest, truncated)
    parsed, _ = updater.fetch_manifest()
    try:
        updater.download_artifact(parsed)
        checks["truncated_download_fail_closed"] = {"status": "FAIL"}
    except RuntimeError:
        checks["truncated_download_fail_closed"] = {"status": "PASS"}

    with tempfile.TemporaryDirectory(prefix="happy8-updater-up-to-date-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-bytes"
        target.write_bytes(original)
        same_manifest = manifest_bytes(version="0.2.0", artifact=artifact)
        updater = updater_with(same_manifest)
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["non_monotonic_no_replace"] = {
            "status": "PASS"
            if result.get("status") == "PASS"
            and result.get("action") == "UP_TO_DATE"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-success-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-bytes-success"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        with patch("happy8.updater.subprocess.run", side_effect=_healthy_self_test):
            result = updater.install(target_exe=target, current_version="0.2.0")
        stage, backup, health, journal = _update_transaction_paths(target)
        checks["normal_atomic_update"] = {
            "status": "PASS"
            if result.get("status") == "PASS"
            and result.get("action") == "UPDATED"
            and target.read_bytes() == artifact
            and not stage.exists()
            and not backup.exists()
            and not health.exists()
            and not journal.exists()
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-offline-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-offline"
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

    with tempfile.TemporaryDirectory(prefix="happy8-updater-download-interrupt-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-download-interrupt"
        target.write_bytes(original)
        updater = Updater(
            manifest_url="https://updates.example/latest.json",
            trusted_hosts={"updates.example"},
            net=FakeNet([
                FakeResponse(
                    url="https://updates.example/latest.json",
                    content=manifest,
                    content_type="application/json",
                ),
                requests.ConnectionError("download interrupted"),
            ]),
        )
        result = updater.install(target_exe=target, current_version="0.2.0")
        checks["download_interruption_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ABORTED_BEFORE_REPLACE"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-permission-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-permission"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        real_sync = __import__("happy8.updater", fromlist=["_durable_sync_path"])._durable_sync_path

        def deny_stage(path):
            if str(path).endswith(".update-stage"):
                raise PermissionError("injected stage permission denial")
            return real_sync(path)

        with patch("happy8.updater._durable_sync_path", side_effect=deny_stage):
            result = updater.install(target_exe=target, current_version="0.2.0")
        checks["permission_error_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-parent-busy-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-parent-busy"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        with patch("happy8.updater._wait_parent_exit", side_effect=RuntimeError("parent still running")):
            result = updater.install(target_exe=target, current_version="0.2.0", parent_pid=12345)
        stage, backup, health, journal = _update_transaction_paths(target)
        checks["main_program_occupied_fail_closed"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ABORTED_BEFORE_REPLACE"
            and target.read_bytes() == original
            and not stage.exists()
            and not journal.exists()
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-replace-failure-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-replace-failure"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        real_replace = os.replace

        def fail_target_replace(src, dst):
            if str(src).endswith(".update-stage") and Path(dst) == target:
                raise PermissionError("injected target replace failure")
            return real_replace(src, dst)

        with patch("happy8.updater.os.replace", side_effect=fail_target_replace):
            result = updater.install(target_exe=target, current_version="0.2.0")
        checks["replace_failure_rolls_back"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ROLLED_BACK"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-health-rollback-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-bytes-for-rollback"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        with patch("happy8.updater.subprocess.run", side_effect=_failing_self_test):
            result = updater.install(target_exe=target, current_version="0.2.0")
        checks["health_failure_atomic_rollback"] = {
            "status": "PASS"
            if result.get("status") == "FAIL"
            and result.get("action") == "ROLLED_BACK"
            and target.read_bytes() == original
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-updater-rollback-failure-recovery-") as td:
        target = Path(td) / "Happy8.exe"
        original = b"old-exe-restart-recovery"
        target.write_bytes(original)
        updater = updater_with(manifest, artifact)
        real_replace = os.replace
        rollback_attempts = {"count": 0}
        _, expected_backup, _, _ = _update_transaction_paths(target)
        target_norm = os.path.normcase(os.path.abspath(os.fspath(target)))
        backup_norm = os.path.normcase(os.path.abspath(os.fspath(expected_backup)))

        def fail_backup_restore(src, dst):
            src_norm = os.path.normcase(os.path.abspath(os.fspath(src)))
            dst_norm = os.path.normcase(os.path.abspath(os.fspath(dst)))
            if src_norm == backup_norm and dst_norm == target_norm:
                rollback_attempts["count"] += 1
                raise PermissionError("injected rollback failure")
            return real_replace(src, dst)

        with patch("happy8.updater.subprocess.run", side_effect=_failing_self_test):
            with patch("happy8.updater.os.replace", side_effect=fail_backup_restore):
                failed = updater.install(target_exe=target, current_version="0.2.0")
        _, backup, _, journal = _update_transaction_paths(target)
        retained = backup.exists() and journal.exists()
        recovered = recover_interrupted_update(target)
        checks["rollback_failure_retains_recovery_state"] = {
            "status": "PASS"
            if failed.get("status") == "FAIL"
            and failed.get("action") == "ROLLBACK_FAILED"
            and retained
            and rollback_attempts["count"] == 1
            else "FAIL",
            "failed_status": failed.get("status"),
            "failed_action": failed.get("action"),
            "retained_backup_and_journal": retained,
            "rollback_injection_count": rollback_attempts["count"],
        }
        checks["restart_recovery_restores_previous_exe"] = {
            "status": "PASS"
            if recovered.get("status") == "PASS"
            and recovered.get("action") == "RECOVERED_ROLLBACK"
            and target.read_bytes() == original
            and not backup.exists()
            and not journal.exists()
            else "FAIL",
            "recovered_status": recovered.get("status"),
            "recovered_action": recovered.get("action"),
            "restored_original_bytes": target.read_bytes() == original,
            "backup_removed": not backup.exists(),
            "journal_removed": not journal.exists(),
        }

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-updater-gate-v2", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
