"""Controlled transport failures, not official-network or release evidence."""
import io
import sys
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
from glp.net_client import NetClient, OperationDeadlineExceeded, ResponseTooLarge

URL = "https://official.example.test/draws"


class Session:
    def __init__(self, callback):
        self.callback = callback
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.callback()


def streamed(body=b"draws", *, url=URL, status=200, headers=None):
    response = requests.Response()
    response.raw = io.BytesIO(body)
    response.status_code = status
    response.url = url
    response.headers.update(headers or {})
    return response


class ResourceContractTests(unittest.TestCase):
    def test_wall_clock_rollback_does_not_extend_deadline(self):
        wall = [1000.0]
        elapsed = [0.0]
        response = streamed()

        def transfer():
            wall[0] = 0.0
            elapsed[0] = 2.0
            return response

        client = NetClient(session=Session(transfer), total_timeout=1,
                           clock=lambda: wall[0], monotonic_clock=lambda: elapsed[0])
        with self.assertRaises(OperationDeadlineExceeded) as error:
            client.get(URL)
        self.assertTrue(response.raw.closed)
        self.assertEqual(error.exception.glp_attempts[-1]["outcome"], "OPERATION_DEADLINE")

    def test_timeout_backoff_exhaustion_keeps_attempt_ledger(self):
        def failure():
            raise requests.ReadTimeout("controlled read failure")

        session = Session(failure)
        client = NetClient(session=session, total_timeout=0.1,
                           monotonic_clock=lambda: 0.0, jitter_source=lambda: 0.5)
        with self.assertRaises(OperationDeadlineExceeded) as error:
            client.get(URL)
        self.assertEqual(session.calls, 1)
        self.assertEqual([r["outcome"] for r in error.exception.glp_attempts],
                         ["RETRY_EXCEPTION", "OPERATION_DEADLINE"])

    def test_retry_configuration_failure_keeps_evidence(self):
        def failure():
            raise requests.ReadTimeout("controlled failure")

        client = NetClient(session=Session(failure), jitter_source=lambda: float("nan"))
        with self.assertRaises(ValueError) as error:
            client.get(URL)
        self.assertEqual(error.exception.glp_attempts[-1]["outcome"], "FINAL_EXCEPTION")

    def test_real_response_stream_size_limit_closes_stream(self):
        response = streamed(b"12345")
        client = NetClient(session=Session(lambda: response), max_response_bytes=4)
        with self.assertRaises(ResponseTooLarge) as error:
            client.get(URL)
        self.assertEqual(error.exception.glp_attempts[-1]["outcome"], "BODY_TOO_LARGE")
        self.assertTrue(response.raw.closed)

    def test_success_caches_bytes_before_closing_stream(self):
        response = streamed(b"1234")
        result = NetClient(session=Session(lambda: response), max_response_bytes=4).get(URL)
        self.assertEqual(result.content, b"1234")
        self.assertTrue(response.raw.closed)

    def test_rejected_redirect_and_response_identity_close_stream(self):
        for response in (
            streamed(status=302, headers={"Location": "http://official.example.test/x"}),
            streamed(status=302, headers={"Location": "https://other.example.test/x"}),
            streamed(status=302),
            streamed(url="https://other.example.test/x"),
            streamed(url="http://official.example.test/x"),
        ):
            with self.subTest(url=response.url, headers=response.headers):
                with self.assertRaises((ValueError, requests.RequestException)):
                    NetClient(session=Session(lambda: response)).get(URL)
                self.assertTrue(response.raw.closed)

    def test_failed_stream_is_closed_before_retry(self):
        response = streamed()

        def broken_chunks(chunk_size):
            yield b"partial"
            raise requests.exceptions.ChunkedEncodingError("controlled truncation")

        response.iter_content = broken_chunks
        responses = [response, streamed(b"ok")]

        def transfer():
            if len(responses) == 1:
                self.assertTrue(response.raw.closed)
            return responses.pop(0)

        result = NetClient(session=Session(transfer), sleeper=lambda _: None).get(URL)
        self.assertEqual(result.content, b"ok")
        self.assertEqual([r["outcome"] for r in result.glp_attempts],
                         ["RETRY_EXCEPTION", "HTTP_RESPONSE"])


if __name__ == "__main__":
    unittest.main()
