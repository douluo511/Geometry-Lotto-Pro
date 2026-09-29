import pathlib
import random
import sys
import unittest

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service import EnglishRootService
from net_client import NetClient

class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None, url="https://example.invalid/data"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url

class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

class T(unittest.TestCase):
    def test_service_contract(self):
        for n in ["analyze","today_roots","stats","mark_practiced","one_click_update","one_click_repair"]:
            self.assertTrue(callable(getattr(EnglishRootService, n, None)))

    def test_net_bounds(self):
        n = NetClient(max_attempts=99)
        self.assertLessEqual(n.max_attempts, 4)
        self.assertGreater(n.connect_timeout, 0)
        self.assertGreater(n.read_timeout, 0)

    def test_retry_429_and_attempt_ledger(self):
        sleeps = []
        session = FakeSession([
            FakeResponse(429, b"{}", {"Content-Type":"application/json"}),
            FakeResponse(200, b'{"ok":true}', {"Content-Type":"application/json"}),
        ])
        n = NetClient(session=session, sleeper=sleeps.append, rng=random.Random(7), backoff_base=0.1)
        raw, rec = n.get_bytes("https://example.invalid/data", source_id="test")
        self.assertEqual(raw, b'{"ok":true}')
        self.assertEqual(rec.source_id, "test")
        self.assertEqual(len(rec.attempt_ledger), 2)
        self.assertEqual(rec.attempt_ledger[0]["outcome"], "RETRY_HTTP")
        self.assertEqual(rec.attempt_ledger[-1]["outcome"], "HTTP_RESPONSE")
        self.assertEqual(len(sleeps), 1)

    def test_separate_connect_read_timeout(self):
        session = FakeSession([FakeResponse(200, b"{}", {"Content-Type":"application/json"})])
        n = NetClient(connect_timeout=1, read_timeout=2, session=session, sleeper=lambda _: None)
        n.get_bytes("https://example.invalid/data")
        self.assertEqual(session.calls[0]["timeout"], (1.0, 2.0))

    def test_insecure_redirect_fails_closed(self):
        session = FakeSession([FakeResponse(200, b"{}", {"Content-Type":"application/json"}, url="http://example.invalid/data")])
        n = NetClient(session=session, sleeper=lambda _: None)
        with self.assertRaises(requests.RequestException) as ctx:
            n.get_bytes("https://example.invalid/data")
        ledger = getattr(ctx.exception, "glp_attempts", ())
        self.assertTrue(ledger)
        self.assertEqual(ledger[-1]["outcome"], "FINAL_INSECURE_REDIRECT")

    def test_wrong_content_type_fails_closed(self):
        session = FakeSession([FakeResponse(200, b"<html></html>", {"Content-Type":"text/html"})])
        n = NetClient(session=session, sleeper=lambda _: None)
        with self.assertRaises(ValueError):
            n.get_bytes("https://example.invalid/data")

if __name__=="__main__":
    unittest.main()
