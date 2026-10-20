"""Only newly generated synthetic local fixtures; no network or historical data."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.ssq_dlt_time_probe.verifier import (
    Inputs, Recorder, VerificationError, deadline_allows, one,
    parse_generalized_time, parse_query, parse_response, verify_offline,
)


def find_openssl():
    candidate = shutil.which("openssl")
    if candidate:
        return Path(candidate)
    candidate = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
    if candidate.is_file():
        return candidate
    raise RuntimeError("OpenSSL executable is required for synthetic verifier tests")


class SyntheticVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="ssq-dlt-synthetic-tsa-")
        cls.base = Path(cls.temporary.name)
        cls.openssl = find_openssl()

        def run(*args):
            result = subprocess.run([str(cls.openssl), *args], cwd=cls.base, capture_output=True, timeout=25)
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", "replace"))

        run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "2",
            "-subj", "/CN=SYNTHETIC_TEST_ROOT_NOT_PUBLIC_TRUST", "-keyout", "root.key", "-out", "root.pem",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-subj", "/CN=SYNTHETIC_TEST_TSA",
            "-keyout", "signer.key", "-out", "signer.csr")
        (cls.base / "extensions.cnf").write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=critical,timeStamping\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n", encoding="ascii")
        run("x509", "-req", "-in", "signer.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial",
            "-days", "1", "-extfile", "extensions.cnf", "-out", "signer.pem")
        (cls.base / "payload.bin").write_bytes(b"SYNTHETIC LOCAL RFC3161 TEST FIXTURE ONLY\n")
        run("ts", "-query", "-data", "payload.bin", "-sha256", "-cert", "-out", "request.tsq")
        (cls.base / "serial.txt").write_text("01\n", encoding="ascii")
        (cls.base / "tsa.cnf").write_text("[tsa]\ndefault_tsa=synthetic\n[synthetic]\nserial=serial.txt\nsigner_cert=signer.pem\nsigner_key=signer.key\ncerts=root.pem\nsigner_digest=sha256\ndefault_policy=1.2.3.4\nother_policies=1.2.3.4\ndigests=sha256\naccuracy=secs:1\nordering=yes\ntsa_name=yes\ness_cert_id_chain=no\ness_cert_id_alg=sha256\n", encoding="ascii")
        run("ts", "-reply", "-config", "tsa.cnf", "-queryfile", "request.tsq", "-out", "response.tsr")
        cls.inputs = Inputs(cls.base / "payload.bin", cls.base / "request.tsq", cls.base / "response.tsr",
                            cls.base / "root.pem", cls.base / "signer.pem",
                            hashlib.sha256((cls.base / "root.pem").read_bytes()).hexdigest(),
                            hashlib.sha256((cls.base / "signer.pem").read_bytes()).hexdigest())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_positive_and_specific_negative_checks(self):
        receipt = verify_offline(self.inputs, self.base / "verified", self.openssl)
        self.assertEqual(receipt["technical_status"], "PASS", receipt)
        self.assertTrue(all(item["status"] == "PASS" for item in receipt["checks"]))
        self.assertFalse(receipt["formal_approval"])
        self.assertFalse(receipt["historical_asof_proof"])
        self.assertEqual(receipt["network_operations"], 0)
        self.assertEqual(receipt["A"], 0)
        self.assertEqual(receipt["revocation_check"], "NOT_RUN")
        names = [item["name"] for item in receipt["checks"]]
        for name in ("tampered-payload-rejected", "different-nonce-rejected", "tampered-signature-rejected", "wrong-trust-rejected", "synthetic-past-deadline-rejected"):
            self.assertIn(name, names)
            self.assertGreater(names.index(name), names.index("all-positive-checks-before-negatives"))

    def test_wrong_pin_fails_before_verification(self):
        wrong = Inputs(self.inputs.payload, self.inputs.query, self.inputs.response, self.inputs.root, self.inputs.signer,
                       "0" * 64, self.inputs.signer_raw_sha256)
        receipt = verify_offline(wrong, self.base / "wrong-pin", self.openssl)
        self.assertEqual(receipt["technical_status"], "FAIL")
        self.assertEqual(receipt["checks"][0]["name"], "root-raw-pin")
        self.assertEqual(receipt["checks"][0]["status"], "FAIL")
        self.assertEqual(receipt["checks"][-1]["status"], "PASS")

    def test_output_directory_is_exclusive(self):
        existing = self.base / "existing-output"
        existing.mkdir()
        (existing / "sentinel").write_bytes(b"KEEP")
        with self.assertRaises(FileExistsError):
            verify_offline(self.inputs, existing, self.openssl)
        self.assertEqual((existing / "sentinel").read_bytes(), b"KEEP")

    def test_missing_openssl_retains_blocked_receipt(self):
        out = self.base / "missing-openssl-receipt"
        receipt = verify_offline(self.inputs, out, self.base / "no-openssl-executable")
        self.assertEqual(receipt["technical_status"], "BLOCKED")
        self.assertIsNone(receipt["openssl_sha256"])
        self.assertTrue((out / "RECEIPT.json").is_file())
        self.assertFalse(any(x["name"] == "all-positive-checks-before-negatives" for x in receipt["checks"]))

    def test_request_and_response_imprint_and_nonce(self):
        request = parse_query(self.inputs.query.read_bytes())
        response = parse_response(self.inputs.response.read_bytes())
        expected = hashlib.sha256(self.inputs.payload.read_bytes()).digest()
        self.assertEqual(request["digest"], expected)
        self.assertEqual(response["digest"], expected)
        self.assertEqual(request["nonce"], response["nonce"])
        self.assertEqual(response["policy_oid"], "1.2.3.4")
        self.assertEqual(response["accuracy_seconds"], 1)

    def test_der_trailing_truncated_and_nonminimal_rejected(self):
        for data in (b"\x30\x00\x00", b"\x30\x01", b"\x30\x80\x00\x00", b"\x30\x81\x00"):
            with self.subTest(data=data), self.assertRaises(VerificationError):
                one(data)

    def test_unknown_options_and_timeouts_are_not_negative_passes(self):
        recorder = Recorder(self.base, self.openssl)
        for code, text in ((1, "unknown option: no-CApath; message imprint mismatch"),
                           (None, "message imprint mismatch"), (0, "message imprint mismatch"),
                           (1, "No such file; nonce mismatch"), (1, "Verification: FAILED")):
            with self.subTest(code=code, text=text), self.assertRaises(VerificationError):
                recorder.rejected("must-not-pass", code, text, r"message imprint mismatch|nonce mismatch")

    def test_deadline_is_strict_and_unknown_accuracy_fails_closed(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.assertFalse(deadline_allows(now, now, 0))
        self.assertFalse(deadline_allows(now, now + timedelta(seconds=1), 1))
        self.assertTrue(deadline_allows(now, now + timedelta(seconds=2), 1))
        self.assertFalse(deadline_allows(now, now + timedelta(days=1), None))
        with self.assertRaises(VerificationError):
            deadline_allows(now.replace(tzinfo=None), now, 0)
        for accuracy in (-1, float("nan"), float("inf")):
            with self.subTest(accuracy=accuracy), self.assertRaises(VerificationError):
                deadline_allows(now, now + timedelta(seconds=2), accuracy)

    def test_signed_generalized_time_supports_fraction_and_requires_utc(self):
        value = parse_generalized_time(b"20261020172333.123Z")
        self.assertEqual(value.microsecond, 123000)
        for bad in (b"20261020172333+0000", b"20261020172333.1234567Z", b"20261320172333Z"):
            with self.subTest(bad=bad), self.assertRaises((VerificationError, ValueError)):
                parse_generalized_time(bad)


if __name__ == "__main__":
    unittest.main()
