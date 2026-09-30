from __future__ import annotations

import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
