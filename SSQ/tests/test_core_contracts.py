from __future__ import annotations

import random
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
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
from glp.constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL
from glp.util import sha256_bytes, sha256_json, utc_now


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None, url="https://example.invalid"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url
        self.history = []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


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
    """Mocked official responses for storage atomicity, never a live-network PASS."""
    today = datetime.now(timezone.utc).date()
    draws = [Draw(f"{today.year}001", (today - timedelta(days=3)).isoformat(),
                  (1, 2, 3, 4, 5, 6), (1,))]
    if extra:
        draws.append(Draw(f"{today.year}002", today.isoformat(), (2, 3, 4, 5, 6, 7), (2,)))
    digest = sha256_json([d.to_dict() for d in draws])
    national_raw = json.dumps({"state": 0, "result": [{
        "code": draw.issue, "date": draw.draw_date,
        "red": ",".join(f"{number:02d}" for number in draw.front),
        "blue": f"{draw.back[0]:02d}",
    } for draw in draws], "pageNum": 1}).encode("utf-8")
    latest = draws[-1]
    shanghai_raw = (
        f"{latest.issue} {latest.draw_date} "
        + "".join(f"{number:02d}" for number in latest.front)
        + f" {latest.back[0]:02d}"
    ).encode("utf-8")
    raws = {
        "official_cwl_L0": (NATIONAL_URL, national_raw, {"pageNo": "1"}),
        "official_shanghai_L1": (SHANGHAI_URL, shanghai_raw, {}),
    }
    records = []
    payloads = {}
    for source, (url, raw, params) in raws.items():
        raw_hash = sha256_bytes(raw)
        payloads[raw_hash] = raw
        records.append({
            "source": source, "url": url, "requested_url": url,
            "request_params": params, "fetched_at": utc_now(), "http_status": 200,
            "sha256": raw_hash, "bytes": len(raw), "artifact": f"raw_responses/{raw_hash}.bin",
        })
    national_manifest = [{"page": 1, "sha256": sha256_bytes(national_raw),
                          "bytes": len(national_raw), "url": NATIONAL_URL}]
    receipts = [
        SourceReceipt("official_cwl_L0", utc_now(), 200, sha256_json(national_manifest),
                      len(draws), draws[-1].issue, "PASS"),
        SourceReceipt("official_shanghai_L1", utc_now(), 200, sha256_bytes(shanghai_raw),
                      1, draws[-1].issue, "PASS"),
        SourceReceipt("official_hebei_L2", utc_now(), 0, "", 0, "", "FAIL", "mock unavailable"),
    ]
    ds = CanonicalDataset(draws, digest, receipts, 1, "PASS")
    ev = {
        "schema": "official-source-evidence-v8.5",
        "game": "SSQ",
        "canonical_hash": digest,
        "draw_count": len(draws),
        "latest": draws[-1].to_dict(),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "verification": "CWL_L0_PLUS_1_PROVINCIAL_VALIDATOR",
        "source_receipts": [asdict(r) for r in receipts],
        "national_raw_manifest": national_manifest,
        "raw_responses": records,
        "raw_response_status": "PENDING_PERSISTENCE",
        "_raw_response_payloads": payloads,
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
        response = FakeResponse(200, b"{", {"Content-Type": "application/json"}, url=NATIONAL_URL)
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)

    def test_invalid_encoding_fails_closed(self):
        response = FakeResponse(200, b"\xff\xfe\x00", {"Content-Type": "application/json"}, url=NATIONAL_URL)
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)

    def test_schema_drift_fails_closed(self):
        response = FakeResponse(
            200,
            b'{"state":0,"result":{"unexpected":true},"pageNum":1}',
            {"Content-Type": "application/json"},
            url=NATIONAL_URL,
        )
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError):
                sources.fetch_national_page(1)

    def test_malformed_row_fails_closed_instead_of_skipping(self):
        payload = (
            b'{"state":0,"pageNum":1,"result":['
            b'{"code":"2026100","date":"2026-09-01","red":"01,02,03,04,05,06","blue":"07"},'
            b'{"code":"bad","date":"2026-09-04","red":"01,02,03,04,05,06","blue":"07"}]}'
        )
        response = FakeResponse(200, payload, url=NATIONAL_URL)
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError) as context:
                sources.fetch_national_page(1)
        self.assertIn("row 1", str(context.exception))

    def test_duplicate_issue_on_page_fails_closed(self):
        row = {"code": "2026100", "date": "2026-09-01", "red": "01,02,03,04,05,06", "blue": "07"}
        response = FakeResponse(200, json.dumps({"state": 0, "pageNum": 1,
                                                 "result": [row, row]}).encode(), url=NATIONAL_URL)
        fake_net = type("N", (), {"get": lambda self, *a, **k: response})()
        with patch.object(sources, "NET", fake_net):
            with self.assertRaises(SourceError) as context:
                sources.fetch_national_page(1)
        self.assertIn("repeats issue", str(context.exception))

    def test_http_validation_metadata_has_parser_time_and_url(self):
        response = FakeResponse(200, b'{"x":1}', url="https://example.invalid/data")
        meta = _validate_http_payload(response, response.content, expected="json")
        self.assertEqual(meta["validation_result"], "PASS")
        self.assertTrue(meta["parser_version"])
        self.assertTrue(meta["fetched_at"].endswith("Z"))
        self.assertEqual(meta["final_url"], "https://example.invalid/data")


class SourceFailoverTests(unittest.TestCase):
    def test_primary_failure_secondary_consensus_cannot_recover_unverified_baseline(self):
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
            with self.assertRaises(SourceError):
                build_canonical(baseline_draws=draws)

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
