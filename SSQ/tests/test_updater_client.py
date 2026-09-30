from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from glp.updater_client import UpdaterClient
from glp.util import sha256_json


class _Proc:
    pid = 424242


class UpdaterClientSoftwareTests(unittest.TestCase):
    def test_software_handoff_is_not_pass_and_binds_parent_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = UpdaterClient(root)
            updater = root / "bundle-updater.exe"
            target = root / "main.exe"
            updater.write_bytes(b"updater-bytes")
            target.write_bytes(b"main-before")
            digest = hashlib.sha256(updater.read_bytes()).hexdigest()
            manifest = {"sha256": digest}
            with (
                patch.object(client, "_materialize", return_value=(updater, manifest)),
                patch("glp.updater_client.subprocess.Popen", return_value=_Proc()) as popen,
            ):
                result = client.launch_software_update(
                    "https://github.com/example/project/releases/download/v1/manifest.json",
                    target_exe=target,
                )
            self.assertEqual(result["status"], "HANDOFF_READY")
            self.assertEqual(result["updater_pid"], 424242)
            self.assertEqual(result["updater_sha256"], digest)
            self.assertEqual(result["target_before_sha256"], hashlib.sha256(b"main-before").hexdigest())
            cmd = popen.call_args.args[0]
            self.assertIn("software-update", cmd)
            self.assertIn("--wait-pid", cmd)
            self.assertIn(str(target.resolve()), cmd)

    def test_missing_software_result_is_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = UpdaterClient(root)
            missing = root / "missing-result.json"
            handoff = {
                "schema": "ssq-software-update-handoff-v1",
                "main_pid": 123,
                "updater_sha256": "a" * 64,
                "result_file": str(missing),
            }
            result = client.read_software_update_result(handoff)
            self.assertEqual(result["status"], "PENDING")

    def test_completed_software_result_binds_full_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = UpdaterClient(root)
            result_path = root / "result.json"
            target = root / "main.exe"
            target.write_bytes(b"new-main")
            before_hash = hashlib.sha256(b"old-main").hexdigest()
            installed_hash = hashlib.sha256(b"new-main").hexdigest()
            manifest_url = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro-SSQ/main/release/manifest.json"
            handoff = {
                "schema": "ssq-software-update-handoff-v1",
                "main_pid": 123,
                "updater_sha256": "a" * 64,
                "result_file": str(result_path),
                "target_exe": str(target),
                "target_before_sha256": before_hash,
                "manifest_url": manifest_url,
            }
            service_result = {
                "status": "PASS",
                "schema": "ssq-software-update-result-v1",
                "wait_for_main": {"status": "PASS"},
                "manifest": {"artifact_sha256": installed_hash},
                "manifest_receipt": {"requested_url": manifest_url},
                "replacement": {
                    "status": "PASS",
                    "target": str(target.resolve()),
                    "before_sha256": before_hash,
                    "expected_sha256": installed_hash,
                    "installed_sha256": installed_hash,
                    "post_replace_validation": {"status": "PASS"},
                },
            }
            report = {
                "schema": "ssq-independent-updater-v2",
                "mode": "software-update",
                "status": "PASS",
                "updater_exe_sha256": "a" * 64,
                "parent_pid_match": True,
                "parent_pid": 456,
                "ancestor_pids": [456, 123],
                "expected_parent_pid": 123,
                "service_result": service_result,
                "service_result_sha256": sha256_json(service_result),
            }
            result_path.write_text(json.dumps(report), encoding="utf-8")
            result = client.read_software_update_result(handoff)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["transaction"]["replacement"]["installed_sha256"], installed_hash)

    def test_completed_software_result_rejects_target_or_ancestor_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = UpdaterClient(root)
            result_path = root / "result.json"
            target = root / "main.exe"
            target.write_bytes(b"new-main")
            before_hash = hashlib.sha256(b"old-main").hexdigest()
            installed_hash = hashlib.sha256(b"new-main").hexdigest()
            manifest_url = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro-SSQ/main/release/manifest.json"
            handoff = {
                "schema": "ssq-software-update-handoff-v1",
                "main_pid": 123,
                "updater_sha256": "a" * 64,
                "result_file": str(result_path),
                "target_exe": str(target),
                "target_before_sha256": before_hash,
                "manifest_url": manifest_url,
            }
            service_result = {
                "status": "PASS",
                "schema": "ssq-software-update-result-v1",
                "wait_for_main": {"status": "PASS"},
                "manifest": {"artifact_sha256": installed_hash},
                "manifest_receipt": {"requested_url": manifest_url},
                "replacement": {
                    "status": "PASS",
                    "target": str(root / "other.exe"),
                    "before_sha256": before_hash,
                    "expected_sha256": installed_hash,
                    "installed_sha256": installed_hash,
                    "post_replace_validation": {"status": "PASS"},
                },
            }
            report = {
                "schema": "ssq-independent-updater-v2",
                "mode": "software-update",
                "status": "PASS",
                "updater_exe_sha256": "a" * 64,
                "parent_pid_match": True,
                "parent_pid": 456,
                "ancestor_pids": [456, 123],
                "expected_parent_pid": 123,
                "service_result": service_result,
                "service_result_sha256": sha256_json(service_result),
            }
            result_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                client.read_software_update_result(handoff)

            service_result["replacement"]["target"] = str(target.resolve())
            report["ancestor_pids"] = [456, 999]
            report["service_result_sha256"] = sha256_json(service_result)
            result_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                client.read_software_update_result(handoff)

    def test_result_must_bind_updater_hash_and_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = UpdaterClient(root)
            result_path = root / "result.json"
            handoff = {
                "schema": "ssq-software-update-handoff-v1",
                "main_pid": 123,
                "updater_sha256": "a" * 64,
                "result_file": str(result_path),
            }
            result_path.write_text(json.dumps({
                "schema": "ssq-independent-updater-v2",
                "mode": "software-update",
                "status": "PASS",
                "updater_exe_sha256": "b" * 64,
                "expected_parent_pid": 123,
                "service_result": {"status": "PASS"},
            }), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                client.read_software_update_result(handoff)


if __name__ == "__main__":
    unittest.main()
