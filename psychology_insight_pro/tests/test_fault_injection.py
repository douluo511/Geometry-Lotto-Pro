import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from domain import SourceRecord
from net_client import NetClient, NetError
from service import PsychologyService
from storage import KnowledgeStorage


class FakeResponse:
    def __init__(self, raw: bytes, status=200, content_type="application/json", headers=None):
        self._raw = raw
        self.status_code = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._raw), max(1, chunk_size)):
            yield self._raw[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected extra request")
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class StubNetClient:
    def __init__(self, values):
        self.values = values

    def get_json(self, url, validator=None, *, source_id=""):
        payload = self.values[url]
        if validator:
            validator(payload)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        return payload, SourceRecord(
            url=url,
            fetched_at="2026-09-29T00:00:00+00:00",
            http_status=200,
            sha256="a" * 64,
            bytes_count=len(raw),
            content_type="application/json",
            source_id=source_id,
            attempts=({"attempt": 1, "outcome": "HTTP_RESPONSE"},),
            raw_b64="e30=",
        )


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
        session = FakeSession([FakeResponse(raw)])
        with self.assertRaises(ValueError):
            NetClient(retries=0, session=session).get_json("https://example.com/a.json")

    def test_rejects_oversize_body(self):
        raw = b"x" * 101
        session = FakeSession([FakeResponse(raw)])
        with self.assertRaises(NetError):
            NetClient(retries=0, max_bytes=100, session=session).get_json(
                "https://example.com/a.json"
            )

    def test_rejects_wrong_content_type(self):
        raw = json.dumps(self.valid).encode()
        session = FakeSession([FakeResponse(raw, content_type="text/html")])
        with self.assertRaises(NetError):
            NetClient(retries=0, session=session).get_json("https://example.com/a.json")

    def test_transient_500_retries_then_succeeds_with_attempt_ledger(self):
        raw = json.dumps(self.valid).encode()
        sleeps = []
        session = FakeSession([
            FakeResponse(b"{}", status=500),
            FakeResponse(raw),
        ])
        payload, source = NetClient(
            retries=1,
            session=session,
            sleeper=sleeps.append,
            rng=random.Random(7),
            connect_timeout=1,
            read_timeout=2,
        ).get_json("https://example.com/a.json", source_id="example")
        self.assertEqual(payload["version"], "9.9.9")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][1]["timeout"], (1.0, 2.0))
        self.assertEqual(source.http_status, 200)
        self.assertEqual(len(source.attempts), 2)
        self.assertEqual(source.attempts[0]["outcome"], "RETRY_HTTP")
        self.assertEqual(source.attempts[-1]["outcome"], "HTTP_RESPONSE")
        self.assertTrue(source.raw_b64)
        self.assertEqual(len(sleeps), 1)

    def test_timeout_retry_cap_fails_closed(self):
        session = FakeSession([
            requests.Timeout("a"),
            requests.ConnectionError("b"),
        ])
        with self.assertRaises(NetError) as ctx:
            NetClient(retries=1, session=session, sleeper=lambda _: None).get_json(
                "https://example.com/a.json"
            )
        self.assertEqual(len(ctx.exception.attempts), 2)
        self.assertEqual(ctx.exception.attempts[-1]["outcome"], "FINAL_EXCEPTION")

    def test_multi_source_conflict_fails_closed(self):
        other = json.loads(json.dumps(self.valid))
        other["version"] = "9.9.8"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            bundle.write_text(json.dumps(self.valid), encoding="utf-8")
            storage = KnowledgeStorage(root / "local.json", bundle)
            service = PsychologyService(
                storage,
                StubNetClient({"https://a.example/k": self.valid, "https://b.example/k": other}),
                ["https://a.example/k", "https://b.example/k"],
            )
            with self.assertRaises(NetError):
                service.update_knowledge()

    def test_single_source_cannot_pass_network_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            bundle.write_text(json.dumps(self.valid), encoding="utf-8")
            service = PsychologyService(
                KnowledgeStorage(root / "local.json", bundle),
                StubNetClient({"https://a.example/k": self.valid}),
                "https://a.example/k",
            )
            with self.assertRaises(NetError):
                service.update_knowledge()

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

    def test_evidence_stage_failure_leaves_knowledge_unchanged(self):
        newer = json.loads(json.dumps(self.valid))
        newer["version"] = "10.0.0"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            local = root / "local.json"
            bundle.write_text(json.dumps(self.valid), encoding="utf-8")
            storage = KnowledgeStorage(local, bundle)
            storage.ensure()
            before = local.read_bytes()
            original = storage._stage

            def injected(path, payload):
                if Path(path) == storage.evidence_path:
                    raise OSError("injected evidence stage failure")
                return original(path, payload)

            storage._stage = injected
            with self.assertRaises(OSError):
                storage.replace_knowledge(newer)
            self.assertEqual(local.read_bytes(), before)

    def test_knowledge_commit_failure_rolls_back_evidence_and_knowledge(self):
        newer = json.loads(json.dumps(self.valid))
        newer["version"] = "10.0.0"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle.json"
            local = root / "local.json"
            bundle.write_text(json.dumps(self.valid), encoding="utf-8")
            storage = KnowledgeStorage(local, bundle)
            storage.ensure()
            before = local.read_bytes()
            before_evidence = storage.evidence_path.read_bytes() if storage.evidence_path.exists() else None
            original = storage._commit_replace

            def injected(staged, target):
                if Path(target) == storage.local_path:
                    raise OSError("injected knowledge commit failure")
                return original(staged, target)

            storage._commit_replace = injected
            with self.assertRaises(OSError):
                storage.replace_knowledge(newer)
            self.assertEqual(local.read_bytes(), before)
            current_evidence = storage.evidence_path.read_bytes() if storage.evidence_path.exists() else None
            self.assertEqual(current_evidence, before_evidence)


if __name__ == "__main__":
    unittest.main()
