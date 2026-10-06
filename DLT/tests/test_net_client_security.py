"""Controlled transport fault tests; these are NOT Real Network evidence."""
from __future__ import annotations

import io
import math
import random
import unittest
from email.utils import formatdate

import requests

from glp.net_client import NetClient, OperationDeadlineExceeded, ResponseTooLarge
from glp.sources import SourceError, _validate_response


URL = "https://official.example.invalid/data"


def response(status=200, body=b'{"value": 1}', *, url=URL, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers.update({"Content-Type": "application/json", **(headers or {})})
    result.raw = io.BytesIO(body)
    return result


class Transport:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.items:
            raise AssertionError("unexpected extra HTTP attempt")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class NetworkSecurityTests(unittest.TestCase):
    def test_success_stream_is_closed_but_body_remains_available(self):
        value = response()
        session = Transport(value)
        result = NetClient(session=session).get(URL, {"page": 1}, {"Accept": "application/json"}, (1, 2), True)
        self.assertEqual(result.json(), {"value": 1})
        self.assertTrue(value.raw.closed)
        self.assertEqual(result.glp_attempts[-1]["outcome"], "HTTP_RESPONSE")
        kwargs = session.calls[0][1]
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout"], (1, 2))

    def test_https_to_http_is_rejected_before_following_location(self):
        value = response(302, headers={"Location": "http://official.example.invalid/data"})
        session = Transport(value)
        with self.assertRaises(ValueError) as caught:
            NetClient(session=session).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertTrue(value.raw.closed)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "REJECTED_REDIRECT")

    def test_cross_host_credentials_and_nonstandard_ports_rejected(self):
        for location in ("https://other.invalid/path", "https://u:p@official.example.invalid/path", "https://official.example.invalid:444/path"):
            with self.subTest(location=location):
                session = Transport(response(302, headers={"Location": location}))
                with self.assertRaises(ValueError):
                    NetClient(session=session).get(URL)
                self.assertEqual(len(session.calls), 1)

    def test_same_host_redirect_preserves_evidence_and_drops_original_params(self):
        first = response(302, headers={"Location": "/next?page=2"})
        final = response(url="https://official.example.invalid/next?page=2")
        session = Transport(first, final)
        result = NetClient(session=session).get(URL, params={"page": 1})
        self.assertEqual(result.json(), {"value": 1})
        self.assertEqual(session.calls[0][1]["params"], {"page": 1})
        self.assertIsNone(session.calls[1][1]["params"])
        self.assertTrue(first.raw.closed)
        self.assertEqual([x["outcome"] for x in result.glp_attempts], ["REDIRECT_HTTPS", "HTTP_RESPONSE"])

    def test_redirect_hop_budget_is_finite(self):
        session = Transport(*[response(302, headers={"Location": "/loop"}) for _ in range(3)])
        with self.assertRaises(requests.TooManyRedirects) as caught:
            NetClient(session=session, max_redirects=2).get(URL)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "REDIRECT_LIMIT")

    def test_missing_or_control_character_location_is_rejected(self):
        for location in (None, "", "/ok\r\nInjected: true"):
            with self.subTest(location=location):
                value = response(302, headers={} if location is None else {"Location": location})
                session = Transport(value)
                with self.assertRaises(requests.HTTPError):
                    NetClient(session=session).get(URL)
                self.assertEqual(len(session.calls), 1)
                self.assertTrue(value.raw.closed)

    def test_disabled_redirects_return_nonpass_terminal_http(self):
        session = Transport(response(302, headers={"Location": "/next"}))
        result = NetClient(session=session).get(URL, allow_redirects=False)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.glp_attempts[-1]["outcome"], "FINAL_HTTP")
        with self.assertRaises(SourceError):
            _validate_response(result, result.content, expected="json")

    def test_transport_automatic_redirect_is_rejected(self):
        value = response()
        value.history = [response(302)]
        with self.assertRaises(ValueError) as caught:
            NetClient(session=Transport(value)).get(URL)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "REJECTED_HISTORY")
        self.assertTrue(value.raw.closed)

    def test_response_changed_to_http_is_rejected(self):
        value = response(url="http://official.example.invalid/data")
        with self.assertRaises(requests.RequestException) as caught:
            NetClient(session=Transport(value)).get(URL)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "FINAL_INSECURE_REDIRECT")
        self.assertTrue(value.raw.closed)

    def test_response_changed_to_other_host_is_rejected(self):
        value = response(url="https://other.invalid/data")
        with self.assertRaises(ValueError) as caught:
            NetClient(session=Transport(value)).get(URL)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "REJECTED_RESPONSE_URL")

    def test_streamed_body_limit_is_enforced_and_closed(self):
        value = response(body=b"x" * 200000)
        session = Transport(value)
        with self.assertRaises(ResponseTooLarge) as caught:
            NetClient(session=session, max_response_bytes=32).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(value.raw.closed)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "BODY_TOO_LARGE")
        self.assertIs(value._content, False)

    def test_preloaded_body_limit_is_also_enforced(self):
        value = response()
        value._content = b"12345"
        with self.assertRaises(ResponseTooLarge):
            NetClient(session=Transport(value), max_response_bytes=4).get(URL)
        self.assertTrue(value.raw.closed)

    def test_exact_body_limit_is_accepted(self):
        result = NetClient(session=Transport(response(body=b"1234")), max_response_bytes=4).get(URL)
        self.assertEqual(result.content, b"1234")

    def test_retried_response_is_closed_before_backoff(self):
        value = response(429)
        sleeps = []
        def sleeper(delay):
            self.assertTrue(value.raw.closed)
            sleeps.append(delay)
        session = Transport(value, response())
        result = NetClient(session=session, rng=random.Random(7), sleeper=sleeper).get(URL)
        self.assertEqual(len(session.calls), 2)
        self.assertGreaterEqual(sleeps[0], 0.35)
        self.assertLess(sleeps[0], 0.7)
        self.assertEqual(result.glp_attempts[0]["outcome"], "RETRY_HTTP")

    def test_all_5xx_and_408_429_have_finite_attempt_budget(self):
        for status in (408, 429, 500, 501, 502, 503, 504, 599):
            with self.subTest(status=status):
                session = Transport(*[response(status) for _ in range(3)])
                sleeps = []
                result = NetClient(session=session, sleeper=sleeps.append).get(URL)
                self.assertEqual(len(session.calls), 3)
                self.assertEqual(len(sleeps), 2)
                self.assertEqual(result.glp_attempts[-1]["outcome"], "FINAL_RETRYABLE_HTTP")
                with self.assertRaises(SourceError):
                    _validate_response(result, result.content, expected="json")

    def test_403_is_not_retried_or_mislabeled_success(self):
        session = Transport(response(403, body=b"denied"))
        result = NetClient(session=session).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(result.content, b"denied")
        self.assertEqual(result.glp_attempts[-1]["outcome"], "FINAL_HTTP")
        with self.assertRaises(SourceError):
            _validate_response(result, result.content, expected="json")

    def test_retry_after_above_budget_stops_instead_of_retrying_too_early(self):
        session = Transport(response(429, headers={"Retry-After": "60"}))
        sleeps = []
        result = NetClient(session=session, max_retry_after=5, sleeper=sleeps.append).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.glp_attempts[-1]["outcome"], "FINAL_RETRYABLE_HTTP")

    def test_retry_after_http_date_respected(self):
        session = Transport(response(503, headers={"Retry-After": formatdate(1004, usegmt=True)}), response())
        sleeps = []
        NetClient(session=session, clock=lambda: 1000.0, sleeper=sleeps.append).get(URL)
        self.assertEqual(sleeps, [4.0])

    def test_delay_exceeding_deadline_does_not_sleep_or_send_another_request(self):
        clock = Clock()
        session = Transport(response(429, headers={"Retry-After": "5"}))
        with self.assertRaises(OperationDeadlineExceeded) as caught:
            NetClient(session=session, total_timeout=2, sleeper=clock.sleep, monotonic_clock=clock).get(URL)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "OPERATION_DEADLINE")

    def test_timeouts_shrink_to_remaining_operation_budget(self):
        clock = Clock()
        session = Transport(response())
        NetClient(session=session, total_timeout=4, monotonic_clock=clock).get(URL, timeout=(10, 30))
        self.assertEqual(session.calls[0][1]["timeout"], (2.0, 2.0))

    def test_exceptions_stop_at_finite_budget_with_failure_ledger(self):
        session = Transport(requests.Timeout("one"), requests.ConnectionError("two"), requests.Timeout("three"))
        sleeps = []
        with self.assertRaises(requests.Timeout) as caught:
            NetClient(session=session, sleeper=sleeps.append).get(URL)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(caught.exception.glp_attempts[-1]["outcome"], "FINAL_EXCEPTION")

    def test_invalid_config_never_silently_clamps_or_accepts_nonfinite(self):
        values = {
            "connect_timeout": [0, -1, math.nan, math.inf, True],
            "read_timeout": [0, -1, math.nan, math.inf, True],
            "total_timeout": [0, -1, math.nan, math.inf, True],
            "backoff_base": [-1, math.nan, math.inf, True],
            "max_retry_after": [-1, math.nan, math.inf, True],
            "max_attempts": [0, 5, 1.5, True],
            "max_redirects": [-1, 6, 1.5, True],
            "max_response_bytes": [0, 64 * 1024 * 1024 + 1, 1.5, True],
        }
        for name, invalid in values.items():
            for value in invalid:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    NetClient(**{name: value})

    def test_invalid_timeout_pairs_fail_before_transport(self):
        for timeout in (0, [], [1, 2], (1,), (1, math.nan), (True, 2), (1, math.inf)):
            session = Transport()
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                NetClient(session=session).get(URL, timeout=timeout)
            self.assertEqual(session.calls, [])

    def test_empty_or_wrong_content_type_response_cannot_pass_source(self):
        for value in (response(body=b""), response(headers={"Content-Type": "text/html"})):
            result = NetClient(session=Transport(value)).get(URL)
            with self.assertRaises(SourceError):
                _validate_response(result, result.content, expected="json")

    def test_unexpected_success_status_is_not_a_complete_official_response(self):
        # 206 may contain valid JSON but only part of the requested history.
        # GET endpoints are contracted to return a complete HTTP 200 body.
        for status in (201, 202, 204, 206, 299):
            with self.subTest(status=status):
                result = NetClient(session=Transport(response(status))).get(URL)
                with self.assertRaises(SourceError):
                    _validate_response(result, result.content, expected="json")


if __name__ == "__main__":
    unittest.main()
