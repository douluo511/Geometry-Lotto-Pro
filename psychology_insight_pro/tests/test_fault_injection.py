import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from net_client import NetClient, NetError
from storage import KnowledgeStorage


class FakeResponse:
    def __init__(self, raw: bytes, status=200, content_type="application/json"):
        self._raw = raw
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self, n=-1):
        return self._raw if n < 0 else self._raw[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FaultInjectionTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "version": "9.9.9",
            "hypotheses": [{
                "key": "x",
                "name": "X",
                "explanation": "x",
                "support_keywords": ["a"],
                "contradict_keywords": ["b"]
            }]
        }

    def test_rejects_non_https(self):
        with self.assertRaises(NetError):
            NetClient().get_json("http://example.com/a.json")

    def test_rejects_invalid_schema(self):
        raw = json.dumps({"version": "1.0.0"}).encode()
        with self.assertRaises(ValueError):
            NetClient(retries=0).get_json(
                "https://example.com/a.json",
                opener=lambda *a, **k: FakeResponse(raw)
            )

    def test_rejects_oversize_body(self):
        raw = b"x" * 101
        with self.assertRaises(NetError):
            NetClient(retries=0, max_bytes=100).get_json(
                "https://example.com/a.json",
                opener=lambda *a, **k: FakeResponse(raw, content_type="application/json")
            )

    def test_transient_500_retries_then_succeeds(self):
        calls = {"n": 0}
        raw = json.dumps(self.valid).encode()
        def opener(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
            return FakeResponse(raw)
        payload, source = NetClient(retries=1).get_json(
            "https://example.com/a.json", opener=opener, sleeper=lambda _: None
        )
        self.assertEqual(payload["version"], "9.9.9")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(source.http_status, 200)
        self.assertEqual(len(source.sha256), 64)

    def test_corrupt_local_storage_repairs_from_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            local = root / "local.json"
            bundle.write_text(json.dumps(self.valid), encoding="utf-8")
            local.write_text("{broken", encoding="utf-8")
            storage = KnowledgeStorage(local, bundle)
            data = storage.load_knowledge()
            self.assertEqual(data["version"], "9.9.9")


if __name__ == "__main__":
    unittest.main()
