"""Deterministic transport contracts; these tests never claim a live-network PASS."""
from __future__ import annotations

import math
import random
import sys
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
from glp.net_client import NetClient


URL = "https://official.example.test/draws"


def response(status=200, *, url=URL, headers=None, content=b"draws", history=None):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers = requests.structures.CaseInsensitiveDict(headers or {})
    result._content = content
    result.history = history or []
    return result


class FakeSession:
    def __init__(self, *effects):
        self.effects = list(effects)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class NetClientContractTests(unittest.TestCase):
    def make_client(self, session, sleeps, **kwargs):
        options = {
            "session": session,
            "sleeper": sleeps.append,
            "jitter_source": lambda: 0.5,
            "backoff_base": 0.5,
            "max_retry_delay": 5,
        }
        options.update(kwargs)
        return NetClient(**options)

    def test_success_preserves_independent_timeout_and_does_not_retry(self):
        session = FakeSession(response())
        sleeps = []
        result = self.make_client(session, sleeps, connect_timeout=2, read_timeout=7).get(URL)
        self.assertEqual(result.content, b"draws")
        self.assertEqual(session.calls[0][1]["timeout"], (2.0, 7.0))
        self.assertIs(session.calls[0][1]["allow_redirects"], False)
        self.assertIs(session.calls[0][1]["stream"], True)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual([entry["outcome"] for entry in result.glp_attempts], ["HTTP_RESPONSE"])

    def test_call_override_requires_two_finite_timeouts(self):
        for invalid in (0, 8, (1,), (0, 3), (1, math.inf), (True, 3), (1, None)):
            with self.subTest(invalid=invalid):
                session = FakeSession(response())
                with self.assertRaises(ValueError):
                    self.make_client(session, []).get(URL, timeout=invalid)
                self.assertEqual(session.calls, [])
        session = FakeSession(response())
        self.make_client(session, []).get(URL, timeout=(3, 11))
        self.assertEqual(session.calls[0][1]["timeout"], (3.0, 11.0))

    def test_invalid_client_configuration_fails_before_request(self):
        for values in (
            {"connect_timeout": 0}, {"read_timeout": float("nan")},
            {"backoff_base": -1}, {"max_retry_delay": float("inf")},
            {"max_attempts": 0}, {"max_attempts": 5},
            {"max_attempts": True}, {"backoff_base": 6},
            {"max_redirects": -1}, {"max_redirects": 6}, {"max_redirects": True},
            {"total_timeout": 0}, {"total_timeout": float("inf")},
            {"max_response_bytes": 0}, {"max_response_bytes": True},
            {"max_response_bytes": 64 * 1024 * 1024 + 1},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.make_client(FakeSession(), [], **values)

    def test_rejects_non_https_or_credentialed_url_before_request(self):
        for url in (
            "http://official.example.test/draws", "https://", "/draws",
            "https://user:secret@official.example.test/draws",
            "https://official.example.test:8080/draws", None,
        ):
            with self.subTest(url=url):
                session = FakeSession(response())
                with self.assertRaises(ValueError):
                    self.make_client(session, []).get(url)
                self.assertEqual(session.calls, [])

    def test_transport_timeouts_use_bounded_exponential_backoff_with_jitter(self):
        session = FakeSession(requests.ConnectTimeout("connect"), requests.ReadTimeout("read"), response())
        sleeps = []
        self.make_client(session, sleeps).get(URL)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleeps, [0.75, 1.5])

    def test_408_429_and_all_5xx_retry_then_success(self):
        for status in (408, 429, 500, 501, 502, 503, 504, 599):
            with self.subTest(status=status):
                session = FakeSession(response(status), response())
                sleeps = []
                self.make_client(session, sleeps).get(URL)
                self.assertEqual(len(session.calls), 2)
                self.assertEqual(sleeps, [0.75])

    def test_retry_after_seconds_is_respected(self):
        session = FakeSession(response(429, headers={"Retry-After": "2"}), response())
        sleeps = []
        self.make_client(session, sleeps).get(URL)
        self.assertEqual(sleeps, [2.0])

    def test_retry_ledger_binds_http_and_transport_attempts(self):
        session = FakeSession(response(429), requests.ReadTimeout("read"), response())
        sleeps = []
        result = self.make_client(session, sleeps).get(URL)
        ledger = result.glp_attempts
        self.assertEqual([item["outcome"] for item in ledger],
                         ["RETRY_HTTP", "RETRY_EXCEPTION", "HTTP_RESPONSE"])
        self.assertEqual([item["attempt"] for item in ledger], [1, 2, 3])
        self.assertEqual(ledger[0]["status_code"], 429)
        self.assertEqual(ledger[1]["error_type"], "ReadTimeout")
        self.assertEqual([item["retry_delay"] for item in ledger], [0.75, 1.5, 0.0])

    def test_rng_injection_is_deterministic(self):
        def run():
            session = FakeSession(response(503), response())
            result = self.make_client(session, [], rng=random.Random(17)).get(URL)
            return result.glp_attempts[0]["retry_delay"]
        self.assertEqual(run(), run())

    def test_retry_after_http_date_is_respected(self):
        now = 1_700_000_000
        target = datetime.fromtimestamp(now + 4, timezone.utc)
        header = format_datetime(target, usegmt=True)
        session = FakeSession(response(503, headers={"Retry-After": header}), response())
        sleeps = []
        self.make_client(session, sleeps, clock=lambda: now).get(URL)
        self.assertEqual(sleeps, [4.0])

    def test_excessive_retry_after_fails_closed_without_sleeping(self):
        session = FakeSession(response(429, headers={"Retry-After": "120"}), response())
        sleeps = []
        with self.assertRaises(requests.HTTPError) as raised:
            self.make_client(session, sleeps).get(URL)
        self.assertEqual(raised.exception.response.status_code, 429)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])

    def test_exhausted_5xx_never_returns_failure_as_success(self):
        session = FakeSession(response(500), response(502), response(503))
        sleeps = []
        with self.assertRaises(requests.HTTPError) as raised:
            self.make_client(session, sleeps).get(URL)
        self.assertEqual(raised.exception.response.status_code, 503)
        self.assertEqual([entry["outcome"] for entry in raised.exception.glp_attempts],
                         ["RETRY_HTTP", "RETRY_HTTP", "FINAL_HTTP"])
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleeps, [0.75, 1.5])

    def test_exhausted_transport_failure_raises(self):
        session = FakeSession(*(requests.ReadTimeout("offline") for _ in range(3)))
        sleeps = []
        with self.assertRaises(requests.ReadTimeout) as raised:
            self.make_client(session, sleeps).get(URL)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleeps, [0.75, 1.5])
        self.assertEqual([entry["outcome"] for entry in raised.exception.glp_attempts],
                         ["RETRY_EXCEPTION", "RETRY_EXCEPTION", "FINAL_EXCEPTION"])

    def test_body_transfer_failure_retries_inside_transport_boundary(self):
        session = FakeSession(requests.exceptions.ChunkedEncodingError("truncated"), response())
        sleeps = []
        result = self.make_client(session, sleeps).get(URL)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [0.75])

    def test_oversized_response_is_rejected_before_source_parsing(self):
        session = FakeSession(response(content=b"12345"))
        with self.assertRaises(requests.RequestException) as raised:
            self.make_client(session, [], max_response_bytes=4).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(raised.exception.glp_attempts[-1]["outcome"], "BODY_TOO_LARGE")

    def test_retry_delay_cannot_exceed_total_operation_budget(self):
        now = [1000.0]
        sleeps = []

        def clock():
            return now[0]

        def sleeper(delay):
            sleeps.append(delay)
            now[0] += delay

        session = FakeSession(response(503), response())
        client = self.make_client(
            session,
            sleeps,
            clock=clock,
            total_timeout=0.6,
            sleeper=sleeper,
        )
        with self.assertRaises(requests.Timeout) as raised:
            client.get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(raised.exception.glp_attempts[-1]["outcome"], "OPERATION_DEADLINE")

    def test_one_attempt_never_retries_or_sleeps(self):
        session = FakeSession(response(429))
        sleeps = []
        with self.assertRaises(requests.HTTPError):
            self.make_client(session, sleeps, max_attempts=1).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])

    def test_nonretryable_http_status_fails_without_retry(self):
        for status in (204, 301, 400, 403, 404):
            with self.subTest(status=status):
                session = FakeSession(response(status), response())
                with self.assertRaises(requests.HTTPError):
                    self.make_client(session, []).get(URL)
                self.assertEqual(len(session.calls), 1)

    def test_https_redirect_is_checked_before_next_request(self):
        next_url = "https://official.example.test/latest"
        session = FakeSession(response(302, headers={"Location": "/latest"}), response(url=next_url))
        sleeps = []
        result = self.make_client(session, sleeps).get(URL, params={"name": "ssq"})
        self.assertEqual([call[0] for call in session.calls], [URL, next_url])
        self.assertEqual(session.calls[0][1]["params"], {"name": "ssq"})
        self.assertIsNone(session.calls[1][1]["params"])
        self.assertTrue(all(call[1]["allow_redirects"] is False for call in session.calls))
        self.assertEqual(sleeps, [])
        self.assertEqual([entry["outcome"] for entry in result.glp_attempts],
                         ["REDIRECT_HTTPS", "HTTP_RESPONSE"])

    def test_http_or_cross_host_redirect_is_rejected_before_the_hop(self):
        for location in (
            "http://official.example.test/latest",
            "https://untrusted.example.test/latest",
            "//untrusted.example.test/latest",
            "https://official.example.test:8080/latest",
        ):
            with self.subTest(location=location):
                session = FakeSession(response(302, headers={"Location": location}), response())
                with self.assertRaises(ValueError) as raised:
                    self.make_client(session, []).get(URL)
                self.assertEqual(len(session.calls), 1)
                self.assertIs(session.calls[0][1]["allow_redirects"], False)
                self.assertEqual(raised.exception.glp_attempts[-1]["outcome"], "REJECTED_REDIRECT")

    def test_redirect_chain_is_bounded(self):
        session = FakeSession(
            response(301, headers={"Location": "/one"}),
            response(302, url="https://official.example.test/one", headers={"Location": "/two"}),
        )
        with self.assertRaises(requests.TooManyRedirects):
            self.make_client(session, [], max_redirects=1).get(URL)
        self.assertEqual(len(session.calls), 2)

    def test_redirect_disabled_never_follows_even_safe_location(self):
        session = FakeSession(response(302, headers={"Location": "/latest"}), response())
        with self.assertRaises(requests.HTTPError):
            self.make_client(session, []).get(URL, allow_redirects=False)
        self.assertEqual(len(session.calls), 1)

    def test_transport_supplied_history_is_rejected(self):
        hop = response(301, url="http://untrusted.example.test/draws")
        session = FakeSession(response(history=[hop]))
        with self.assertRaises(ValueError):
            self.make_client(session, []).get(URL)
        self.assertEqual(len(session.calls), 1)

    def test_nonconforming_transport_insecure_final_url_has_provenance(self):
        observed = "http://official.example.test/draws"
        session = FakeSession(response(url=observed))
        with self.assertRaises(requests.RequestException) as raised:
            self.make_client(session, []).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertIs(session.calls[0][1]["allow_redirects"], False)
        self.assertEqual(raised.exception.glp_attempts[-1]["outcome"], "FINAL_INSECURE_REDIRECT")
        self.assertEqual(raised.exception.glp_attempts[-1]["url"], observed)

    def test_malformed_jitter_cannot_turn_failure_into_success(self):
        session = FakeSession(response(503), response())
        client = NetClient(session=session, sleeper=lambda _: None, jitter_source=lambda: float("nan"))
        with self.assertRaises(ValueError):
            client.get(URL)
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
