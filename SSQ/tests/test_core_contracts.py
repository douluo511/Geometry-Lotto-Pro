from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "SSQ"))

import glp.sources as sources
from glp.domain import CanonicalDataset, Draw, SourceReceipt
from glp.net_client import NetClient
from glp.sources import (
    SourceError,
    _balls,
    _draw,
    _issue,
    _validate_freshness,
    _validate_http_payload,
    build_canonical,
    parse_shanghai_history,
)
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


def receipt(name: str, draw: Draw) -> SourceReceipt:
    return SourceReceipt(
        source=name,
        fetched_at=utc_now(),
        http_status=200,
        raw_sha256="0" * 64,
        draw_count=1,
        latest_issue=draw.issue,
        status="PASS",
        detail="unit fixture",
    )


def dataset_pair(extra: bool = False):
    draws = [
        Draw("2026001", "2026-01-01", (1, 2, 3, 4, 5, 6), (1,)),
    ]
    if extra:
        draws.append(Draw("2026002", "2026-01-04", (2, 3, 4, 5, 6, 7), (2,)))
    digest = sha256_json([d.to_dict() for d in draws])
    ds = CanonicalDataset(draws, digest, [receipt("fixture", draws[-1])], 1, "PASS")
    ev = {
        "schema": "unit-evidence",
        "game": "SSQ",
        "canonical_hash": digest,
        "draw_count": len(draws),
        "latest": draws[-1].to_dict(),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
    }
    return ds, ev


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

    def test_draw_rejects_out_of_range(self):
        with self.assertRaises(SourceError):
            _draw("2026100", "2026-09-01", [1, 2, 3, 4, 5, 34], [6])

    def test_stale_payload_fails_closed(self):
        stale = Draw("2020001", "2020-01-01", (1, 2, 3, 4, 5, 6), (1,))
        with self.assertRaises(SourceError):
            _validate_freshness([stale], "stale-fixture")

    def test_invalid_html_fails_closed(self):
        with self.assertRaises(SourceError):
            parse_shanghai_history(b"<html><body>truncated</body></html>")


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

    def test_invalid_json_fails_closed(self):
        response = FakeResponse(200, b"{", {"Content-Type": "application/json"})
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)

    def test_invalid_encoding_fails_closed(self):
        response = FakeResponse(200, b"\xff\xfe\x00", {"Content-Type": "application/json"})
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)

    def test_schema_drift_fails_closed(self):
        response = FakeResponse(
            200,
            b'{"state":0,"result":{"unexpected":true},"pageNum":1}',
            {"Content-Type": "application/json"},
        )
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)


class SourceFailoverTests(unittest.TestCase):
    def test_primary_failure_secondary_consensus_can_recover_trusted_baseline(self):
        draws = [
            Draw("2026099", "2026-09-01", (1, 2, 3, 4, 5, 6), (1,)),
            Draw("2026100", "2026-09-04", (2, 3, 4, 5, 6, 7), (2,)),
        ]
        latest = draws[-1]
        sh_receipt = receipt("official_shanghai_L1", latest)
        hb_receipt = receipt("official_hebei_L2", latest)
        sh_raw = {"raw": b"<html>fixture</html>", "meta": {"status": 200}}
        hb_raw = {
            "home": {"raw": b"home", "meta": {"status": 200}},
            "announce": {"raw": b"announce", "meta": {"status": 200}},
        }
        with (
            patch.object(sources, "fetch_national_history", side_effect=SourceError("primary unavailable")),
            patch.object(sources, "fetch_shanghai_history", return_value=(draws, sh_receipt, sh_raw)),
            patch.object(sources, "fetch_hebei_latest", return_value=(latest, hb_receipt, hb_raw)),
        ):
            ds, evidence = build_canonical(baseline_draws=draws)
        self.assertEqual(ds.crosscheck_status, "PASS")
        self.assertEqual(evidence["verification"], "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS")
        self.assertEqual(ds.canonical_hash, sha256_json([d.to_dict() for d in draws]))

    def test_all_sources_unavailable_fails_closed(self):
        with (
            patch.object(sources, "fetch_national_history", side_effect=SourceError("n")),
            patch.object(sources, "fetch_shanghai_history", side_effect=SourceError("s")),
            patch.object(sources, "fetch_hebei_latest", side_effect=SourceError("h")),
        ):
            with self.assertRaises(SourceError):
                build_canonical(baseline_draws=[])


class StorageAtomicityTests(unittest.TestCase):
    def test_evidence_stage_failure_does_not_mutate_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            ds1, ev1 = dataset_pair(False)
            ds2, ev2 = dataset_pair(True)
            store.save_dataset(ds1, ev1)
            old_history = store.history_path.read_bytes()
            old_evidence = store.evidence_path.read_bytes()
            original_stage = store._stage_bytes

            def fail_evidence(path, data):
                if Path(path) == store.evidence_path:
                    raise OSError("injected evidence stage failure")
                return original_stage(path, data)

            store._stage_bytes = fail_evidence
            with self.assertRaises(OSError):
                store.save_dataset(ds2, ev2)
            self.assertEqual(store.history_path.read_bytes(), old_history)
            self.assertEqual(store.evidence_path.read_bytes(), old_evidence)

    def test_history_commit_failure_rolls_back_evidence_and_history(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            ds1, ev1 = dataset_pair(False)
            ds2, ev2 = dataset_pair(True)
            store.save_dataset(ds1, ev1)
            old_history = store.history_path.read_bytes()
            old_evidence = store.evidence_path.read_bytes()
            original_replace = store._commit_replace

            def fail_history(staged, target):
                if Path(target) == store.history_path:
                    raise OSError("injected canonical commit failure")
                return original_replace(staged, target)

            store._commit_replace = fail_history
            with self.assertRaises(OSError):
                store.save_dataset(ds2, ev2)
            self.assertEqual(store.history_path.read_bytes(), old_history)
            self.assertEqual(store.evidence_path.read_bytes(), old_evidence)


if __name__ == "__main__":
    unittest.main()
