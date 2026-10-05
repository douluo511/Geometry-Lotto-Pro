from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))

from glp.constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL  # noqa: E402
from glp.domain import CanonicalDataset, Draw, SourceReceipt  # noqa: E402
from glp.sources import (  # noqa: E402
    SourceError, _date, _expected_latest_completed_draw_day, _validate_freshness,
    _validate_history, build_canonical, fetch_national_page, parse_shanghai_history,
)
from glp.service import LottoService  # noqa: E402
from glp.storage import Store  # noqa: E402
from glp.util import sha256_bytes, sha256_json, utc_now  # noqa: E402


class FakeResponse:
    def __init__(self, raw: bytes, *, url: str = NATIONAL_URL, content_type: str = "application/json"):
        self.content = raw
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        raise AssertionError("parser must consume the preserved raw bytes")


class SourceParsingTests(unittest.TestCase):
    def test_invalid_calendar_date_is_rejected(self) -> None:
        with self.assertRaises(SourceError):
            _date("2026-02-30")

    def test_national_any_malformed_row_rejects_whole_page(self) -> None:
        year = datetime.now(timezone.utc).year
        good = {"code": f"{year}001", "date": datetime.now(timezone.utc).date().isoformat(),
                "red": "01,02,03,04,05,06", "blue": "07"}
        raw = json.dumps({"state": 0, "result": [good, {**good, "red": "01,02,03,04,05,99"}],
                          "pageNum": 1}).encode()
        with patch("glp.sources.NET.get", return_value=FakeResponse(raw)):
            with self.assertRaises(SourceError):
                fetch_national_page(1)

    def test_national_wrong_content_type_and_redirect_fail_closed(self) -> None:
        raw = b'{"state":0,"result":[],"pageNum":1}'
        with patch("glp.sources.NET.get", return_value=FakeResponse(raw, content_type="text/html")):
            with self.assertRaises(SourceError):
                fetch_national_page(1)
        with patch("glp.sources.NET.get", return_value=FakeResponse(raw, url="https://example.com/mirror")):
            with self.assertRaises(SourceError):
                fetch_national_page(1)

    def test_final_http_error_body_is_captured_but_never_parsed(self) -> None:
        response = FakeResponse(b"rate limited")
        response.status_code = 429
        error = requests.HTTPError("rate limited", response=response)
        captured = []
        with patch("glp.sources.NET.get", side_effect=error):
            with self.assertRaises(requests.HTTPError):
                fetch_national_page(1, lambda metadata, raw: captured.append((metadata, raw)))
        self.assertEqual(captured[0][0]["http_status"], 429)
        self.assertEqual(captured[0][1], b"rate limited")

    def test_returned_final_retryable_http_status_is_also_captured(self) -> None:
        response = FakeResponse(b"server unavailable")
        response.status_code = 503
        response.glp_attempts = ({"attempt": 1, "outcome": "FINAL_RETRYABLE_HTTP"},)
        captured = []
        with patch("glp.sources.NET.get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                fetch_national_page(1, lambda metadata, raw: captured.append((metadata, raw)))
        self.assertEqual(captured[0][0]["http_status"], 503)
        self.assertEqual(captured[0][0]["attempts"][0]["outcome"], "FINAL_RETRYABLE_HTTP")
        self.assertEqual(captured[0][1], b"server unavailable")

    def test_shanghai_conflicting_duplicate_issue_is_rejected(self) -> None:
        year = datetime.now(timezone.utc).year
        day = datetime.now(timezone.utc).date().isoformat()
        raw = f"{year}001 {day} 010203040506 07 {year}001 {day} 010203040506 08"
        with self.assertRaises(SourceError):
            parse_shanghai_history(raw)

    def test_stale_latest_draw_is_rejected(self) -> None:
        old = Draw("2020001", "2020-01-01", (1, 2, 3, 4, 5, 6), (7,))
        with self.assertRaises(SourceError):
            _validate_history([old], "test")

    def test_freshness_uses_2026_official_national_day_closure(self) -> None:
        latest = Draw("2026113", "2026-09-29", (3, 4, 20, 24, 29, 30), (11,))
        info = _validate_freshness([latest], "test", today=date(2026, 10, 1))
        self.assertEqual(info["expected_latest_completed_draw_date"], "2026-09-29")
        self.assertEqual(info["latest_date"], "2026-09-29")
        self.assertEqual(info["policy_year"], 2026)
        self.assertIn("mof.gov.cn", info["policy_sources"]["closure"])

    def test_scheduled_draw_day_allows_prior_completed_draw_until_next_day(self) -> None:
        prior = Draw("2026112", "2026-09-27", (1, 2, 3, 4, 5, 6), (7,))
        info = _validate_freshness([prior], "test", today=date(2026, 9, 29))
        self.assertEqual(info["expected_latest_completed_draw_date"], "2026-09-27")
        stale = Draw("2026111", "2026-09-24", (1, 2, 3, 4, 5, 6), (7,))
        with self.assertRaises(SourceError):
            _validate_history([stale], "test", today=date(2026, 9, 29))

    def test_unknown_freshness_calendar_year_fails_closed(self) -> None:
        with self.assertRaisesRegex(SourceError, "updater required"):
            _expected_latest_completed_draw_day(date(2027, 1, 2))


class RawEvidenceStorageTests(unittest.TestCase):
    def test_service_update_records_transport_failure_without_fake_raw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            service = LottoService(store)
            service.ensure_seed()
            before_history = store.history_path.read_bytes()
            with patch("glp.sources.NET.get", side_effect=requests.ConnectionError("offline")):
                with self.assertRaises(SourceError):
                    service.update()
            manifest = next(store.failure_root.glob("*/failure_evidence.json"))
            failure = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "FAIL")
            self.assertEqual(failure["raw_response_status"], "UNAVAILABLE")
            self.assertEqual(failure["raw_responses"], [])
            self.assertEqual(set(failure["source_errors"]), {"national", "shanghai", "hebei"})
            self.assertEqual(store.history_path.read_bytes(), before_history)

    def test_failed_quorum_preserves_http_errors_without_replacing_dataset(self) -> None:
        dataset, accepted_evidence = self._fixture()
        failures = {
            NATIONAL_URL: (429, b"CWL rate limited"),
            SHANGHAI_URL: (503, b"Shanghai unavailable"),
            HEBEI_URL: (503, b"Hebei unavailable"),
        }

        def unavailable(url, **kwargs):
            status, raw = failures.get(url, (503, b"Hebei announcement unavailable"))
            response = FakeResponse(raw, url=url)
            response.status_code = status
            raise requests.HTTPError(f"HTTP {status}", response=response)

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_dataset(dataset, accepted_evidence)
            before_history = store.history_path.read_bytes()
            before_evidence = store.evidence_path.read_bytes()
            with patch("glp.sources.NET.get", side_effect=unavailable):
                with self.assertRaises(SourceError) as context:
                    build_canonical(baseline_draws=dataset.draws,
                                    failure_sink=store.save_failure_evidence)
            self.assertEqual(store.history_path.read_bytes(), before_history)
            self.assertEqual(store.evidence_path.read_bytes(), before_evidence)
            manifests = list(store.failure_root.glob("*/failure_evidence.json"))
            self.assertEqual(len(manifests), 1, str(context.exception))
            failure = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "FAIL")
            self.assertEqual(failure["crosscheck_status"], "FAIL")
            self.assertEqual(failure["raw_response_status"], "FAIL")
            self.assertEqual(len(failure["raw_responses"]), 3)
            self.assertTrue(all(r["http_status"] in (429, 503) for r in failure["raw_responses"]))
            for record in failure["raw_responses"]:
                raw = manifests[0].parent / record["artifact"]
                self.assertEqual(sha256_bytes(raw.read_bytes()), record["sha256"])
                self.assertTrue(record["fetched_at"].endswith("Z"))

    def test_cross_source_conflict_persists_all_received_bytes_as_fail(self) -> None:
        now = datetime.now(timezone.utc)
        issue, day = f"{now.year}001", now.date().isoformat()
        national = json.dumps({"state": 0, "result": [{
            "code": issue, "date": day, "red": "01,02,03,04,05,06", "blue": "07",
        }], "pageNum": 1}).encode()
        conflicting = f"{issue} {day} 010203040506 08".encode()

        def get(url, **kwargs):
            if url == NATIONAL_URL:
                return FakeResponse(national)
            if url == SHANGHAI_URL:
                return FakeResponse(conflicting, url=url, content_type="text/html")
            response = FakeResponse(b"unavailable", url=url)
            response.status_code = 503
            raise requests.HTTPError("HTTP 503", response=response)

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            with patch("glp.sources.NET.get", side_effect=get):
                with self.assertRaises(SourceError):
                    build_canonical(failure_sink=store.save_failure_evidence)
            self.assertFalse(store.history_path.exists())
            self.assertFalse(store.evidence_path.exists())
            manifest = next(store.failure_root.glob("*/failure_evidence.json"))
            failure = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "FAIL")
            self.assertIn("CWL-vs-Shanghai", failure["reason"])
            self.assertEqual(len(failure["raw_responses"]), 3)
            self.assertEqual([r["status"] for r in failure["source_receipts"]], ["PASS", "PASS", "FAIL"])

    def test_malformed_and_stale_sources_leave_failure_evidence(self) -> None:
        now = datetime.now(timezone.utc)
        stale = json.dumps({"state": 0, "result": [{
            "code": "2020001", "date": "2020-01-01",
            "red": "01,02,03,04,05,06", "blue": "07",
        }], "pageNum": 1}).encode()
        cases = [(b"not JSON", "JSON"), (stale, "stale")]
        for raw, marker in cases:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory))

                def get(url, **kwargs):
                    if url == NATIONAL_URL:
                        return FakeResponse(raw)
                    response = FakeResponse(b"unavailable", url=url)
                    response.status_code = 503
                    raise requests.HTTPError("HTTP 503", response=response)

                with patch("glp.sources.NET.get", side_effect=get):
                    with self.assertRaises(SourceError):
                        build_canonical(failure_sink=store.save_failure_evidence)
                failure_path = next(store.failure_root.glob("*/failure_evidence.json"))
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
                self.assertEqual(failure["status"], "FAIL")
                self.assertIn(marker.lower(), failure["source_errors"]["national"].lower())
                self.assertEqual(failure["raw_responses"][0]["sha256"], sha256_bytes(raw))
                self.assertFalse(store.history_path.exists())

    def test_packaged_seed_can_bootstrap_but_cannot_pass_live_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            LottoService(store).ensure_seed()
            baseline = store.baseline_integrity_check()
            self.assertEqual(baseline["status"], "PASS", baseline)
            self.assertEqual(store.integrity_check()["status"], "FAIL")

    def test_mocked_official_contract_binds_every_raw_response(self) -> None:
        """Contract test only: mocked responses never prove a live network PASS."""
        now = datetime.now(timezone.utc)
        issue = f"{now.year}001"
        day = now.date().isoformat()
        national_raw = json.dumps({
            "state": 0, "result": [{
                "code": issue, "date": day, "red": "01,02,03,04,05,06", "blue": "07",
            }], "pageNum": 1,
        }).encode()
        shanghai_raw = f"<table><tr><td>{issue}</td><td>{day}</td><td>010203040506</td><td>07</td></tr></table>".encode()
        home_raw = (
            f'<li class="kj-info-item"><img src="logo_ssq.png"/><p>第 {issue} 期</p>'
            '<div class="cirle-number">'
            + "".join(f"<span>{ball:02d}</span>" for ball in range(1, 7))
            + '<span class="blue-num">07</span></div></li>'
        ).encode()
        announce_raw = f"开奖日期：{day} 开奖号码：01 02 03 04 05 06 07".encode()
        responses = {
            NATIONAL_URL: FakeResponse(national_raw),
            SHANGHAI_URL: FakeResponse(shanghai_raw, url=SHANGHAI_URL, content_type="text/html"),
            HEBEI_URL: FakeResponse(home_raw, url=HEBEI_URL, content_type="text/html"),
            HEBEI_ANNOUNCE_URL: FakeResponse(announce_raw, url=HEBEI_ANNOUNCE_URL, content_type="text/html"),
        }
        with patch("glp.sources.NET.get", side_effect=lambda url, **kwargs: responses[url]):
            dataset, evidence = build_canonical()
        self.assertEqual(dataset.crosscheck_status, "PASS")
        self.assertEqual(len(evidence["raw_responses"]), 4)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_dataset(dataset, evidence)
            persisted = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(Store.validate_raw_evidence(persisted, Path(directory)), 4)
            self.assertEqual(store.integrity_check()["status"], "PASS")

            failed_primary = FakeResponse(b"Forbidden")
            failed_primary.status_code = 403

            def primary_unavailable(url, **kwargs):
                if url == NATIONAL_URL:
                    raise requests.HTTPError("Forbidden", response=failed_primary)
                return responses[url]

            with patch("glp.sources.NET.get", side_effect=primary_unavailable):
                with self.assertRaises(SourceError):
                    build_canonical(baseline_draws=dataset.draws, baseline_raw_verified=False,
                                    baseline_evidence=persisted)
                fallback_dataset, fallback_evidence = build_canonical(
                    baseline_draws=dataset.draws, baseline_raw_verified=True,
                    baseline_evidence=persisted,
                )
            self.assertEqual(fallback_evidence["verification"], "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS")
            self.assertEqual(fallback_evidence["source_receipts"][0]["status"], "FAIL")
            store.save_dataset(fallback_dataset, fallback_evidence)
            self.assertEqual(store.integrity_check()["status"], "PASS")
            failed_primary_digest = sha256_bytes(b"Forbidden")
            self.assertEqual((store.raw_root / f"{failed_primary_digest}.bin").read_bytes(), b"Forbidden")
            self.assertTrue(any(
                record["sha256"] == failed_primary_digest and record["http_status"] == 403
                for record in fallback_evidence["raw_responses"]
            ))

    def _fixture(self):
        now = datetime.now(timezone.utc)
        draw = Draw(f"{now.year}001", now.date().isoformat(), (1, 2, 3, 4, 5, 6), (7,))
        canonical_hash = sha256_json([draw.to_dict()])
        national_raw = json.dumps({"state": 0, "result": [{
            "code": draw.issue, "date": draw.draw_date,
            "red": "01,02,03,04,05,06", "blue": "07",
        }], "pageNum": 1}).encode("utf-8")
        raws = {
            NATIONAL_URL: national_raw,
            SHANGHAI_URL: f"{draw.issue} {draw.draw_date} 010203040506 07".encode("utf-8"),
        }
        records = []
        payloads = {}
        for url, raw in raws.items():
            digest = sha256_bytes(raw)
            source = "official_cwl_L0" if url == NATIONAL_URL else "official_shanghai_L1"
            records.append({
                "source": source, "url": url, "requested_url": url,
                "request_params": {"pageNo": "1"} if url == NATIONAL_URL else {},
                "fetched_at": utc_now(), "http_status": 200,
                "sha256": digest, "bytes": len(raw), "artifact": f"raw_responses/{digest}.bin",
            })
            payloads[digest] = raw
        national_manifest = [{"page": 1, "sha256": sha256_bytes(national_raw),
                              "bytes": len(national_raw), "url": NATIONAL_URL}]
        receipts = [
            SourceReceipt("official_cwl_L0", utc_now(), 200, sha256_json(national_manifest),
                          1, draw.issue, "PASS"),
            SourceReceipt("official_shanghai_L1", utc_now(), 200, sha256_bytes(raws[SHANGHAI_URL]), 1, draw.issue, "PASS"),
            SourceReceipt("official_hebei_L2", utc_now(), 0, "", 0, "", "FAIL", "mock unavailable"),
        ]
        dataset = CanonicalDataset([draw], canonical_hash, receipts, 1, "PASS")
        evidence = {
            "schema": "official-source-evidence-v8.5", "game": "SSQ",
            "canonical_hash": canonical_hash, "draw_count": 1, "latest": draw.to_dict(),
            "crosscheck_count": 1, "crosscheck_status": "PASS",
            "verification": "CWL_L0_PLUS_1_PROVINCIAL_VALIDATOR",
            "source_receipts": [asdict(r) for r in receipts],
            "national_raw_manifest": national_manifest, "raw_responses": records,
            "raw_response_status": "PENDING_PERSISTENCE", "_raw_response_payloads": payloads,
        }
        return dataset, evidence

    def test_save_preserves_raw_bytes_and_detects_tampering(self) -> None:
        dataset, evidence = self._fixture()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_dataset(dataset, evidence)
            persisted = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["raw_response_status"], "PASS")
            self.assertNotIn("_raw_response_payloads", persisted)
            self.assertEqual(Store.validate_raw_evidence(persisted, Path(directory)), 2)
            self.assertEqual(store.integrity_check()["status"], "PASS")
            target = store.raw_root / f"{persisted['raw_responses'][0]['sha256']}.bin"
            target.write_bytes(b"tampered")
            self.assertEqual(store.integrity_check()["status"], "FAIL")

    def test_missing_raw_bytes_cannot_replace_current_dataset(self) -> None:
        dataset, evidence = self._fixture()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            evidence["_raw_response_payloads"] = {}
            with self.assertRaises(ValueError):
                store.save_dataset(dataset, evidence)
            self.assertFalse(store.history_path.exists())
            self.assertFalse(store.evidence_path.exists())

    def test_commit_binding_tamper_fails_even_when_raw_files_are_intact(self) -> None:
        dataset, evidence = self._fixture()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_dataset(dataset, evidence)
            self.assertEqual(store.integrity_check()["status"], "PASS")
            persisted = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            persisted["crosscheck_count"] = 99
            store.evidence_path.write_text(json.dumps(persisted), encoding="utf-8")
            self.assertEqual(store.integrity_check()["status"], "FAIL")
            self.assertEqual(store.baseline_integrity_check()["status"], "FAIL")

    def test_legacy_evidence_is_baseline_only(self) -> None:
        dataset, evidence = self._fixture()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_dataset(dataset, evidence)
            persisted = json.loads(store.evidence_path.read_text(encoding="utf-8"))
            persisted["schema"] = "official-source-evidence-v8.3"
            persisted.pop("raw_responses")
            persisted.pop("raw_response_status")
            store.evidence_path.write_text(json.dumps(persisted), encoding="utf-8")
            self.assertEqual(store.baseline_integrity_check()["status"], "FAIL")
            self.assertEqual(store.integrity_check()["status"], "FAIL")

    def test_failed_primary_http_body_cannot_be_grafted_into_primary_pass(self) -> None:
        dataset, evidence = self._fixture()
        raw = b"rate limited"
        digest = sha256_bytes(raw)
        evidence["raw_responses"].append({
            "source": "official_cwl_L0", "url": NATIONAL_URL, "requested_url": NATIONAL_URL,
            "request_params": {"pageNo": "1"}, "fetched_at": utc_now(), "http_status": 429,
            "sha256": digest, "bytes": len(raw), "artifact": f"raw_responses/{digest}.bin",
        })
        evidence["_raw_response_payloads"][digest] = raw
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            with self.assertRaises(ValueError):
                store.save_dataset(dataset, evidence)
            self.assertFalse(store.history_path.exists())
            self.assertFalse(store.evidence_path.exists())


if __name__ == "__main__":
    unittest.main()
