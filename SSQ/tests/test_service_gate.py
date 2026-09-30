from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
from glp.service import LottoService  # noqa: E402


class _Prediction:
    def to_dict(self):
        return {"target_issue": "2099001"}


class ServiceGateTests(unittest.TestCase):
    def test_offline_run_never_reuses_historical_pass(self) -> None:
        service = LottoService.__new__(LottoService)
        service.ensure_seed = lambda: None

        def offline(progress=None):
            raise ConnectionError("official sources unavailable")

        service.update = offline
        service._load_draws = lambda: []
        service._canonical_hash = lambda: "canonical-hash"
        service._court = lambda draws, canonical_hash, progress=None: {}
        service._existing_freeze = lambda target: {"target_issue": target, "freeze_hash": "old-freeze"}
        service._existing_gate = lambda target: {"status": "PASS", "gate_hash": "old-gate"}

        with patch("glp.service.make_prediction", return_value=(_Prediction(), {})):
            result = service.predict()

        self.assertEqual(result["historical_gate"]["status"], "PASS")
        self.assertEqual(result["final_gate"]["status"], "FAIL")
        self.assertFalse(result["final_gate"]["checks"]["current_version_revalidation"])
        self.assertGreater(result["final_gate"]["hard_fail_count"], 0)
        self.assertIn("ConnectionError", result["auto_update_error"])
        self.assertTrue(result["immutable_freeze_preserved"])

    def test_audit_reuses_strict_current_official_evidence(self) -> None:
        service = LottoService.__new__(LottoService)
        service.ensure_seed = lambda: None
        service._current_verified_official_snapshot = lambda: {
            "source": "persisted-current-official-evidence",
            "crosscheck_status": "PASS",
            "reused_current_evidence": True,
        }

        def must_not_refetch(progress=None):
            raise AssertionError("current verified official evidence must not be refetched")

        service.update = must_not_refetch
        service._load_draws = lambda: []
        service._canonical_hash = lambda: "current-canonical"
        service._freeze_count = lambda: 0
        service._court = lambda draws, canonical_hash, progress=None: {
            "software_verdict": "PASS", "gates": []
        }
        service.self_test = lambda fast=False: {"status": "PASS"}
        recorded = []
        service._append_experiment = lambda kind, status, input_hash, payload: recorded.append(
            (kind, status, input_hash, payload)
        ) or 1

        class _Preview:
            def to_dict(self):
                return {"status": "research-only"}

        with (
            patch("glp.service.make_prediction", return_value=(_Preview(), {})),
            patch("glp.service.build_ors_record", return_value={"status": "PASS"}),
        ):
            result = service.audit()

        self.assertEqual(result["software_verdict"], "PASS")
        self.assertTrue(result["auto_update"]["reused_current_evidence"])
        self.assertIsNone(result["auto_update_error"])
        self.assertEqual(recorded[-1][0:3], ("audit", "PASS", "current-canonical"))

    def test_current_snapshot_rejects_stale_network_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence_path = root / "source_evidence.json"
            now = datetime.now(timezone.utc)
            stale = (now - timedelta(hours=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            evidence_path.write_text(json.dumps({
                "game": "SSQ",
                "fetched_at": stale,
                "crosscheck_status": "PASS",
                "canonical_hash": "canonical",
                "source_receipts": [
                    {"source": "official_shanghai_L1", "status": "PASS", "fetched_at": stale},
                    {"source": "official_hebei_L2", "status": "PASS", "fetched_at": stale},
                ],
            }), encoding="utf-8")

            service = LottoService.__new__(LottoService)
            service.store = type("StoreStub", (), {"evidence_path": evidence_path})()
            service._integrity_check = lambda: {"ok": True}
            service._canonical_hash = lambda: "canonical"
            self.assertIsNone(service._current_verified_official_snapshot())

    def test_current_snapshot_accepts_only_short_lived_network_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence_path = root / "source_evidence.json"
            fresh = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            evidence_path.write_text(json.dumps({
                "game": "SSQ",
                "fetched_at": fresh,
                "crosscheck_status": "PASS",
                "canonical_hash": "canonical",
                "source_receipts": [
                    {"source": "official_shanghai_L1", "status": "PASS", "fetched_at": fresh},
                    {"source": "official_hebei_L2", "status": "PASS", "fetched_at": fresh},
                ],
            }), encoding="utf-8")

            service = LottoService.__new__(LottoService)
            service.store = type("StoreStub", (), {"evidence_path": evidence_path})()
            service._integrity_check = lambda: {"ok": True}
            service._canonical_hash = lambda: "canonical"
            snapshot = service._current_verified_official_snapshot()
            self.assertIsNotNone(snapshot)
            self.assertTrue(snapshot["reused_current_evidence"])
            self.assertLessEqual(snapshot["evidence_age_seconds"], snapshot["max_reuse_age_seconds"])

    def test_current_snapshot_rejects_future_or_malformed_receipt_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence_path = root / "source_evidence.json"
            fresh = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            for bad in (future, "not-a-time", None):
                with self.subTest(bad=bad):
                    evidence_path.write_text(json.dumps({
                        "game": "SSQ",
                        "fetched_at": fresh,
                        "crosscheck_status": "PASS",
                        "canonical_hash": "canonical",
                        "source_receipts": [
                            {"source": "official_shanghai_L1", "status": "PASS", "fetched_at": fresh},
                            {"source": "official_hebei_L2", "status": "PASS", "fetched_at": bad},
                        ],
                    }), encoding="utf-8")
                    service = LottoService.__new__(LottoService)
                    service.store = type("StoreStub", (), {"evidence_path": evidence_path})()
                    service._integrity_check = lambda: {"ok": True}
                    service._canonical_hash = lambda: "canonical"
                    self.assertIsNone(service._current_verified_official_snapshot())

    def test_current_snapshot_rejects_noncurrent_integrity(self) -> None:
        service = LottoService.__new__(LottoService)
        service._integrity_check = lambda: {"ok": False}
        self.assertIsNone(service._current_verified_official_snapshot())


if __name__ == "__main__":
    unittest.main()
