from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "SSQ"))
from launcher import (  # noqa: E402
    _preserve_failed_network_evidence,
    _preserve_live_evidence,
    _run_corrupt_repair_fault_injection,
    main,
)


class LauncherEvidenceTests(unittest.TestCase):
    def test_corrupt_repair_uses_isolated_synthetic_raw_without_live_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "corrupt-repair.json"
            with patch.object(sys, "argv", [
                "launcher.py", "--check", "corrupt-repair", "--result-file", str(result_path),
            ]):
                self.assertEqual(main(), 0)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            detail = result["result"]
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["scope"], "corrupt-repair")
            self.assertEqual(result["final_release_gate"], "PENDING")
            self.assertEqual(result["test_data_classification"], "TEST_ONLY_SYNTHETIC")
            self.assertEqual(result["real_network_status"], "PENDING")
            self.assertFalse(result["real_network_tested"])
            self.assertEqual(result["production_repair_status"], "PENDING")
            self.assertEqual(detail["validation_scope"], "FAULT_INJECTION_ONLY")
            self.assertTrue(all(detail["checks"].values()))
            self.assertEqual(detail["escaped_network_calls"], 0)
            self.assertFalse(detail["synthetic_artifacts_exported"])
            self.assertFalse((result_path.parent / "raw_responses").exists())
            self.assertFalse((result_path.parent / "corrupt-repair-source-evidence.json").exists())

    def test_corrupt_repair_restores_transport_after_exception(self) -> None:
        import requests
        import glp.sources as sources
        from glp.service import LottoService
        from glp.storage import Store

        original_net_get = sources.NET.get
        original_session_request = requests.sessions.Session.request
        with tempfile.TemporaryDirectory() as directory:
            svc = LottoService(Store(Path(directory) / "isolated-store"))
            with patch.object(LottoService, "repair", side_effect=RuntimeError("injected repair failure")):
                with self.assertRaisesRegex(RuntimeError, "injected repair failure"):
                    _run_corrupt_repair_fault_injection(svc)
        self.assertEqual(sources.NET.get, original_net_get)
        self.assertIs(requests.sessions.Session.request, original_session_request)

    def test_corrupt_repair_does_not_pass_when_raw_proof_fails(self) -> None:
        from glp.service import LottoService
        from glp.storage import Store

        with tempfile.TemporaryDirectory() as directory:
            svc = LottoService(Store(Path(directory) / "isolated-store"))
            with patch.object(Store, "validate_raw_evidence", side_effect=ValueError("injected raw failure")):
                result = _run_corrupt_repair_fault_injection(svc)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["synthetic_raw_hashes_match"])
        self.assertEqual(result["real_network_status"], "PENDING")
        self.assertEqual(result["production_repair_status"], "PENDING")

    def test_failed_network_bundle_survives_temporary_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure_root = root / "store" / "failed"
            bundle = failure_root / ("a" * 24)
            raw = b"official 403 body\r\n"
            digest = hashlib.sha256(raw).hexdigest()
            (bundle / "raw_responses").mkdir(parents=True)
            (bundle / "raw_responses" / f"{digest}.bin").write_bytes(raw)
            (bundle / "failure_evidence.json").write_text(json.dumps({
                "status": "FAIL", "crosscheck_status": "FAIL",
                "raw_responses": [{"sha256": digest, "bytes": len(raw),
                                   "artifact": f"raw_responses/{digest}.bin"}],
            }), encoding="utf-8")
            result = root / "evidence" / "update.json"
            proof = _preserve_failed_network_evidence(
                SimpleNamespace(failure_root=failure_root), str(result)
            )
            self.assertEqual(proof["status"], "FAIL")
            self.assertEqual(proof["bundles"][0]["raw_response_count"], 1)
            exported = result.parent / "failed"
            self.assertEqual((exported / "raw_responses" / f"{digest}.bin").read_bytes(), raw)
            self.assertEqual(json.loads((exported / (("a" * 24) + ".json")).read_text())
                             ["status"], "FAIL")

    def test_mutated_failed_raw_body_cannot_be_exported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "failed" / ("b" * 24)
            (bundle / "raw_responses").mkdir(parents=True)
            digest = hashlib.sha256(b"original").hexdigest()
            (bundle / "raw_responses" / f"{digest}.bin").write_bytes(b"mutated")
            (bundle / "failure_evidence.json").write_text(json.dumps({
                "status": "FAIL", "crosscheck_status": "FAIL",
                "raw_responses": [{"sha256": digest, "bytes": 8,
                                   "artifact": f"raw_responses/{digest}.bin"}],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                _preserve_failed_network_evidence(
                    SimpleNamespace(failure_root=root / "failed"),
                    str(root / "evidence" / "update.json"),
                )

    def test_preserves_exact_raw_bytes_outside_temporary_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store_root = root / "store"
            raw_root = store_root / "raw_responses"
            raw_root.mkdir(parents=True)
            raw = b"{\"official\":true}\r\n"
            digest = hashlib.sha256(raw).hexdigest()
            (raw_root / f"{digest}.bin").write_bytes(raw)
            evidence_path = store_root / "source_evidence.json"
            evidence_path.write_text(json.dumps({
                "raw_response_status": "PASS",
                "raw_responses": [{"sha256": digest, "bytes": len(raw)}],
            }), encoding="utf-8")
            history_path = store_root / "canonical_history.json"
            history_path.write_text('{"game":"SSQ"}', encoding="utf-8")
            store = SimpleNamespace(evidence_path=evidence_path, raw_root=raw_root, history_path=history_path)
            result_path = root / "acceptance" / "update.json"
            proof = _preserve_live_evidence(store, str(result_path))
            preserved = result_path.parent / "raw_responses" / f"{digest}.bin"
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(preserved.read_bytes(), raw)
            self.assertEqual(proof["raw_response_count"], 1)
            self.assertTrue((result_path.parent / proof["canonical"]).is_file())

    def test_missing_or_mutated_raw_bytes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_root = root / "raw_responses"
            raw_root.mkdir()
            raw = b"valid"
            digest = hashlib.sha256(raw).hexdigest()
            (raw_root / f"{digest}.bin").write_bytes(b"tampered")
            evidence_path = root / "source_evidence.json"
            evidence_path.write_text(json.dumps({
                "raw_response_status": "PASS",
                "raw_responses": [{"sha256": digest, "bytes": len(raw)}],
            }), encoding="utf-8")
            store = SimpleNamespace(evidence_path=evidence_path, raw_root=raw_root)
            with self.assertRaises(ValueError):
                _preserve_live_evidence(store, str(root / "acceptance" / "update.json"))


if __name__ == "__main__":
    unittest.main()
