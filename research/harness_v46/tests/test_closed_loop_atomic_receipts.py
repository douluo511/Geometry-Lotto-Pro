"""Adversarial persistence checks for the EXISTING single V4.7 closed-loop receipt writer.

Synthetic only. No official draw claims or host power-loss success claim.
"""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from research.harness_v46 import closed_loop
from research.harness_v46.core import GateError


class ReceiptAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.receipts = root / "receipts"
        self.receipts.mkdir()
        self.path = self.receipts / ("V47-" + "a" * 32 + ".json")
        self.record = {"schema": "synthetic-scored-receipt", "formal_A": 0,
                       "decision": "NO_EDGE", "value": "complete"}

    def test_failed_fsync_never_publishes_a_partial_final_receipt(self):
        # Power-loss stand-in: an OS flush failure between write and publication.
        # The old direct xb writer left a file at the final path.
        with patch.object(closed_loop.os, "fsync", side_effect=OSError("injected flush failure")):
            with self.assertRaisesRegex(OSError, "injected flush failure"):
                closed_loop._write_once(self.path, self.record)
        self.assertFalse(self.path.exists(), "unflushed bytes cannot be a valid receipt")
        self.assertEqual(list(self.receipts.iterdir()), [], "staging file must not leak after normal exception")
        # A later Bot retry must recover without changing the frozen prediction.
        closed_loop._write_once(self.path, self.record)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.record)

    def test_existing_receipt_conflict_is_never_overwritten(self):
        closed_loop._write_once(self.path, self.record)
        original = self.path.read_bytes()
        with self.assertRaisesRegex(GateError, "SCORE_RECEIPT_CONFLICT"):
            closed_loop._write_once(self.path, {**self.record, "value": "different"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.receipts.iterdir()), [self.path])

    def test_concurrent_different_receipts_cannot_publish_a_torn_or_replaced_file(self):
        a = {**self.record, "value": "A" * 400000}
        b = {**self.record, "value": "B" * 400000}
        values = [a, b, a, b, a, b]
        def attempt(obj):
            try:
                closed_loop._write_once(self.path, obj)
                return "accepted"
            except GateError as exc:
                self.assertIn("SCORE_RECEIPT_CONFLICT", str(exc))
                return "conflict"
        with ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(attempt, values))
        self.assertIn("accepted", statuses)
        self.assertEqual(sum(x == "accepted" for x in statuses) +
                         sum(x == "conflict" for x in statuses), len(values))
        self.assertIn(json.loads(self.path.read_text(encoding="utf-8")), (a, b))
        self.assertEqual(list(self.receipts.iterdir()), [self.path])


    def test_integrated_failed_receipt_flush_keeps_frozen_run_and_allows_rescore(self):
        import hashlib
        from datetime import datetime, timezone
        from research.harness_v46.tests.test_core import fixture
        root = Path(self.tmp.name) / "integrated"
        frozen_at = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
        after_draw = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
        snapshots = {g: fixture(g) for g in ("SSQ", "DLT")}
        first = closed_loop.advance_workspace(root, snapshots=snapshots,
                                              observed_at=frozen_at)
        run_id = first["run_ids"][0]
        ledger = root / "ledger.sqlite3"
        original_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()
        outcome = {
            g: {"lottery": g, "issue": "29999",
                "front": list(snapshots[g]["draws"][-2]["front"]),
                "back": list(snapshots[g]["draws"][-2]["back"]),
                "drawn_at": "2026-10-23T21:05:00+08:00"}
            for g in ("SSQ", "DLT")
        }
        folder = root / "outcomes"
        folder.mkdir(exist_ok=True)
        (folder / (run_id + ".json")).write_text(json.dumps(outcome), encoding="utf-8")
        receipt = root / "receipts" / (run_id + ".json")
        with patch.object(closed_loop.os, "fsync", side_effect=OSError("injected flush failure")):
            with self.assertRaisesRegex(OSError, "injected flush failure"):
                closed_loop.advance_workspace(root, observed_at=after_draw)
        self.assertFalse(receipt.exists())
        self.assertEqual(hashlib.sha256(ledger.read_bytes()).hexdigest(), original_sha)
        result = closed_loop.advance_workspace(root, observed_at=after_draw)
        self.assertEqual(result["status"], "STUDY_SHADOW_READY")
        self.assertEqual(result["study"]["draws_by_game"], {"SSQ": 1, "DLT": 1})
        self.assertEqual(result["study"]["statistical_analysis"]["family_size"], 12)
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")
        self.assertTrue(receipt.exists())
        self.assertEqual(hashlib.sha256(ledger.read_bytes()).hexdigest(), original_sha)

    def test_two_concurrent_replays_publish_identical_receipt_once(self):
        from datetime import datetime, timezone
        from research.harness_v46.tests.test_core import fixture
        root = Path(self.tmp.name) / "concurrent"
        before = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
        after = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
        snapshots = {g: fixture(g) for g in ("SSQ", "DLT")}
        run_id = closed_loop.advance_workspace(root, snapshots=snapshots, observed_at=before)["run_ids"][0]
        outcome = {g: {"lottery": g, "issue": "29999",
                       "front": list(snapshots[g]["draws"][-2]["front"]),
                       "back": list(snapshots[g]["draws"][-2]["back"]),
                       "drawn_at": "2026-10-23T21:05:00+08:00"}
                   for g in ("SSQ", "DLT")}
        path = root / "outcomes"
        path.mkdir()
        (path / (run_id + ".json")).write_text(json.dumps(outcome), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda _: closed_loop.advance_workspace(root, observed_at=after), range(2)
            ))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["status"], "STUDY_SHADOW_READY")
        self.assertEqual(len(list((root / "receipts").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
