"""Schedule-only cloud live-issuer ledger: two runs, prior recovery and score tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.supercompute.v47_models import canonical
from research.supercompute.v47_live_ledger import record, verify, next_nominal_draw


class LiveScheduleLedgerTests(unittest.TestCase):
    def make_sources(self, root, issues=None):
        sources = root / "sources"
        sources.mkdir(exist_ok=True)
        issues = issues or {"ssq": ("2026130", "2026-11-12"),
                            "dlt": ("26129", "2026-11-11")}
        receipt = {"schema": "SSQDLT_V47_LIVE_ISSUER_INGEST_V1",
                   "status": "OVERLAP_VERIFIED", "games": {}}
        for game, (issue, day) in issues.items():
            balls = {"front": [1, 3, 7, 10, 20, 31], "back": [5]} if game == "ssq" \
                else {"front": [2, 5, 11, 19, 30], "back": [4, 12]}
            rows = [{"issue": issue, "draw_date": day, **balls}]
            (sources / f"{game}-verified-history.json").write_bytes(
                canonical({"game": game.upper(), "draws": rows}))
            raw = (game + " official-html").encode()
            (sources / f"{game}-publisher-raw.html").write_bytes(raw)
            receipt["games"][game] = {
                "history_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "new_target_issue": str(int(issue) + 1),
                "source_url": "https://official.example/" + game}
        (sources / "official-ingest-receipt.json").write_bytes(canonical(receipt))
        return sources

    def make_forecast(self, command, **kwargs):
        game = command[command.index("--game") + 1]
        target = command[command.index(f"--{game}-target") + 1]
        output = Path(command[command.index("--output") + 1])
        directory = Path(command[command.index("--freeze-dir") + 1])
        directory.mkdir(parents=True, exist_ok=True)
        tickets = [{"front": [1, 3, 7, 10, 20, 31], "back": [5],
                    "dan2": [1, 3]}] if game == "ssq" else [
                    {"front": [2, 5, 11, 19, 30], "back": [4, 12],
                     "dan2": [2, 5]}]
        report = {"schema": "SSQDLT_V47_UNIFIED_11_V1", "game": game,
                  "target_issue": target, "ticket_count": 11,
                  "validation": {"M2": {str(n): {} for n in range(11)},
                                 "M3": {str(n): {} for n in range(11)}},
                  "proposed_tickets": tickets * 11}
        outer = {"schema": "SSQDLT_V47_UNIFIED_RUN_V1",
                 "games": {game: report}}
        output.write_bytes(canonical(outer))
        (directory / f"{game}-{target}-v47-unified.json").write_bytes(
            canonical({"schema": "SSQDLT_V47_UNIFIED_FROZEN_V1",
                       "created_utc": "2026-11-14T02:00:00+00:00",
                       "source": report}))
        class P:
            returncode = 0
        return P()

    def test_two_genuine_context_receipts_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = self.make_sources(root)
            now = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_forecast) as calls:
                first = record(root, source, 123400, 1, "a"*40, "schedule", now)
                self.assertEqual(first["count"], 1)
                self.assertEqual(len(first["generated"]), 2)
                self.assertEqual(calls.call_count, 2)
            restored = verify(root)
            self.assertEqual(restored["count"], 1)
            with patch("research.supercompute.v47_live_ledger.subprocess.run") as calls:
                second = record(root, source, 123401, 1, "a"*40, "schedule", now)
                self.assertEqual(second["count"], 2)
                self.assertEqual(second["generated"], [])
                self.assertEqual(len(second["pending"]), 2)
                self.assertEqual(calls.call_count, 0)
            self.assertEqual(verify(root)["run_ids"], [123400, 123401])
            with self.assertRaises(ValueError):
                record(root, source, 123401, 1, "a"*40, "schedule", now)
            with self.assertRaises(ValueError):
                record(root, source, 123402, 1, "a"*40, "workflow_dispatch", now)
            entry = next((root / "research/v47_live_ledger/events").glob("*.json"))
            doc = json.loads(entry.read_bytes())
            doc["event_hash"] = "0" * 64
            entry.write_bytes(canonical(doc))
            with self.assertRaises(ValueError):
                verify(root)

    def test_after_nominal_draw_halts_if_publisher_not_updated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = self.make_sources(root)
            after = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run") as calls:
                result = record(root, source, 123499, 1, "b"*40, "schedule", after)
                self.assertEqual(result["generated"], [])
                self.assertEqual(len(result["pending"]), 2)
                self.assertTrue(all(x["reason"] ==
                    "PUBLISHER_STALE_AFTER_NOMINAL_DRAW" for x in result["pending"]))
                calls.assert_not_called()

    def test_nominal_time_for_both_games(self):
        self.assertEqual(next_nominal_draw("2026-11-12", "ssq").date().isoformat(),
                         "2026-11-15")
        self.assertEqual(next_nominal_draw("2026-11-11", "dlt").date().isoformat(),
                         "2026-11-14")


if __name__ == "__main__":
    unittest.main()
