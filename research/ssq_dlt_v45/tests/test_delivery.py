"""SQLite/outbox concurrency and fault tests; all SMTP transport is mocked.

No live credential, network connection or real recipient is used here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import smtplib
import tempfile
import threading
import unittest
from unittest import mock

from research.ssq_dlt_v45 import delivery
from research.ssq_dlt_v45.runtime import latest_due
from research.ssq_dlt_v45.store import Store


class DueSlotBoundaryTests(unittest.TestCase):
    def test_exact_jst_boundaries_and_cross_midnight(self):
        cases = (
            ("2026-10-19T06:59:59+00:00", "2026-10-17T16:00:00+09:00"),
            ("2026-10-19T07:00:00+00:00", "2026-10-19T16:00:00+09:00"),
            ("2026-10-21T06:59:59+00:00", "2026-10-19T16:00:00+09:00"),
            ("2026-10-21T07:00:00+00:00", "2026-10-21T16:00:00+09:00"),
            ("2026-10-24T06:59:59+00:00", "2026-10-21T16:00:00+09:00"),
            ("2026-10-24T07:00:00+00:00", "2026-10-24T16:00:00+09:00"),
            ("2026-10-18T15:01:00+00:00", "2026-10-17T16:00:00+09:00"),
            ("2026-10-19T03:00:00-04:00", "2026-10-19T16:00:00+09:00"),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(latest_due(datetime.fromisoformat(now)), expected)

    def test_aware_clock_required_and_never_future_over_two_weeks(self):
        with self.assertRaises(ValueError):
            latest_due(datetime(2026, 10, 19, 7))
        start = datetime(2026, 10, 15, tzinfo=timezone.utc)
        for step in range(14 * 48):
            now = start + timedelta(minutes=30 * step)
            due = datetime.fromisoformat(latest_due(now))
            self.assertLessEqual(due, now)
            self.assertIn(due.weekday(), (0, 2, 5))
            self.assertEqual((due.hour, due.minute, due.utcoffset()), (16, 0, timedelta(hours=9)))
            self.assertLess(now - due, timedelta(days=4))


class MockTransport:
    def __init__(self, factory):
        self.factory = factory

    def ehlo(self):
        self.factory.actions.append("ehlo")

    def starttls(self, *, context):
        self.factory.actions.append("starttls")
        assert context is not None

    def login(self, username, credential):
        self.factory.actions.append("login")
        if self.factory.mode == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"mock auth failure")
        if self.factory.barrier:
            self.factory.barrier.wait(timeout=10)

    def send_message(self, message):
        with self.factory.lock:
            self.factory.messages.append(message)
        if self.factory.mode == "ambiguous":
            # Simulates a connection loss after the server may have accepted DATA.
            raise smtplib.SMTPServerDisconnected("mock ambiguous acceptance")
        return {}

    def close(self):
        self.factory.actions.append("close")


class MockFactory:
    def __init__(self, mode="success", barrier=None):
        self.mode = mode
        self.barrier = barrier
        self.messages = []
        self.actions = []
        self.lock = threading.Lock()

    def __call__(self, host, port, *, timeout):
        if (host, port, timeout) != ("smtp.example.test", 587, 10):
            raise AssertionError("Unexpected SMTP endpoint")
        if self.mode == "connect":
            raise ConnectionError("mock offline")
        return MockTransport(self)


class DeliveryFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glp-v45-mock-mail-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory / "ledger.sqlite3")
        self.report = {"scope": "SYNTHETIC_TEST_ONLY", "formal_A": 0, "decision": "NO_EDGE"}
        self.smtp = {"host": "smtp.example.test", "port": 587, "sender": "sender@example.test", "password_env": "V45_TEST_FAKE_PASSWORD"}
        self.environment = mock.patch.dict("os.environ", {"V45_TEST_FAKE_PASSWORD": "synthetic-not-a-real-password"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def prepare(self):
        return delivery.prepare(self.store, self.directory / "outbox", "test@example.test", self.report, "<p>SYNTHETIC TEST ONLY</p>")

    def test_prepare_is_idempotent_and_header_injection_rejected(self):
        self.assertEqual(self.prepare(), self.prepare())
        self.assertEqual(len(self.store.rows("outbox")), 1)
        self.assertEqual(len(list((self.directory / "outbox").glob("*.eml"))), 1)
        for recipient in ("a@example.test\r\nBcc: victim@example.test", "a@example.test,b@example.test", "invalid"):
            with self.assertRaises(ValueError):
                delivery.prepare(self.store, self.directory / "outbox", recipient, self.report, "body")

    def test_missing_configuration_and_credential_never_contacts_smtp(self):
        self.prepare()
        with mock.patch.object(delivery.smtplib, "SMTP") as transport:
            self.assertEqual(delivery.flush(self.store, None)[0]["status"], "BLOCKED_NO_SMTP_CONFIGURATION")
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "BLOCKED_NO_SMTP_CREDENTIAL")
            transport.assert_not_called()
        self.assertEqual(self.store.rows("send_started"), [])

    def test_success_sent_once_and_credentials_do_not_enter_ledger(self):
        identity = self.prepare()
        transport = MockFactory()
        with mock.patch.object(delivery.smtplib, "SMTP", side_effect=transport):
            self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "SMTP_ACCEPTED")
            self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "SENT_PREVIOUSLY")
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual(transport.actions[:4], ["ehlo", "starttls", "ehlo", "login"])
        self.assertEqual(transport.messages[0]["Message-ID"], f"<{identity}@glp.local>")
        self.assertEqual(transport.messages[0]["To"], "test@example.test")
        self.assertNotIn("synthetic-not-a-real-password", repr(self.store.rows("outbox") + self.store.rows("sent") + self.store.rows("send_started")))

    def test_pre_data_connect_and_auth_failures_can_retry(self):
        self.prepare()
        for mode in ("connect", "auth"):
            transport = MockFactory(mode)
            with mock.patch.object(delivery.smtplib, "SMTP", side_effect=transport):
                self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "RETRY")
            self.assertEqual(self.store.rows("send_started"), [])
        transport = MockFactory()
        with mock.patch.object(delivery.smtplib, "SMTP", side_effect=transport):
            self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "SMTP_ACCEPTED")
        self.assertEqual(len(transport.messages), 1)

    def test_ambiguous_data_acceptance_never_automatically_resends(self):
        self.prepare()
        transport = MockFactory("ambiguous")
        with mock.patch.object(delivery.smtplib, "SMTP", side_effect=transport):
            for _ in range(2):
                self.assertEqual(delivery.flush(self.store, self.smtp)[0]["status"], "UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual(self.store.rows("sent"), [])
        self.assertEqual(len(self.store.rows("send_started")), 1)

    def test_concurrent_flush_claim_allows_one_data_send(self):
        self.prepare()
        transport = MockFactory(barrier=threading.Barrier(8))
        with mock.patch.object(delivery.smtplib, "SMTP", side_effect=transport):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: delivery.flush(self.store, self.smtp), range(8)))
        statuses = [item[0]["status"] for item in results]
        self.assertEqual(statuses.count("SMTP_ACCEPTED"), 1)
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual(len(self.store.rows("sent")), 1)

    def test_concurrent_prepare_has_no_partial_or_failed_duplicate(self):
        barrier = threading.Barrier(2)
        original_open = Path.open
        original_link = os.link

        def racing_open(path, mode="r", *args, **kwargs):
            if path.suffix == ".eml" and mode in ("xb", "x"):
                barrier.wait(timeout=10)
            return original_open(path, mode, *args, **kwargs)

        def racing_link(source, destination, *args, **kwargs):
            if Path(destination).suffix == ".eml":
                barrier.wait(timeout=10)
            return original_link(source, destination, *args, **kwargs)

        with mock.patch.object(Path, "open", racing_open), mock.patch.object(delivery.os, "link", racing_link):
            with ThreadPoolExecutor(max_workers=2) as pool:
                identities = list(pool.map(lambda _: self.prepare(), range(2)))
        self.assertEqual(identities[0], identities[1])
        self.assertEqual(len(self.store.rows("outbox")), 1)

    def test_existing_eml_tampering_is_detected(self):
        identity = self.prepare()
        path = self.directory / "outbox" / (identity + ".eml")
        path.write_bytes(b"deliberately corrupt existing EML")
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
