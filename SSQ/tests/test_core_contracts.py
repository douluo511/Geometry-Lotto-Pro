from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "SSQ"))

from glp.net_client import NetClient
from glp.sources import SourceError, _balls, _draw, _issue, _validate_http_payload


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class DomainContractTests(unittest.TestCase):
    def test_issue_normalizes_five_digits(self):
        self.assertEqual(_issue("26100"), "2026100")

    def test_issue_rejects_invalid(self):
        with self.assertRaises(SourceError):
            _issue("abc")

    def test_compact_red_balls(self):
        self.assertEqual(_balls("010203040506", 6), [1, 2, 3, 4, 5, 6])

    def test_draw_rejects_duplicate_reds(self):
        with self.assertRaises(SourceError):
            _draw("2026100", "2026-09-01", [1, 1, 2, 3, 4, 5], [6])


class NetClientUnitTests(unittest.TestCase):
    def test_retry_cap_and_ledger(self):
        sleeps = []
        session = FakeSession([
            requests.Timeout("a"),
            requests.ConnectionError("b"),
            FakeResponse(200),
        ])
        response = NetClient(
            connect_timeout=1,
            read_timeout=2,
            max_attempts=3,
            backoff_base=0.1,
            session=session,
            sleeper=sleeps.append,
            rng=random.Random(1),
        ).get("https://example.invalid")
        ledger = list(response.glp_attempts)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(ledger[-1]["outcome"], "HTTP_RESPONSE")
        self.assertTrue(all(call[1]["timeout"] == (1.0, 2.0) for call in session.calls))

    def test_wrong_content_type_fails_closed(self):
        response = FakeResponse(200, b"<html></html>", {"Content-Type": "text/html"})
        with self.assertRaises(SourceError):
            _validate_http_payload(response, response.content, expected="json")

    def test_empty_payload_fails_closed(self):
        response = FakeResponse(200, b"", {"Content-Type": "application/json"})
        with self.assertRaises(SourceError):
            _validate_http_payload(response, response.content, expected="json")


if __name__ == "__main__":
    unittest.main()
