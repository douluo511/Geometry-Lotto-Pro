from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from glp.domain import CanonicalDataset, Draw, SourceReceipt
from glp.net_client import NetClient
from glp.sources import SourceError, _validate_freshness, _validate_http_payload
from glp.storage import Store
from glp.util import sha256_json, utc_now


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


def make_dataset(extra=False):
    draws = [Draw("26001", "2026-01-03", (1, 2, 3, 4, 5), (1, 2))]
    if extra:
        draws.append(Draw("26002", "2026-01-05", (2, 3, 4, 5, 6), (2, 3)))
    digest = sha256_json([d.to_dict() for d in draws])
    receipt = SourceReceipt("fixture", utc_now(), 200, "0" * 64, len(draws), draws[-1].issue, "PASS", "test")
    ds = CanonicalDataset(draws, digest, [receipt], 1, "PASS")
    evidence = {
        "canonical_hash": digest,
        "draw_count": len(draws),
        "latest": draws[-1].to_dict(),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "network_gate": "PASS",
    }
    return ds, evidence


class NetClientTests(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(ValueError):
            NetClient().get("http://example.invalid")

    def test_retry_429_with_attempt_ledger_and_separate_timeouts(self):
        sleeps = []
        session = FakeSession([FakeResponse(429), FakeResponse(200)])
        response = NetClient(
            connect_timeout=1,
            read_timeout=2,
            max_attempts=2,
            backoff_base=0.1,
            session=session,
            sleeper=sleeps.append,
            rng=random.Random(7),
        ).get("https://example.invalid/data")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.glp_attempts), 2)
        self.assertEqual(response.glp_attempts[0]["outcome"], "RETRY_HTTP")
        self.assertTrue(all(call[1]["timeout"] == (1.0, 2.0) for call in session.calls))
        self.assertEqual(len(sleeps), 1)

    def test_retry_cap_exception_fail_closed(self):
        sleeps = []
        session = FakeSession([requests.Timeout("a"), requests.ConnectionError("b")])
        client = NetClient(
            max_attempts=2,
            session=session,
            sleeper=sleeps.append,
            rng=random.Random(1),
        )
        with self.assertRaises(requests.ConnectionError) as ctx:
            client.get("https://example.invalid/data")
        self.assertEqual(len(ctx.exception.glp_attempts), 2)
        self.assertEqual(ctx.exception.glp_attempts[-1]["outcome"], "FINAL_EXCEPTION")

    def test_wrong_content_type_fails_closed(self):
        response = FakeResponse(200, b"<html/>", {"Content-Type": "text/html"})
        with self.assertRaises(SourceError):
            _validate_http_payload(response, response.content, allowed_types=("json",))

    def test_empty_payload_fails_closed(self):
        response = FakeResponse(200, b"", {"Content-Type": "application/json"})
        with self.assertRaises(SourceError):
            _validate_http_payload(response, response.content, allowed_types=("json",))

    def test_stale_draw_fails_closed(self):
        stale = Draw("20001", "2020-01-01", (1, 2, 3, 4, 5), (1, 2))
        with self.assertRaises(SourceError):
            _validate_freshness([stale], "fixture")


class StorageAtomicityTests(unittest.TestCase):
    def test_store_constructs_and_rebuild_method_is_callable(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            self.assertTrue(callable(store.rebuild_ledger))

    def test_evidence_stage_failure_does_not_mutate_history(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            ds1, ev1 = make_dataset(False)
            ds2, ev2 = make_dataset(True)
            store.save_dataset(ds1, ev1)
            old_history = store.history_path.read_bytes()
            old_evidence = store.evidence_path.read_bytes()
            original = store._stage_bytes

            def injected(path, data):
                if Path(path) == store.evidence_path:
                    raise OSError("injected evidence stage failure")
                return original(path, data)

            store._stage_bytes = injected
            with self.assertRaises(OSError):
                store.save_dataset(ds2, ev2)
            self.assertEqual(store.history_path.read_bytes(), old_history)
            self.assertEqual(store.evidence_path.read_bytes(), old_evidence)

    def test_history_commit_failure_rolls_back_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            ds1, ev1 = make_dataset(False)
            ds2, ev2 = make_dataset(True)
            store.save_dataset(ds1, ev1)
            old_history = store.history_path.read_bytes()
            old_evidence = store.evidence_path.read_bytes()
            original = store._commit_replace

            def injected(staged, target):
                if Path(target) == store.history_path:
                    raise OSError("injected history commit failure")
                return original(staged, target)

            store._commit_replace = injected
            with self.assertRaises(OSError):
                store.save_dataset(ds2, ev2)
            self.assertEqual(store.history_path.read_bytes(), old_history)
            self.assertEqual(store.evidence_path.read_bytes(), old_evidence)


if __name__ == "__main__":
    unittest.main()
