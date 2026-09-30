from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import updater


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
