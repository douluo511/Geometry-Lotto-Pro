"""TDD security tests for the optional RFC3161 sidecar. No official A claim."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from research.harness_v46 import core, prospective_cycle
from research.harness_v46 import rfc3161_client as tsa
from research.harness_v46.tests.test_core import fixture


class TsaClientTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}

    def _context(self, root):
        db = Path(root) / "shadow.sqlite3"
        r = prospective_cycle.forecast_on_demand(self.snaps, db, now=self.now)
        commitment = prospective_cycle.build_predraw_commitment(db, r["run_id"])
        return db, commitment

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI unavailable: query integration blocked")
    def test_real_openssl_der_query_is_for_frozen_two_game_imprint(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            content_before = db.read_bytes()
            query = tsa.make_query(db, commitment)
            self.assertTrue(query.startswith(b"\x30"), "must be binary DER")
            path = Path(root) / "test.tsq"
            path.write_bytes(query)
            output = subprocess.run(
                ["openssl", "ts", "-query", "-in", str(path), "-text"],
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("Hash Algorithm: sha256", output)
            self.assertIn("Nonce:", output)
            self.assertEqual(db.read_bytes(), content_before)

    def test_network_request_is_https_only_no_credentials_or_redirect(self):
        with self.assertRaisesRegex(core.GateError, "TSA_HTTPS_URL_REQUIRED"):
            tsa.submit_query_https("http://freetsa.org/tsr", b"\x30\x00")
        with self.assertRaisesRegex(core.GateError, "TSA_HTTPS_URL_REQUIRED"):
            tsa.submit_query_https("https://u:p@freetsa.org/tsr", b"\x30\x00")
        with self.assertRaisesRegex(core.GateError, "TSA_HTTPS_URL_REQUIRED"):
            tsa.submit_query_https("https://localhost/tsr", b"\x30\x00")

    def test_bad_or_missing_trust_anchor_fails_before_crypto(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            with self.assertRaisesRegex(core.GateError, "TSA_TRUST_ANCHOR_REQUIRED"):
                tsa.verify_response(db, commitment, b"\x30\x00", b"\x30\x00", ca_file="")
            with self.assertRaisesRegex(core.GateError, "TSA_TRUST_ANCHOR_REQUIRED"):
                tsa.verify_response(db, commitment, b"\x30\x00", b"\x30\x00",
                                    ca_file=str(Path(root) / "not-there.pem"))

    def test_forged_commitment_is_rejected_before_crypto(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            fake = json.loads(json.dumps(commitment))
            fake["external_tsa"] = "VERIFIED"
            cafile = Path(root) / "root.pem"
            cafile.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")
            with self.assertRaisesRegex(core.GateError, "PREDRAW_COMMITMENT_LEDGER_MISMATCH"):
                tsa.verify_response(db, fake, b"\x30\x00", b"\x30\x00", ca_file=str(cafile))

    def test_verifier_checks_both_nonce_bound_request_and_exact_commitment_imprint(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            cafile = Path(root) / "root.pem"
            cafile.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")
            commands = []
            def fake_run(args, **kwargs):
                commands.append(args)
                if "-reply" in args:
                    return subprocess.CompletedProcess(args, 0,
                        stdout=b"Status info:\nStatus: Granted.\nTime stamp: Oct 20 08:05:00 2026 GMT\n", stderr=b"")
                return subprocess.CompletedProcess(args, 0, stdout=b"Verification: OK\n", stderr=b"")
            with mock.patch.object(tsa.subprocess, "run", side_effect=fake_run):
                result = tsa.verify_response(db, commitment, b"\x30\x00", b"\x30\x00",
                                             ca_file=str(cafile))
            self.assertEqual(sum("-verify" in c for c in commands), 2)
            self.assertTrue(any("-queryfile" in c for c in commands))
            self.assertTrue(any("-digest" in c and
                commitment["message_imprint_sha256"] in c for c in commands))
            self.assertEqual(result["cryptographic_check"], "PASS_CALLER_ANCHOR")
            self.assertEqual(result["cutoff_relation"], "BEFORE_BOTH_DECLARED_CUTOFFS_UNVERIFIED")
            self.assertFalse(result["independent_cutoff_authenticated"])
            self.assertFalse(result["trust_anchor_independently_approved"])
            self.assertEqual(result["formal_A"], 0)
            self.assertEqual(result["decision"], "NO_EDGE")

    def test_timestamp_after_declared_cutoff_must_fail(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            cafile = Path(root) / "root.pem"
            cafile.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")
            def fake_run(args, **kwargs):
                if "-reply" in args:
                    return subprocess.CompletedProcess(args, 0,
                        stdout=b"Status info:\nTime stamp: Oct 24 08:05:00 2026 GMT\n", stderr=b"")
                return subprocess.CompletedProcess(args, 0, stdout=b"Verification: OK\n", stderr=b"")
            with mock.patch.object(tsa.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(core.GateError, "TSA_AFTER_DECLARED_SALES_CUTOFF"):
                    tsa.verify_response(db, commitment, b"\x30\x00", b"\x30\x00",
                                        ca_file=str(cafile))

    def test_invalid_crypto_return_code_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            db, commitment = self._context(root)
            cafile = Path(root) / "root.pem"
            cafile.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n")
            with mock.patch.object(tsa.subprocess, "run", return_value=
                    subprocess.CompletedProcess(["openssl"], 1, stdout=b"", stderr=b"bad signature")):
                with self.assertRaisesRegex(core.GateError, "TSA_OPENSSL_VERIFICATION_FAILED"):
                    tsa.verify_response(db, commitment, b"\x30\x00", b"\x30\x00",
                                        ca_file=str(cafile))


    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI absent")
    def test_actual_ephemeral_tsa_signature_chain_nonce_and_imprint(self):
        """Cryptographic integration with a disposable TEST root, never official TSA."""
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            future = {
                game: {**s,
                       "sales_cutoff": "2028-10-23T12:00:00+08:00",
                       "target_draw_at": "2028-10-23T21:00:00+08:00"}
                for game, s in self.snaps.items()
            }
            db = base / "future.sqlite3"
            frozen = prospective_cycle.forecast_on_demand(future, db, now=self.now)
            commitment = prospective_cycle.build_predraw_commitment(db, frozen["run_id"])
            def run(*args):
                return subprocess.run(["openssl", *map(str, args)], check=True,
                                      capture_output=True)
            ca_conf = base / "ca.cnf"
            ca_conf.write_text(
                "[req]\ndistinguished_name=req_dn\nx509_extensions=ca_ext\nprompt=no\n"
                "[req_dn]\nCN=Ephemeral test root\n[ca_ext]\n"
                "basicConstraints=critical,CA:TRUE\n"
                "keyUsage=critical,keyCertSign,cRLSign\n")
            run("req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", base / "ca.key", "-out", base / "ca.crt",
                "-days", "1", "-config", ca_conf)
            run("req", "-new", "-newkey", "rsa:2048", "-nodes",
                "-keyout", base / "tsa.key", "-out", base / "tsa.csr",
                "-subj", "/CN=Ephemeral test TSA")
            extensions = base / "tsa.ext"
            extensions.write_text(
                "basicConstraints=critical,CA:FALSE\n"
                "extendedKeyUsage=critical,timeStamping\n"
                "keyUsage=critical,digitalSignature,nonRepudiation\n"
                "subjectKeyIdentifier=hash\n"
                "authorityKeyIdentifier=keyid,issuer\n")
            run("x509", "-req", "-in", base / "tsa.csr",
                "-CA", base / "ca.crt", "-CAkey", base / "ca.key",
                "-CAcreateserial", "-out", base / "tsa.crt",
                "-days", "1", "-extfile", extensions)
            (base / "tsa.serial").write_text("01\n")
            cfg = base / "tsa.cnf"
            cfg.write_text(
                "[tsa]\ndefault_tsa=tsa_config\n[tsa_config]\n"
                f"serial={ (base / 'tsa.serial').as_posix() }\n"
                f"signer_cert={ (base / 'tsa.crt').as_posix() }\n"
                f"certs={ (base / 'ca.crt').as_posix() }\n"
                f"signer_key={ (base / 'tsa.key').as_posix() }\n"
                "signer_digest=sha256\ndefault_policy=1.2.3.4.1\n"
                "digests=sha256\naccuracy=secs:1\nordering=yes\n"
                "tsa_name=yes\ness_cert_id_chain=yes\n")
            query = tsa.make_query(db, commitment)
            (base / "request.tsq").write_bytes(query)
            run("ts", "-reply", "-config", cfg, "-queryfile",
                base / "request.tsq", "-out", base / "response.tsr")
            response = (base / "response.tsr").read_bytes()
            accepted = tsa.verify_response(
                db, commitment, query, response, ca_file=str(base / "ca.crt")
            )
            self.assertEqual(accepted["cryptographic_check"], "PASS_CALLER_ANCHOR")
            self.assertEqual(accepted["research_admission"], "BLOCKED")
            self.assertFalse(accepted["independent_cutoff_authenticated"])
            self.assertEqual(accepted["formal_A"], 0)

            # Same signed response must fail a fresh random-nonce request.
            different_query = tsa.make_query(db, commitment)
            self.assertNotEqual(query, different_query)
            with self.assertRaisesRegex(core.GateError, "TSA_OPENSSL_VERIFICATION_FAILED"):
                tsa.verify_response(db, commitment, different_query, response,
                                    ca_file=str(base / "ca.crt"))
            # A different, valid but unapproved root is not an acceptable chain.
            run("req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", base / "wrong.key", "-out", base / "wrong.crt",
                "-days", "1", "-config", ca_conf)
            with self.assertRaisesRegex(core.GateError, "TSA_OPENSSL_VERIFICATION_FAILED"):
                tsa.verify_response(db, commitment, query, response,
                                    ca_file=str(base / "wrong.crt"))


if __name__ == "__main__":
    unittest.main()
