"""SHADOW CLI adversarial evidence ingestion, never an official source test."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.harness_v46.core import RULES
from research.harness_v46.tests.test_core import fixture
from research.harness_v46 import prospective_cycle


class ClosedLoopEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.workspace = self.home / "workspace"
        self.now = datetime.now(timezone.utc)
        self.snaps = {g: fixture(g) for g in RULES}
        for s in self.snaps.values():
            s["as_of"] = (self.now - timedelta(hours=1)).isoformat()
            s["sales_cutoff"] = (self.now + timedelta(hours=4)).isoformat()
            s["target_draw_at"] = (self.now + timedelta(hours=5)).isoformat()

    def cli(self, *more):
        return subprocess.run(
            [sys.executable, "-m", "research.harness_v46.closed_loop",
             "--workspace", str(self.workspace), *more],
            capture_output=True, text=True, timeout=50,
        )

    def test_duplicate_nested_snapshot_key_blocks_before_frozen_ledger(self):
        source = self.home / "ambiguous.json"
        raw = json.dumps(self.snaps)
        raw = raw.replace('"target_issue": "29999"',
                          '"target_issue": "29999", "target_issue": "30000"', 1)
        source.write_text(raw, encoding="utf-8")
        out = self.cli("--snapshot-bundle", str(source))
        self.assertEqual(out.returncode, 2)
        self.assertIn("CLOSED_LOOP_JSON_DUPLICATE_KEY", out.stderr)
        self.assertFalse((self.workspace / "ledger.sqlite3").exists())

    def test_nonfinite_snapshot_rejected_before_freeze(self):
        source = self.home / "nan.json"
        raw = json.dumps(self.snaps).replace('"target_issue": "29999"',
                                          '"extra_float": NaN, "target_issue": "29999"', 1)
        source.write_text(raw, encoding="utf-8")
        out = self.cli("--snapshot-bundle", str(source))
        self.assertEqual(out.returncode, 2)
        self.assertIn("CLOSED_LOOP_JSON_NONFINITE", out.stderr)
        self.assertFalse((self.workspace / "ledger.sqlite3").exists())

    def test_duplicate_outcome_fields_never_issue_valid_score_receipt(self):
        self.workspace.mkdir()
        run_id = prospective_cycle.forecast_on_demand(
            self.snaps, self.workspace / "ledger.sqlite3", now=self.now)["run_id"]
        outcome = {
            g: {"lottery": g, "issue": "29999",
                "front": list(self.snaps[g]["draws"][-2]["front"]),
                "back": list(self.snaps[g]["draws"][-2]["back"]),
                "drawn_at": self.snaps[g]["target_draw_at"]}
            for g in RULES
        }
        raw = json.dumps(outcome)
        raw = raw.replace('"lottery": "SSQ"', '"lottery": "SSQ", "front": [1,2,3,4,5,6]', 1)
        folder = self.workspace / "outcomes"
        folder.mkdir()
        (folder / (run_id + ".json")).write_text(raw, encoding="utf-8")
        out = self.cli()
        self.assertEqual(out.returncode, 2)
        self.assertIn("CLOSED_LOOP_JSON_DUPLICATE_KEY", out.stderr)
        self.assertFalse((self.workspace / "receipts" / (run_id + ".json")).exists())


if __name__ == "__main__":
    unittest.main()
