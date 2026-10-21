"""Real loopback/TLS checks; missing prerequisites must fail as BLOCKED, not skip."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import smtplib
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest

from research.ssq_dlt_process_faults.smtp_fixture import (
    FixtureBlocked, HOST, LoopbackSMTP, PORT, SYNTHETIC_ADDRESS,
    SYNTHETIC_PASSWORD, SYNTHETIC_USERNAME,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
FLUSH_CHILD = r'''
import json
from pathlib import Path
import sys
from research.ssq_dlt_v45 import delivery
from research.ssq_dlt_v45.store import Store
root = Path(sys.argv[1])
store = Store(root / "synthetic.sqlite3")
report = {"scope": "SYNTHETIC_TEST_ONLY", "formal_A": 0, "decision": "NO_EDGE"}
delivery.prepare(store, root / "outbox", "synthetic@example.invalid", report,
                 "<p>SYNTHETIC ONLY</p>")
smtp = json.loads(sys.argv[2])
results = [delivery.flush(store, smtp), delivery.flush(store, smtp)]
print(json.dumps({"results": results, "sent": store.rows("sent"),
                  "send_started": store.rows("send_started")}))
'''


class LoopbackSMTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glp-synthetic-smtp-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def connect(self, server):
        client = smtplib.SMTP(HOST, PORT, timeout=5)
        self.addCleanup(client.close)
        client.ehlo()
        client.starttls(context=ssl.create_default_context(cafile=str(server.ca_path)))
        client.ehlo()
        return client

    def flush_child(self, server):
        environment = dict(os.environ, **server.child_env)
        completed = subprocess.run(
            [sys.executable, "-c", FLUSH_CHILD, str(self.root / "worker"), json.dumps(server.smtp_config)],
            cwd=REPO_ROOT, env=environment, capture_output=True, text=True, timeout=20, check=True,
        )
        return json.loads(completed.stdout)

    def test_real_starttls_plain_auth_data_hash_and_immutable_logs(self):
        original_ca = os.environ.get("SSL_CERT_FILE")
        data = b"Subject: SYNTHETIC ONLY\r\n\r\n.first\r\nlast\r\n"
        with LoopbackSMTP(self.root / "server") as server:
            client = self.connect(server)
            client.login(SYNTHETIC_USERNAME, SYNTHETIC_PASSWORD)
            self.assertEqual(client.sendmail(SYNTHETIC_ADDRESS, SYNTHETIC_ADDRESS, data), {})
            receipt = server.wait_for_ack()
            self.assertEqual(receipt.data_sha256, hashlib.sha256(data).hexdigest())
            self.assertEqual(receipt.data_bytes, len(data))
            self.assertEqual(receipt.recipients, (SYNTHETIC_ADDRESS,))
            self.assertEqual(server.wait_for_data(), receipt)
            self.assertEqual(server.stats, dict(connections=1, authenticated_connections=1,
                                                data_transactions=1, acknowledgements=1))
            with self.assertRaises(FrozenInstanceError):
                receipt.data_bytes = 0
            self.assertIsInstance(server.events, tuple)
            commands = [event.command for event in server.events if event.kind == "command"]
            self.assertEqual(commands[:7], ["EHLO", "STARTTLS", "EHLO", "AUTH", "MAIL", "RCPT", "DATA"])
            client.quit()
        self.assertFalse(server.is_running)
        self.assertEqual(original_ca, os.environ.get("SSL_CERT_FILE"))
        self.assertNotIn(SYNTHETIC_PASSWORD, server.events_path.read_text())
        self.assertEqual(len(server.receipts_path.read_text().splitlines()), 1)

    def test_login_auth_and_non_synthetic_recipient_rejected(self):
        with LoopbackSMTP(self.root / "server") as server:
            client = self.connect(server)
            client.user, client.password = SYNTHETIC_USERNAME, SYNTHETIC_PASSWORD
            self.assertEqual(client.auth("LOGIN", client.auth_login)[0], 235)
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                client.sendmail(SYNTHETIC_ADDRESS, "other@example.invalid", b"Subject: rejected\r\n\r\nbody")
            self.assertEqual(server.stats["data_transactions"], 0)
            self.assertEqual(server.stats["authenticated_connections"], 1)

    def test_real_legacy_flush_success_then_sent_previously(self):
        with LoopbackSMTP(self.root / "server") as server:
            result = self.flush_child(server)
            server.wait_for_ack()
            self.assertEqual([row[0]["status"] for row in result["results"]],
                             ["SMTP_ACCEPTED", "SENT_PREVIOUSLY"])
            self.assertEqual(len(result["sent"]), 1)
            self.assertEqual(len(result["send_started"]), 1)
            self.assertEqual(server.stats["connections"], 1)
            self.assertEqual(server.stats["data_transactions"], 1)

    def test_real_legacy_flush_data_disconnect_is_unknown_without_resend(self):
        with LoopbackSMTP(self.root / "server", "disconnect_after_data") as server:
            result = self.flush_child(server)
            receipt = server.wait_for_data()
            self.assertEqual([row[0]["status"] for row in result["results"]],
                             ["UNKNOWN_REQUIRES_RECONCILIATION"] * 2)
            self.assertEqual(result["sent"], [])
            self.assertEqual(len(result["send_started"]), 1)
            self.assertEqual(server.stats["connections"], 1)
            self.assertEqual(server.stats["data_transactions"], 1)
            self.assertEqual(server.stats["acknowledgements"], 0)
            self.assertEqual(receipt.mode, "disconnect_after_data")
            with self.assertRaises(TimeoutError):
                server.wait_for_ack(timeout=0.05)

    def test_occupied_fixed_port_is_blocked_without_replacing_listener(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            blocker.bind((HOST, PORT))
            blocker.listen(1)
            with self.assertRaisesRegex(FixtureBlocked, "BLOCKED_LOOPBACK_PORT_587_UNAVAILABLE"):
                with LoopbackSMTP(self.root / "must-not-start"):
                    self.fail("occupied port must never start another fixture")
            self.assertFalse((self.root / "must-not-start").exists())
            self.assertEqual(blocker.getsockname(), (HOST, PORT))

    def test_close_stops_idle_connection_and_releases_fixed_port(self):
        with LoopbackSMTP(self.root / "server") as server:
            client = smtplib.SMTP(HOST, PORT, timeout=5)
            self.addCleanup(client.close)
            self.assertTrue(server.is_running)
        self.assertFalse(server.is_running)
        self.assertTrue(all(not worker.is_alive() for worker in server._workers))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((HOST, PORT))


if __name__ == "__main__":
    unittest.main()
