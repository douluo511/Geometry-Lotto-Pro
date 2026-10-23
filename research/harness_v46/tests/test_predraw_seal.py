"""Invented forecasts and a local test CA; never official/TSA evidence."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46 import core, prospective_cycle
from research.harness_v46.tests.test_core import fixture


class PredrawSealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openssl = shutil.which("openssl")
        fallback = Path("C:/Program Files/Git/usr/bin/openssl.exe")
        if not cls.openssl and fallback.is_file():
            cls.openssl = str(fallback)
        if not cls.openssl:
            raise RuntimeError("OpenSSL is required for real RFC3161 counterexamples")
        cls.ca_tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.ca_tmp.name)
        cls._cmd("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                 "-subj", "/CN=TEST ONLY CA", "-keyout", "ca.key", "-out", "ca.pem",
                 "-addext", "basicConstraints=critical,CA:TRUE")
        cls._cmd("req", "-new", "-newkey", "rsa:2048", "-nodes",
                 "-subj", "/CN=TEST ONLY TSA", "-keyout", "tsa.key", "-out", "tsa.csr")
        (cls.root / "tsa.ext").write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=critical,timeStamping\n", encoding="ascii")
        cls._cmd("x509", "-req", "-in", "tsa.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                 "-CAcreateserial", "-days", "2", "-out", "tsa.pem", "-extfile", "tsa.ext")
        (cls.root / "serial").write_text("01\n", encoding="ascii")
        (cls.root / "tsa.cnf").write_text(
            "[tsa]\ndefault_tsa=local\n[local]\nserial=serial\n"
            "signer_cert=tsa.pem\ncerts=ca.pem\nsigner_key=tsa.key\n"
            "signer_digest=sha256\ndefault_policy=1.2.3.4\ndigests=sha256\n"
            "accuracy=secs:1\nordering=yes\ntsa_name=yes\ness_cert_id_chain=no\n",
            encoding="ascii")
        cls.pin = hashlib.sha256((cls.root / "ca.pem").read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.ca_tmp.cleanup()

    @classmethod
    def _cmd(cls, *args):
        result = subprocess.run([cls.openssl, *args], cwd=cls.root, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode(errors="replace"))
        return result.stdout

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "ledger.sqlite3"
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.snaps = {g: fixture(g) for g in core.RULES}
        for snap in self.snaps.values():
            snap["as_of"] = (self.now - timedelta(hours=1)).isoformat()
            snap["sales_cutoff"] = (self.now + timedelta(days=1)).isoformat()
            snap["target_draw_at"] = (self.now + timedelta(days=1, hours=1)).isoformat()
        self.run_id = prospective_cycle.forecast_on_demand(
            self.snaps, self.db, now=self.now - timedelta(seconds=10))["run_id"]

    def seal_module(self):
        # Import inside the test: the initial RED must identify the missing feature.
        from research.harness_v46 import predraw_seal
        return predraw_seal

    def prepare(self, name="seal", **kwargs):
        return self.seal_module().prepare_request(
            self.db, self.run_id, self.dir / name,
            trust_root_sha256=self.pin, openssl=self.openssl, now=self.now, **kwargs)

    def sign(self, name="seal"):
        request = self.dir / name / "request.tsq"
        response = self.dir / (name + ".tsr")
        self._cmd("ts", "-reply", "-config", "tsa.cnf", "-queryfile", str(request),
                  "-out", str(response))
        return response

    def verify(self, response, name="seal", **kwargs):
        return self.seal_module().verify_response(
            self.db, self.run_id, self.dir / name, response, self.root / "ca.pem",
            trust_root_sha256=self.pin, openssl=self.openssl, **kwargs)

    def test_export_binds_both_original_snapshots_manifest_and_twelve_predictions(self):
        before = self.db.read_bytes()
        result = self.prepare()
        envelope = json.loads((self.dir / "seal" / "payload.json").read_bytes())
        self.assertEqual(envelope["run_id"], self.run_id)
        self.assertEqual(envelope["snapshots"], self.snaps)
        self.assertEqual(envelope["manifest"]["run_id"], self.run_id)
        self.assertEqual(set(envelope["games"]), set(core.RULES))
        for game in core.RULES:
            self.assertEqual(len(envelope["games"][game]["predictions"]), 6)
        self.assertEqual(result["external_tsa"], "REQUEST_ONLY_NOT_VERIFIED")
        self.assertEqual(before, self.db.read_bytes())

    def test_real_signature_verifies_under_explicit_test_pin_without_promoting_formal_a(self):
        self.prepare()
        before = self.db.read_bytes()
        receipt = self.verify(self.sign())
        self.assertEqual(receipt["cryptographic_verification"], "PASS_UNDER_CALLER_PIN")
        self.assertEqual(receipt["predraw_time_bound"], "BEFORE_BOTH_CLAIMED_CUTOFFS")
        self.assertEqual(receipt["trust_policy"], "CALLER_SUPPLIED_UNVERIFIED")
        self.assertEqual(receipt["official_target_admission"], "BLOCKED")
        self.assertEqual(receipt["formal_A"], 0)
        self.assertEqual(receipt["decision"], "NO_EDGE")
        self.assertEqual(before, self.db.read_bytes())

    def test_cutoff_prevents_request_and_creates_no_directory(self):
        with self.assertRaisesRegex(core.GateError, "SEAL_REQUEST_AFTER_CUTOFF"):
            self.seal_module().prepare_request(
                self.db, self.run_id, self.dir / "late", trust_root_sha256=self.pin,
                openssl=self.openssl, now=self.now + timedelta(days=1))
        self.assertFalse((self.dir / "late").exists())

    def test_existing_seal_is_never_overwritten(self):
        self.prepare()
        original = (self.dir / "seal" / "request.tsq").read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(original, (self.dir / "seal" / "request.tsq").read_bytes())

    def test_naive_clock_and_unpinned_root_are_rejected(self):
        for pin, now in ((self.pin, self.now.replace(tzinfo=None)), ("", self.now)):
            with self.subTest(pin=pin), self.assertRaises(core.GateError):
                self.seal_module().prepare_request(
                    self.db, self.run_id, self.dir / "invalid", trust_root_sha256=pin,
                    openssl=self.openssl, now=now)
        self.assertFalse((self.dir / "invalid").exists())

    def test_changed_export_cannot_be_verified(self):
        self.prepare()
        response = self.sign()
        payload = self.dir / "seal" / "payload.json"
        content = json.loads(payload.read_bytes())
        content["games"]["SSQ"]["predictions"][0]["payload"]["primary_d2"] = [32, 33]
        payload.write_text(core.canon(content), encoding="utf-8")
        with self.assertRaisesRegex(core.GateError, "SEAL_PAYLOAD_DIFFERS_FROM_LEDGER"):
            self.verify(response)

    def test_swapped_valid_nonce_response_is_rejected(self):
        self.prepare()
        self.prepare("other")
        # Same exact payload digest, independent nonce: digest-only verification is insufficient.
        with self.assertRaisesRegex(core.GateError, "RFC3161_VERIFY_FAILED"):
            self.verify(self.sign("other"))

    def test_corrupt_response_and_wrong_root_pin_are_rejected(self):
        self.prepare()
        response = self.sign()
        with self.assertRaisesRegex(core.GateError, "TRUST_ROOT_PIN_MISMATCH"):
            self.seal_module().verify_response(
                self.db, self.run_id, self.dir / "seal", response, self.root / "tsa.pem",
                trust_root_sha256=self.pin, openssl=self.openssl)
        response.write_bytes(b"not a timestamp")
        with self.assertRaisesRegex(core.GateError, "RFC3161_VERIFY_FAILED"):
            self.verify(response)

    def test_replaced_no_nonce_request_and_valid_response_are_rejected(self):
        self.prepare()
        root = self.dir / "seal"
        self._cmd("ts", "-query", "-data", str(root / "payload.json"), "-sha256",
                  "-no_nonce", "-cert", "-out", str(root / "request.tsq"))
        with self.assertRaisesRegex(core.GateError, "RFC3161_NONCE_REQUIRED"):
            self.verify(self.sign())

    def test_signed_time_after_locked_cutoff_is_rejected(self):
        # Freeze a separate test record in the past, prepare with an injected test
        # clock, then actually sign now. A valid signature cannot excuse late sealing.
        snaps = {g: fixture(g) for g in core.RULES}
        for snap in snaps.values():
            snap["as_of"] = (self.now - timedelta(days=2)).isoformat()
            snap["sales_cutoff"] = (self.now - timedelta(hours=1)).isoformat()
            snap["target_draw_at"] = (self.now + timedelta(hours=1)).isoformat()
        db = self.dir / "past.sqlite3"
        frozen_at = self.now - timedelta(days=1)
        run = prospective_cycle.forecast_on_demand(snaps, db, now=frozen_at)["run_id"]
        self.seal_module().prepare_request(
            db, run, self.dir / "late", trust_root_sha256=self.pin,
            openssl=self.openssl, now=frozen_at + timedelta(seconds=1))
        response = self.sign("late")
        with self.assertRaisesRegex(core.GateError, "TOKEN_NOT_STRICTLY_PREDRAW"):
            self.seal_module().verify_response(
                db, run, self.dir / "late", response, self.root / "ca.pem",
                trust_root_sha256=self.pin, openssl=self.openssl)


if __name__ == "__main__":
    unittest.main()
