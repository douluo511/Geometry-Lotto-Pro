from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import updater


class _Response:
    def __init__(self, status_code: int, url: str, *, location: str = "", content: bytes = b"ok"):
        self.status_code = status_code
        self.url = url
        self.content = content
        self.headers = {"Content-Type": "application/octet-stream"}
        if location:
            self.headers["Location"] = location


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected redirect request")
        return self.responses.pop(0)




class SoftwareUpdaterTests(unittest.TestCase):
    def test_trusted_release_repository_policy(self):
        manifest = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro-SSQ/main/release/manifest.json"
        artifact = "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe"
        self.assertTrue(updater._trusted_release_request(manifest, kind="manifest"))
        self.assertTrue(updater._trusted_release_request(artifact, kind="artifact"))
        self.assertFalse(updater._trusted_release_request("http://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe", kind="artifact"))
        self.assertFalse(updater._trusted_release_request("https://github.com/other/repo/releases/download/v1/app.exe", kind="artifact"))
        self.assertFalse(updater._trusted_release_request("https://release-assets.githubusercontent.com/direct-object", kind="artifact"))
        self.assertFalse(updater._trusted_release_request("https://user:pass@github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe", kind="artifact"))

    def test_verified_redirect_allows_only_checked_github_asset_hop(self):
        start = "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe"
        asset = "https://release-assets.githubusercontent.com/github-production-release-asset/test"
        session = _Session([
            _Response(302, start, location=asset),
            _Response(200, asset, content=b"artifact"),
        ])
        response = updater._get_with_verified_redirects(
            session, start, headers={}, timeout=(1.0, 2.0)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["url"] for x in session.calls], [start, asset])
        self.assertEqual(len(response.updater_redirect_chain), 1)
        self.assertFalse(session.calls[0]["allow_redirects"])
        self.assertFalse(session.calls[1]["allow_redirects"])

    def test_redirect_downgrade_is_rejected_before_next_request(self):
        start = "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe"
        session = _Session([
            _Response(302, start, location="http://release-assets.githubusercontent.com/insecure"),
        ])
        with self.assertRaises(RuntimeError):
            updater._get_with_verified_redirects(session, start, headers={}, timeout=(1.0, 2.0))
        self.assertEqual(len(session.calls), 1)

    def test_cross_host_redirect_is_rejected_before_next_request(self):
        start = "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v1/app.exe"
        session = _Session([
            _Response(302, start, location="https://example.com/attacker.exe"),
        ])
        with self.assertRaises(RuntimeError):
            updater._get_with_verified_redirects(session, start, headers={}, timeout=(1.0, 2.0))
        self.assertEqual(len(session.calls), 1)

    def test_manifest_contract(self):
        payload = {
            "schema": updater.SOFTWARE_MANIFEST_SCHEMA,
            "app": "Geometry Lotto Pro SSQ",
            "version": "8.6.0",
            "artifact_url": "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v8.6.0/app.exe",
            "artifact_sha256": "a" * 64,
            "artifact_bytes": 123,
        }
        parsed = updater._parse_software_manifest(json.dumps(payload).encode("utf-8"))
        self.assertEqual(parsed["version"], "8.6.0")
        payload["artifact_url"] = "https://github.com/other/repo/releases/download/v8.6.0/app.exe"
        with self.assertRaises(ValueError):
            updater._parse_software_manifest(json.dumps(payload).encode("utf-8"))
        payload["artifact_url"] = "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v8.6.0/app.exe"
        payload["version"] = "latest"
        with self.assertRaises(ValueError):
            updater._parse_software_manifest(json.dumps(payload).encode("utf-8"))

    def test_forward_version_policy_blocks_equal_and_downgrade(self):
        updater._require_forward_version("8.5.0-verification", "8.5.0")
        updater._require_forward_version("8.5.0", "8.5.1")
        updater._require_forward_version("8.5.0-verification", "8.5.0-verification.1")
        with self.assertRaises(ValueError):
            updater._require_forward_version("8.5.0", "8.5.0")
        with self.assertRaises(ValueError):
            updater._require_forward_version("8.5.0", "8.4.9")
        with self.assertRaises(ValueError):
            updater._require_forward_version("8.5.0+build.1", "8.5.0+build.2")

    def test_software_update_rejects_unverifiable_target_before_network(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "old.exe"
            target.write_bytes(b"not-a-valid-main")
            with mock.patch.object(
                updater, "_exact_main_self_test",
                return_value=(False, {"status": "FAIL", "reported_version": None}),
            ), mock.patch.object(updater, "_bounded_get") as get:
                result = updater._software_update(target, "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v9/manifest.json")
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("version discovery", result["error"])
            get.assert_not_called()

    def test_software_update_compares_manifest_to_installed_target_version(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "old.exe"
            target.write_bytes(b"old-main")
            artifact = b"new-main"
            manifest = {
                "schema": updater.SOFTWARE_MANIFEST_SCHEMA,
                "app": "Geometry Lotto Pro SSQ",
                "version": "9.0.0",
                "artifact_url": "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v9/app.exe",
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                "artifact_bytes": len(artifact),
            }
            manifest_raw = json.dumps(manifest).encode("utf-8")
            manifest_receipt = {"status": "PASS", "requested_url": "manifest"}
            artifact_receipt = {"status": "PASS", "requested_url": manifest["artifact_url"]}
            with mock.patch.object(
                updater, "_exact_main_self_test",
                return_value=(True, {"status": "PASS", "reported_version": "8.5.0"}),
            ), mock.patch.object(
                updater, "_bounded_get",
                side_effect=[(manifest_raw, manifest_receipt), (artifact, artifact_receipt)],
            ), mock.patch.object(
                updater, "_require_forward_version"
            ) as forward, mock.patch.object(
                updater, "_apply_verified_artifact",
                return_value={"status": "PASS", "installed_sha256": hashlib.sha256(artifact).hexdigest()},
            ):
                result = updater._software_update(
                    target,
                    "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v9/manifest.json",
                )
            forward.assert_called_once_with("8.5.0", "9.0.0")
            self.assertEqual(result["from_version"], "8.5.0")
            self.assertEqual(result["to_version"], "9.0.0")
    def test_manifest_accepts_semver_build_metadata(self):
        payload = {
            "schema": updater.SOFTWARE_MANIFEST_SCHEMA,
            "app": "Geometry Lotto Pro SSQ",
            "version": "8.6.0-rc.1+build.7",
            "artifact_url": "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/releases/download/v8.6.0/app.exe",
            "artifact_sha256": "b" * 64,
            "artifact_bytes": 456,
        }
        parsed = updater._parse_software_manifest(json.dumps(payload).encode("utf-8"))
        self.assertEqual(parsed["version"], "8.6.0-rc.1+build.7")

    def test_target_mutation_during_staging_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "app.exe"
            target.write_bytes(b"known-good")
            candidate = b"candidate"
            original_stage = updater._stage_bytes

            def mutate_then_stage(path, data):
                original_stage(path, data)
                target.write_bytes(b"concurrent-change")

            with mock.patch.object(updater, "_stage_bytes", side_effect=mutate_then_stage):
                with self.assertRaisesRegex(RuntimeError, "changed during staging"):
                    updater._apply_verified_artifact(
                        target,
                        candidate,
                        hashlib.sha256(candidate).hexdigest(),
                        validator=lambda _p: (True, {"status": "PASS"}),
                    )
            self.assertEqual(target.read_bytes(), b"concurrent-change")
            self.assertFalse(target.with_name(target.name + ".previous").exists())

    def test_preinstall_restore_failure_is_not_silenced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "app.exe"
            old = b"known-good"
            new = b"candidate"
            target.write_bytes(old)

            original_replace = updater.os.replace
            original_hash = updater._file_sha256
            calls = {"replace": 0}

            def replace_then_block_restore(src, dst):
                calls["replace"] += 1
                if calls["replace"] == 1:
                    return original_replace(src, dst)
                raise OSError("injected restore failure")

            def mismatch_rollback_hash(path):
                if ".rollback" in Path(path).name:
                    return "0" * 64
                return original_hash(path)

            with mock.patch.object(updater.os, "replace", side_effect=replace_then_block_restore), \
                    mock.patch.object(updater, "_file_sha256", side_effect=mismatch_rollback_hash):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "failed to restore original executable after pre-install failure",
                ):
                    updater._apply_verified_artifact(
                        target,
                        new,
                        hashlib.sha256(new).hexdigest(),
                        validator=lambda _p: (True, {"status": "PASS"}),
                    )

            self.assertFalse(target.exists())
            self.assertEqual(len(list(root.glob(".*.rollback"))), 1)

    def test_atomic_replace_and_previous_preservation(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "app.exe"
            old = b"old"
            new = b"new"
            target.write_bytes(old)
            report = updater._apply_verified_artifact(
                target,
                new,
                hashlib.sha256(new).hexdigest(),
                validator=lambda p: (p.read_bytes() == new, {"status": "PASS"}),
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(target.read_bytes(), new)
            self.assertEqual(target.with_name(target.name + ".previous").read_bytes(), old)
            self.assertEqual(report["previous_sha256"], hashlib.sha256(old).hexdigest())

    def test_validation_failure_rolls_back_exact_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "app.exe"
            old = b"known-good"
            bad = b"candidate"
            target.write_bytes(old)
            report = updater._apply_verified_artifact(
                target,
                bad,
                hashlib.sha256(bad).hexdigest(),
                validator=lambda _p: (False, {"status": "FAIL", "injected": True}),
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(report["rolled_back"])
            self.assertEqual(target.read_bytes(), old)
            self.assertEqual(report["restored_sha256"], hashlib.sha256(old).hexdigest())

    def test_exact_updater_software_self_test_contract(self):
        report = updater._software_self_test()
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
