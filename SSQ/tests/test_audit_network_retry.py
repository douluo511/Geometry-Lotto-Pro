from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "SSQ"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
from glp.service import LottoService  # noqa: E402
from glp.storage import Store  # noqa: E402


class AuditUpdateRetryTests(unittest.TestCase):
    def _service(self, root: str) -> LottoService:
        return LottoService(Store(Path(root)))

    def test_transient_deadline_retries_once_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            success = {
                "crosscheck_status": "PASS",
                "source": "official-source-quorum",
                "canonical_hash": "a" * 64,
            }
            transient = RuntimeError(
                'SourceError: diagnostic={"shanghai": '
                '"OperationDeadlineExceeded: official HTTPS GET exceeded total operation timeout"}'
            )
            with patch.object(svc, "update", side_effect=[transient, success]) as update:
                with patch("glp.service.time.sleep") as sleep:
                    result, error, attempts = svc._audit_update_with_retry()
            self.assertEqual(result, success)
            self.assertIsNone(error)
            self.assertEqual(update.call_count, 2)
            sleep.assert_called_once()
            self.assertEqual([row["status"] for row in attempts], ["FAIL", "PASS"])
            self.assertTrue(attempts[0]["retryable"])

    def test_semantic_or_schema_failure_never_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            semantic = RuntimeError(
                "SourceError: 官方来源最新期冲突，拒绝更新: Shanghai=2026113 Hebei=2026112"
            )
            with patch.object(svc, "update", side_effect=semantic) as update:
                with patch("glp.service.time.sleep") as sleep:
                    result, error, attempts = svc._audit_update_with_retry()
            self.assertIsNone(result)
            self.assertIn("官方来源最新期冲突", error or "")
            self.assertEqual(update.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(len(attempts), 1)
            self.assertFalse(attempts[0]["retryable"])

    def test_predict_uses_bounded_transient_retry_contract(self) -> None:
        import inspect

        source = inspect.getsource(LottoService.predict)
        self.assertIn("update_with_transient_retry", source)
        self.assertIn("auto_update_attempts", source)
        self.assertNotIn("update_result = self.update(progress=progress)", source)

    def test_repair_rebuild_transient_deadline_retries_once_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            transient = RuntimeError(
                'SourceError: diagnostic={"shanghai": '
                '"OperationDeadlineExceeded: official HTTPS GET exceeded total operation timeout"}'
            )
            dataset = SimpleNamespace(crosscheck_status="PASS")
            evidence = {"verification": "official-quorum"}
            with patch(
                "glp.service.build_canonical",
                side_effect=[transient, (dataset, evidence)],
            ) as build:
                with patch("glp.service.time.sleep") as sleep:
                    got_dataset, got_evidence, error, attempts = (
                        svc._repair_build_with_transient_retry([])
                    )
            self.assertIs(got_dataset, dataset)
            self.assertEqual(got_evidence, evidence)
            self.assertIsNone(error)
            self.assertEqual(build.call_count, 2)
            sleep.assert_called_once()
            self.assertEqual([row["status"] for row in attempts], ["FAIL", "PASS"])
            self.assertTrue(attempts[0]["retryable"])

    def test_repair_rebuild_semantic_failure_never_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            semantic = RuntimeError(
                "SourceError: 官方来源最新期冲突，拒绝更新: Shanghai=2026113 Hebei=2026112"
            )
            with patch("glp.service.build_canonical", side_effect=semantic) as build:
                with patch("glp.service.time.sleep") as sleep:
                    dataset, evidence, error, attempts = (
                        svc._repair_build_with_transient_retry([])
                    )
            self.assertIsNone(dataset)
            self.assertIsNone(evidence)
            self.assertIn("官方来源最新期冲突", error or "")
            self.assertEqual(build.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(len(attempts), 1)
            self.assertFalse(attempts[0]["retryable"])

    def test_repair_rebuild_second_transient_failure_stays_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            failures = [
                RuntimeError("ConnectionError: temporary reset"),
                RuntimeError(
                    "OperationDeadlineExceeded: official HTTPS GET exceeded total operation timeout"
                ),
            ]
            with patch("glp.service.build_canonical", side_effect=failures) as build:
                with patch("glp.service.time.sleep") as sleep:
                    dataset, evidence, error, attempts = (
                        svc._repair_build_with_transient_retry([])
                    )
            self.assertIsNone(dataset)
            self.assertIsNone(evidence)
            self.assertIn("OperationDeadlineExceeded", error or "")
            self.assertEqual(build.call_count, 2)
            sleep.assert_called_once()
            self.assertEqual(len(attempts), 2)
            self.assertTrue(all(row["status"] == "FAIL" for row in attempts))

    def test_second_transient_failure_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            svc = self._service(directory)
            first = RuntimeError("ConnectionError: temporary reset")
            second = RuntimeError(
                "OperationDeadlineExceeded: official HTTPS GET exceeded total operation timeout"
            )
            with patch.object(svc, "update", side_effect=[first, second]) as update:
                with patch("glp.service.time.sleep") as sleep:
                    result, error, attempts = svc._audit_update_with_retry()
            self.assertIsNone(result)
            self.assertIn("OperationDeadlineExceeded", error or "")
            self.assertEqual(update.call_count, 2)
            sleep.assert_called_once()
            self.assertEqual(len(attempts), 2)
            self.assertTrue(all(row["status"] == "FAIL" for row in attempts))


if __name__ == "__main__":
    unittest.main()
