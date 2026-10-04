from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.update_runtime import (UpdateBlocked, ReleaseNetwork, apply_update, atomic_json, config,
                                digest, health, recover, semver, verify_manifest)


class FixtureNetwork:
    """Offline protocol fixture, never production Release evidence."""
    def __init__(self, manifest, payload):
        self.manifest, self.payload = manifest, payload
        self.current_manifest = None
    def json(self, url):
        selected=self.current_manifest if "v0.1.0" in url else self.manifest
        if "/git/ref/tags/" in url:
            return {"object":{"type":"commit", "sha":selected["source_sha"]}}
        if "api.github.com" in url:
            return {"draft": False, "prerelease": False, "tag_name": selected["release_id"],
                    "assets": [{"name": "RealMoneyFinance.exe", "browser_download_url": selected["artifact"]["url"],
                                "size": selected["artifact"]["size"]}]}
        return selected
    def download(self, url, target, expected_size):
        target.write_bytes(self.payload)


class UpdaterContracts(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.cfg = {"enabled": True, "repository": "fixture-owner/fixture-independent-rmf",
                    "manifest_url": "https://raw.githubusercontent.com/fixture-owner/fixture-independent-rmf/main/release-manifest.json",
                    "trusted_public_key_hex": self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()}
        self.payload = b"MZOFFLINE-PROTOCOL-FIXTURE-NEW"
        self.manifest = {"schema_version": 1, "product": "RealMoneyFinance", "repository": self.cfg["repository"],
                         "version": "0.2.0", "release_id": "v0.2.0", "source_sha": "b" * 40,
                         "artifact": {"name": "RealMoneyFinance.exe", "size": len(self.payload),
                                      "sha256": hashlib.sha256(self.payload).hexdigest(),
                                      "url": "https://github.com/fixture-owner/fixture-independent-rmf/releases/download/v0.2.0/RealMoneyFinance.exe"}}
        self.sign(self.manifest)
        self.current_manifest=copy.deepcopy(self.manifest)
        self.current_manifest.update(version="0.1.0", release_id="v0.1.0", source_sha="a"*40)
        old_payload=b"MZOFFLINE-PROTOCOL-FIXTURE-OLD"
        self.current_manifest["artifact"].update(size=len(old_payload), sha256=hashlib.sha256(old_payload).hexdigest(),
                                                 url="https://github.com/fixture-owner/fixture-independent-rmf/releases/download/v0.1.0/RealMoneyFinance.exe")
        self.sign(self.current_manifest)

    def sign(self, obj):
        obj.pop("signature", None)
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        obj["signature"] = base64.b64encode(self.private.sign(canonical)).decode("ascii")

    def install(self, root, *, health_check=None, launch_app=None, network=None):
        target = root / "RealMoneyFinance.exe"
        if not target.exists():
            target.write_bytes(b"MZOFFLINE-PROTOCOL-FIXTURE-OLD")
        if health_check is None:
            def health_check(target, user_root, expected):
                self.assertEqual(digest(target), expected["sha256"])
        if launch_app is None:
            launch_app = lambda target, user_root: None
        network=network or FixtureNetwork(self.manifest, self.payload)
        network.current_manifest=self.current_manifest
        return apply_update(target, root / "userdata", self.cfg, "0.1.0", "a" * 40,
                            network,
                            health_check=health_check, launch_app=launch_app)

    def test_valid_signature_upgrade_backup_commit_and_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            launches = []
            result = self.install(root, launch_app=lambda target, user_root: launches.append(digest(target)))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(launches, [hashlib.sha256(self.payload).hexdigest()])
            self.assertEqual((root / ".rmf-updates" / "previous.exe").read_bytes(), b"MZOFFLINE-PROTOCOL-FIXTURE-OLD")
            self.assertEqual(json.loads((root / ".rmf-updates" / "journal.json").read_text())["stage"], "COMMITTED")

    def test_unsigned_tamper_rejected(self):
        self.manifest["source_sha"] = "c" * 40
        with self.assertRaises(InvalidSignature):
            verify_manifest(self.manifest, self.cfg, "0.1.0")

    def test_signed_wrong_identity_downgrade_size_and_origin_rejected(self):
        for field, value in (("product", "OtherProduct"), ("repository", "elsewhere/repo"),
                             ("version", "0.1.0"), ("version", "0.0.9"), ("release_id", "v99.0.0"),
                             ("source_sha", "short")):
            with self.subTest(field=field, value=value):
                obj = copy.deepcopy(self.manifest)
                obj[field] = value
                self.sign(obj)
                with self.assertRaises(ValueError):
                    verify_manifest(obj, self.cfg, "0.1.0")
        for field, value in (("name", "Other.exe"), ("size", True), ("size", 200 * 1024 * 1024),
                             ("url", "http://github.com/unsafe.exe"), ("sha256", "broken")):
            with self.subTest(field=field):
                obj = copy.deepcopy(self.manifest)
                obj["artifact"][field] = value
                self.sign(obj)
                with self.assertRaises(ValueError):
                    verify_manifest(obj, self.cfg, "0.1.0")

    def test_strict_semver_rejected(self):
        for value in ("0.1", "v0.1.0", "0.1.0-beta", "01.2.3", "1.2.3.4", "1.2.3junk"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                semver(value)

    def test_download_corruption_does_not_change_target(self):
        for payload in (b"MZBAD", self.payload + b"oversized", b"not-pe"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with self.assertRaises(ValueError):
                    self.install(root, network=FixtureNetwork(self.manifest, payload))
                self.assertEqual((root / "RealMoneyFinance.exe").read_bytes(), b"MZOFFLINE-PROTOCOL-FIXTURE-OLD")

    def test_health_failure_rolls_back_and_quarantines_release(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checked = []
            def reject_new(target, user_root, expected):
                checked.append(expected["version"])
                if expected["version"] == "0.2.0":
                    raise RuntimeError("fixture new health failure")
                self.assertEqual(digest(target), expected["sha256"])
            with self.assertRaisesRegex(RuntimeError, "previous application restored"):
                self.install(root, health_check=reject_new)
            self.assertEqual(checked, ["0.2.0", "0.1.0"])
            self.assertEqual((root / "RealMoneyFinance.exe").read_bytes(), b"MZOFFLINE-PROTOCOL-FIXTURE-OLD")
            with self.assertRaises(UpdateBlocked):
                self.install(root)

    def test_launch_failure_rolls_back_and_relaunches_old(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            launched = []
            def fail_new(target, user_root):
                value = target.read_bytes()
                launched.append(value)
                if value == self.payload:
                    raise OSError("fixture launch failed")
            with self.assertRaisesRegex(RuntimeError, "previous application restored"):
                self.install(root, launch_app=fail_new)
            self.assertEqual(launched, [self.payload, b"MZOFFLINE-PROTOCOL-FIXTURE-OLD"])

    def test_interrupted_replace_recovers_original_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "RealMoneyFinance.exe"
            target.write_bytes(self.payload)
            journal = root / ".rmf-updates" / "journal.json"
            backup = journal.parent / "previous.exe"
            backup.parent.mkdir()
            backup.write_bytes(b"MZOLD")
            atomic_json(journal, {"stage": "REPLACED", "target": str(target.resolve()), "backup": str(backup), "old_sha256": digest(backup)})
            recover(target.resolve(), journal)
            self.assertEqual(target.read_bytes(), b"MZOLD")
            self.assertEqual(json.loads(journal.read_text())["stage"], "RECOVERED")

    def test_rollback_failure_retains_journal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def reject_all(*args):
                raise RuntimeError("fixture health fails on new and restored old")
            with self.assertRaisesRegex(RuntimeError, "rollback needs recovery"):
                self.install(root, health_check=reject_all)
            journal = json.loads((root / ".rmf-updates" / "journal.json").read_text())
            self.assertEqual(journal["stage"], "ROLLBACK_FAILED")

    def test_missing_production_config_and_monorepo_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(UpdateBlocked):
                config(root)
            atomic_json(root / "updater.json", {**self.cfg, "repository": "douluo511/Geometry-Lotto-Pro"})
            with self.assertRaises(UpdateBlocked):
                config(root)

    def test_network_timeout_has_exact_bounded_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            network = ReleaseNetwork(Path(td) / "requests.jsonl")
            with patch.object(network.session, "get", side_effect=requests.Timeout("fixture timeout")) as get, patch("time.sleep"):
                with self.assertRaises(requests.Timeout):
                    network.request("https://github.com/fixture/repo")
                self.assertEqual(get.call_count, 3)

    def test_redirect_downgrade_rejected_before_request(self):
        class Response:
            status_code = 302
            headers = {"Location": "http://github.com/unsafe"}
            def raise_for_status(self): pass
            def close(self): pass
        with tempfile.TemporaryDirectory() as td:
            network = ReleaseNetwork(Path(td) / "requests.jsonl")
            with patch.object(network.session, "get", return_value=Response()) as get:
                with self.assertRaises(ValueError):
                    network.request("https://github.com/fixture/repo")
                self.assertEqual(get.call_count, 1)

    def test_false_success_health_report_identity_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "RealMoneyFinance.exe"
            target.write_bytes(self.payload)
            expected={"version":"0.2.0", "source_sha":"b"*40, "sha256":digest(target)}
            def false_success(command, **kwargs):
                report=Path(command[command.index("--health-report")+1])
                nonce=command[command.index("--health-nonce")+1]
                atomic_json(report, {"status":"PASS", "product":"RealMoneyFinance", "storage_integrity":"ok",
                                     "nonce":nonce, "version":"0.2.0", "source_sha":"c"*40, "exe_sha256":digest(target)})
                return SimpleNamespace(returncode=0)
            with patch("app.update_runtime.subprocess.run", side_effect=false_success):
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    health(target, root, expected)

    def test_prerelease_not_admitted_as_production_release(self):
        class PrereleaseNetwork(FixtureNetwork):
            def json(self, url):
                obj=super().json(url)
                if "api.github.com" in url:
                    obj["prerelease"]=True
                return obj
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "formal production Release"):
                self.install(Path(td), network=PrereleaseNetwork(self.manifest, self.payload))

    def test_current_n_installed_hash_must_match_signed_formal_release(self):
        self.current_manifest["artifact"]["sha256"]="d"*64
        self.sign(self.current_manifest)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "formally signed production Release N"):
                self.install(Path(td))

    def test_release_tag_exact_source_mismatch_rejected(self):
        class WrongTagNetwork(FixtureNetwork):
            def json(self, url):
                obj=super().json(url)
                if "/git/ref/tags/" in url:
                    obj["object"]["sha"]="e"*40
                return obj
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "tag commit differs"):
                self.install(Path(td), network=WrongTagNetwork(self.manifest, self.payload))

    def test_parent_exit_is_waited_before_recovery_or_replacement(self):
        order=[]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            target=root/"RealMoneyFinance.exe"
            target.write_bytes(b"MZOFFLINE-PROTOCOL-FIXTURE-OLD")
            network=FixtureNetwork(self.manifest,self.payload)
            network.current_manifest=self.current_manifest
            with patch("app.update_runtime.wait_parent", side_effect=lambda pid:order.append("wait")), patch("app.update_runtime.recover", side_effect=lambda *args:order.append("recover")):
                apply_update(target,root/"userdata",self.cfg,"0.1.0","a"*40,network,parent_pid=999,
                             health_check=lambda *args:None,launch_app=lambda *args:None)
            self.assertEqual(order,["wait","recover"])


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(UpdaterContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence = {"status": "PASS" if result.wasSuccessful() else "FAIL", "test_count": result.testsRun,
                "failure_count": len(result.failures), "error_count": len(result.errors),
                "evidence_kind": "OFFLINE_CONTRACT_AND_FAULT_FIXTURES", "real_production_release_n_to_n_plus_1": "BLOCKED"}
    Path("updater_contract_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
