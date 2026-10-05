from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from updater_runtime import (
    EXE_NAME, PRODUCT, UpdateBlocked, apply_update, atomic_json, digest,
    load_config, recover, semver, verify_manifest,
)

class FixtureNetwork:
    def __init__(self, current_manifest, next_manifest, payload):
        self.current_manifest = current_manifest
        self.next_manifest = next_manifest
        self.payload = payload

    def json(self, url):
        if "/releases/tags/" in url:
            selected = self.current_manifest if self.current_manifest["release_id"] in url else self.next_manifest
            return {
                "draft": False, "prerelease": False, "tag_name": selected["release_id"],
                "assets": [{
                    "name": EXE_NAME,
                    "browser_download_url": selected["artifact"]["url"],
                    "size": selected["artifact"]["size"],
                }],
            }
        if "/git/ref/tags/" in url:
            selected = self.current_manifest if self.current_manifest["release_id"] in url else self.next_manifest
            return {"object": {"type": "commit", "sha": selected["source_sha"]}}
        if "current-manifest" in url:
            return self.current_manifest
        if "next-manifest" in url:
            return self.next_manifest
        raise AssertionError(url)

    def download(self, url, target, expected_size):
        target.write_bytes(self.payload)

class UpdaterContractTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        pub = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.repo = "fixture-owner/investment-finance-pro"
        self.cfg = {
            "enabled": True,
            "repository": self.repo,
            "trusted_public_key_hex": pub,
            "current_manifest_url": f"https://raw.githubusercontent.com/{self.repo}/main/current-manifest.json",
            "next_manifest_url": f"https://raw.githubusercontent.com/{self.repo}/main/next-manifest.json",
        }
        self.old = b"MZ-INVESTMENT-FINANCE-OLD"
        self.new = b"MZ-INVESTMENT-FINANCE-NEW"
        self.current = self.manifest("0.4.0", "a" * 40, self.old)
        self.next = self.manifest("0.5.0", "b" * 40, self.new)

    def sign(self, obj):
        obj.pop("signature", None)
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        obj["signature"] = base64.b64encode(self.private.sign(raw)).decode("ascii")

    def manifest(self, version, source, payload):
        obj = {
            "schema_version": 1, "product": PRODUCT, "repository": self.repo,
            "version": version, "release_id": "v" + version, "source_sha": source,
            "artifact": {
                "name": EXE_NAME, "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "url": f"https://github.com/{self.repo}/releases/download/v{version}/{EXE_NAME}",
            },
        }
        self.sign(obj)
        return obj

    def config_root(self, root):
        atomic_json(root / "updater.json", self.cfg)

    def install(self, root, *, network=None, health_check=None):
        target = root / EXE_NAME
        target.write_bytes(self.old)
        user = root / "userdata"
        self.config_root(user)
        network = network or FixtureNetwork(self.current, self.next, self.new)
        if health_check is None:
            health_check = lambda target, root, expected: self.assertEqual(digest(target), expected["sha256"])
        return target, apply_update(
            target, user, self.cfg, "0.4.0", "a" * 40, network,
            health_check=health_check,
        )

    def test_strict_semver(self):
        self.assertEqual(semver("0.4.0"), (0, 4, 0))
        for bad in ("v0.4.0", "0.4", "01.2.3", "1.2.3-beta"):
            with self.assertRaises(ValueError):
                semver(bad)

    def test_missing_and_monorepo_config_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(UpdateBlocked):
                load_config(root)
            bad = dict(self.cfg)
            bad["repository"] = "douluo511/Geometry-Lotto-Pro"
            atomic_json(root / "updater.json", bad)
            with self.assertRaises(UpdateBlocked):
                load_config(root)

    def test_signed_manifest_tamper_rejected(self):
        broken = copy.deepcopy(self.next)
        broken["source_sha"] = "c" * 40
        with self.assertRaises(InvalidSignature):
            verify_manifest(broken, self.cfg, newer_than="0.4.0")

    def test_valid_upgrade_backs_up_replaces_and_commits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, result = self.install(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(target.read_bytes(), self.new)
            update_dir = root / ".investment-finance-updates"
            self.assertEqual((update_dir / "previous.exe").read_bytes(), self.old)
            self.assertEqual(json.loads((update_dir / "journal.json").read_text())["stage"], "COMMITTED")

    def test_corrupt_download_never_changes_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            net = FixtureNetwork(self.current, self.next, b"MZ-CORRUPT")
            target = root / EXE_NAME
            target.write_bytes(self.old)
            user = root / "userdata"
            self.config_root(user)
            with self.assertRaises(ValueError):
                apply_update(target, user, self.cfg, "0.4.0", "a" * 40, net, health_check=lambda *a: None)
            self.assertEqual(target.read_bytes(), self.old)

    def test_health_failure_rolls_back_old_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def fail_health(*_args):
                raise RuntimeError("fixture health failure")
            target = root / EXE_NAME
            target.write_bytes(self.old)
            user = root / "userdata"
            self.config_root(user)
            with self.assertRaisesRegex(RuntimeError, "previous application restored"):
                apply_update(
                    target, user, self.cfg, "0.4.0", "a" * 40,
                    FixtureNetwork(self.current, self.next, self.new),
                    health_check=fail_health,
                )
            self.assertEqual(target.read_bytes(), self.old)
            journal = json.loads((root / ".investment-finance-updates" / "journal.json").read_text())
            self.assertEqual(journal["stage"], "ROLLED_BACK")

    def test_interrupted_replace_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = (root / EXE_NAME).resolve()
            target.write_bytes(self.new)
            update_dir = root / ".investment-finance-updates"
            update_dir.mkdir()
            backup = update_dir / "previous.exe"
            backup.write_bytes(self.old)
            journal = update_dir / "journal.json"
            atomic_json(journal, {
                "stage": "REPLACED", "target": str(target), "backup": str(backup),
                "old_sha256": digest(backup),
            })
            self.assertTrue(recover(target, journal))
            self.assertEqual(target.read_bytes(), self.old)
            self.assertEqual(json.loads(journal.read_text())["stage"], "RECOVERED")

if __name__ == "__main__":
    unittest.main(verbosity=2)
