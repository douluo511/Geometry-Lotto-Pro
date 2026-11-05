"""P0: a historical live-network PASS is never formal prospective admission.

Fixtures are invented; neither case authenticates lottery source bytes.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import real_network_check as gate


class RealNetworkEvidenceClassTests(unittest.TestCase):
    _CONTRACT = {
        "evidence_class": "SHADOW",
        "history_asof_authenticity": "NOT_VERIFIED",
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "official_target_admission": "BLOCKED",
        "external_predraw_tsa": "NOT_VERIFIED",
        "official_outcome_authenticity": "NOT_VERIFIED",
        "prospective_verified": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
        "gate_scope": "LIVE_HISTORY_NETWORK_CROSSCHECK_ONLY",
    }

    def _call(self, payload=None, *, exc=None):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gate, "ROOT", Path(tmp)):
                with patch.object(gate, "build_canonical", return_value=payload, side_effect=exc):
                    with contextlib.redirect_stdout(io.StringIO()):
                        exit_code = gate.main()
            report = json.loads((Path(tmp) / "artifacts" / "real_network_check.json").read_text(encoding="utf-8"))
        return exit_code, report

    def _assert_not_promoted(self, report):
        for key, expected in self._CONTRACT.items():
            self.assertIn(key, report, key)
            self.assertEqual(report[key], expected, key)

    def test_synthetic_live_history_pass_is_still_shadow_not_prospective(self):
        dataset = SimpleNamespace(
            crosscheck_status="PASS", draws=[SimpleNamespace(issue="26123")],
            canonical_hash="a" * 64, crosscheck_count=120,
        )
        evidence = {
            "source_mode": "national_plus_jiangsu",
            "national_raw_manifest": [{"sha256": "b" * 64}],
            "jiangsu_raw_evidence": {"sha256": "c" * 64},
            "network_gate": "PASS", "freshness_gate": "PASS",
            "crosscheck_status": "PASS",
        }
        exit_code, report = self._call((dataset, evidence))
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "PASS")
        self._assert_not_promoted(report)

    def test_failed_source_keeps_explicit_blocked_prospective_labels(self):
        exit_code, report = self._call(exc=ValueError("JIANGSU_PUBLICATION_DATE_IS_NOT_DRAW_DATE"))
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("JIANGSU_PUBLICATION_DATE", report["error"])
        self._assert_not_promoted(report)


if __name__ == "__main__":
    unittest.main()
