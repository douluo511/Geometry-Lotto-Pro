"""Synthetic red-team Bot lifecycle; no qualified historical or future outcomes."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.harness_v46 import shadow_bot as bot
from research.harness_v46.core import GateError
from research.harness_v46.tests.test_core import fixture

BEFORE = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)


class ShadowBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.receipts = self.folder / "receipts"
        self.receipts.mkdir()
        self.snapshots = {g: fixture(g) for g in ("SSQ", "DLT")}
        self.snapshot_file = self.folder / "snapshots.json"
        self.outcome_file = self.folder / "result.json"
        self.ledger = self.folder / "prediction.sqlite3"
        self.config = self.folder / "bot-config.json"
        self._write_snapshots()
        self._write_config()

    def _write_snapshots(self):
        self.snapshot_file.write_text(
            json.dumps(self.snapshots), encoding="utf-8")

    def _write_config(self, **overrides):
        item = {
            "schema": bot.BOT_SCHEMA,
            "snapshot_bundle": "snapshots.json",
            "database": "prediction.sqlite3",
            "result_bundle": "result.json",
            "receipts_dir": "receipts",
        }
        item.update(overrides)
        self.config.write_text(json.dumps(item), encoding="utf-8")

    def _write_results(self):
        results = {
            g: {
                "lottery": g,
                "issue": self.snapshots[g]["target_issue"],
                "front": list(self.snapshots[g]["draws"][-2]["front"]),
                "back": list(self.snapshots[g]["draws"][-2]["back"]),
                "drawn_at": "2026-10-23T21:05:00+08:00",
            } for g in ("SSQ", "DLT")
        }
        self.outcome_file.write_text(json.dumps(results), encoding="utf-8")
        return results

    def test_forecast_then_repeat_then_postdraw_scoring_keeps_ledger(self):
        first = bot.tick(self.config, observed_at=BEFORE)
        self.assertEqual(first["status"], "SHADOW_FROZEN_WAIT_DRAW")
        self.assertEqual(first["formal_A"], 0)
        self.assertEqual(first["decision"], "NO_EDGE")
        saved_db = self.ledger.read_bytes()
        frozen_file = Path(first["forecast_receipt"]["path"])
        self.assertTrue(frozen_file.is_file())
        self.assertEqual(hashlib.sha256(frozen_file.read_bytes()).hexdigest(),
                         first["forecast_receipt"]["local_sha256"])
        self.assertEqual(bot.tick(self.config, observed_at=BEFORE), first)
        self.assertEqual(self.ledger.read_bytes(), saved_db)
        wait = bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(wait["status"], "SHADOW_FROZEN_WAIT_RESULT")
        self._write_results()
        scored = bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(scored["status"], "SHADOW_SCORE_RECORDED")
        self.assertEqual(scored["source_authenticity"], "NOT_VERIFIED")
        self.assertEqual(scored["outcome_authenticity"], "CALLER_UNVERIFIED")
        self.assertEqual(scored["formal_A"], 0)
        self.assertEqual(bot.tick(self.config, observed_at=AFTER), scored)
        self.assertEqual(self.ledger.read_bytes(), saved_db)
        details = json.loads(Path(scored["score_receipt"]["path"]).read_text())
        self.assertEqual(set(details["shadow_feedback_receipts"]), {"SSQ", "DLT"})
        for game in ("SSQ", "DLT"):
            self.assertEqual(len(details["shadow_feedback_receipts"][game]["models"]), 6)

    def test_missing_predraw_does_not_backfill_after_cutoff(self):
        report = bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(report["status"], "BLOCKED_MISSED_PREDRAW_FREEZE")
        self.assertFalse(self.ledger.exists())
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_early_asof_wait_never_writes_a_prediction(self):
        early = datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc)
        report = bot.tick(self.config, observed_at=early)
        self.assertEqual(report["status"], "WAIT_ASOF")
        self.assertFalse(self.ledger.exists())

    def test_future_outcome_cannot_be_scored_before_draw(self):
        bot.tick(self.config, observed_at=BEFORE)
        self._write_results()
        report = bot.tick(self.config, observed_at=BEFORE)
        self.assertEqual(report["status"], "SHADOW_FROZEN_WAIT_DRAW")
        self.assertEqual(len(list(self.receipts.glob("*-score.json"))), 0)

    def test_wrong_target_result_cannot_create_score_receipt(self):
        bot.tick(self.config, observed_at=BEFORE)
        result = self._write_results()
        result["SSQ"]["issue"] = "29998"
        self.outcome_file.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(GateError, "RESULT_ISSUE_DIFFERS"):
            bot.tick(self.config, observed_at=AFTER)
        self.assertFalse(list(self.receipts.glob("*-score.json")))

    def test_revised_results_never_silently_replace_the_first_receipt(self):
        bot.tick(self.config, observed_at=BEFORE)
        original = self._write_results()
        first = bot.tick(self.config, observed_at=AFTER)
        stored_score = Path(first["score_receipt"]["path"])
        saved_sha = hashlib.sha256(stored_score.read_bytes()).hexdigest()
        # Change the result while retaining its issue and legal ball count.
        swapped = copy.deepcopy(original)
        swapped["SSQ"]["front"] = [1, 2, 3, 4, 5, 6]
        self.outcome_file.write_text(json.dumps(swapped), encoding="utf-8")
        with self.assertRaisesRegex(GateError, "BOT_RECEIPT_ALREADY_EXISTS_DIFFERENT_CONTENT"):
            bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(hashlib.sha256(stored_score.read_bytes()).hexdigest(), saved_sha)

    def test_same_ledger_supports_a_second_future_target(self):
        first = bot.tick(self.config, observed_at=BEFORE)
        self.snapshots["SSQ"]["target_issue"] = "30000"
        self.snapshots["DLT"]["target_issue"] = "30000"
        self._write_snapshots()
        second = bot.tick(self.config, observed_at=BEFORE)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(second["status"], "SHADOW_FROZEN_WAIT_DRAW")
        import sqlite3
        conn = sqlite3.connect(self.ledger)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 24)
        conn.close()
        self.assertEqual(len(list(self.receipts.glob("*-forecast.json"))), 2)

    def test_two_distinct_future_targets_accumulate_only_original_frozen_d2(self):
        bot.tick(self.config, observed_at=BEFORE)
        self._write_results()
        first = bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(first["cumulative_run_count"], 1)
        self.snapshots["SSQ"]["target_issue"] = "30000"
        self.snapshots["DLT"]["target_issue"] = "30000"
        self._write_snapshots()
        second_freeze = bot.tick(self.config, observed_at=BEFORE)
        self.assertEqual(second_freeze["status"], "SHADOW_FROZEN_WAIT_DRAW")
        self._write_results()
        second = bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(second["cumulative_run_count"], 2)
        summary = json.loads(Path(second["cumulative_receipt"]["path"]).read_text())
        self.assertEqual(summary["summary"]["unique_lottery_issue_count"], 4)
        self.assertEqual(summary["summary"]["games"]["SSQ"]["hot60"]["draws"], 2)
        self.assertEqual(summary["summary"]["games"]["DLT"]["random_null"]["draws"], 2)
        self.assertEqual(summary["summary"]["formal_A"], 0)
        self.assertEqual(len(list(self.receipts.glob("*-score.json"))), 2)

    def test_forged_score_receipt_bits_are_rejected_not_counted(self):
        bot.tick(self.config, observed_at=BEFORE)
        self._write_results()
        recorded = bot.tick(self.config, observed_at=AFTER)
        path = Path(recorded["score_receipt"]["path"])
        tampered = json.loads(path.read_text())
        tampered["shadow_feedback_receipts"]["SSQ"]["models"]["hot60"]["D2"] ^= 1
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaisesRegex(GateError, "BOT_RECEIPT_ALREADY_EXISTS_DIFFERENT_CONTENT"):
            bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(len(list(self.receipts.glob("*-cumulative.json"))), 1)

    @unittest.skipUnless(os.name == "posix", "symlink safety probe on POSIX runners")
    def test_receipt_directory_symlink_rejected_before_freezing(self):
        redirected = self.folder / "redirected"
        redirected.mkdir()
        alias = self.folder / "alias"
        alias.symlink_to(redirected, target_is_directory=True)
        self._write_config(receipts_dir="alias")
        with self.assertRaisesRegex(GateError, "BOT_RECEIPTS_DIRECTORY_SYMLINK_FORBIDDEN"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    @unittest.skipUnless(os.name == "posix", "symlink-ancestor probe on POSIX")
    def test_linked_ancestor_receipts_refuses_before_freeze(self):
        external = self.folder / "external-evidence"
        (external / "receipts").mkdir(parents=True)
        alias = self.folder / "evidence-alias"
        alias.symlink_to(external, target_is_directory=True)
        self._write_config(receipts_dir="evidence-alias/receipts")
        with self.assertRaisesRegex(GateError, "BOT_SYMLINK_PATH_COMPONENT_FORBIDDEN"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())
        self.assertEqual(list((external / "receipts").iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "symlink-ancestor probe on POSIX")
    def test_linked_ancestor_database_cannot_redirect_forecast(self):
        external = self.folder / "external-ledger"
        external.mkdir()
        (self.folder / "db-alias").symlink_to(external, target_is_directory=True)
        self._write_config(database="db-alias/prediction.sqlite3")
        with self.assertRaisesRegex(GateError, "BOT_SYMLINK_PATH_COMPONENT_FORBIDDEN"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse((external / "prediction.sqlite3").exists())

    @unittest.skipUnless(os.name == "posix", "symlink-ancestor probe on POSIX")
    def test_linked_ancestor_snapshot_input_cannot_redirect_forecast(self):
        external = self.folder / "external-snapshots"
        external.mkdir()
        (external / "snapshots.json").write_bytes(self.snapshot_file.read_bytes())
        (self.folder / "snapshot-alias").symlink_to(external, target_is_directory=True)
        self._write_config(snapshot_bundle="snapshot-alias/snapshots.json")
        with self.assertRaisesRegex(GateError, "BOT_SYMLINK_PATH_COMPONENT_FORBIDDEN"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    @unittest.skipUnless(os.name == "posix", "symlink-ancestor probe on POSIX")
    def test_linked_config_file_cannot_hide_actual_input_location(self):
        alias = self.folder / "bot-config-alias.json"
        alias.symlink_to(self.config)
        with self.assertRaisesRegex(GateError, "BOT_SYMLINK_PATH_COMPONENT_FORBIDDEN"):
            bot.tick(alias, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    @unittest.skipUnless(os.name == "posix", "symlink-ancestor probe on POSIX")
    def test_linked_ancestor_results_cannot_redirect_postdraw(self):
        bot.tick(self.config, observed_at=BEFORE)
        frozen = self.ledger.read_bytes()
        self._write_results()
        external = self.folder / "external-outcome"
        external.mkdir()
        (external / "result.json").write_bytes(self.outcome_file.read_bytes())
        (self.folder / "results-alias").symlink_to(external, target_is_directory=True)
        self._write_config(result_bundle="results-alias/result.json")
        with self.assertRaisesRegex(GateError, "BOT_SYMLINK_PATH_COMPONENT_FORBIDDEN"):
            bot.tick(self.config, observed_at=AFTER)
        self.assertEqual(self.ledger.read_bytes(), frozen)
        self.assertFalse(list(self.receipts.glob("*-score.json")))

    def test_bad_or_incomplete_config_rejected_without_ledger(self):
        self._write_config(formal_A=1)
        with self.assertRaisesRegex(GateError, "BOT_CONFIG_FIELDS_INVALID"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())
        self._write_config(receipts_dir="no-such-dir")
        with self.assertRaisesRegex(GateError, "BOT_RECEIPTS_DIRECTORY_MISSING"):
            bot.tick(self.config, observed_at=BEFORE)

    def test_naive_local_time_rejected_before_any_io(self):
        with self.assertRaisesRegex(GateError, "BOT_REQUIRES_AWARE_OBSERVATION_TIME"):
            bot.tick(self.config, observed_at=datetime(2026, 10, 20, 8))
        self.assertFalse(self.ledger.exists())

    def test_duplicate_config_keys_block_before_freeze(self):
        # Python's normal json.loads silently keeps the last duplicate.
        self.config.write_text(
            '{"schema":"V47-SHADOW-BOT-CONFIG-1",'
            '"snapshot_bundle":"snapshots.json",'
            '"database":"unexpected.sqlite3","database":"prediction.sqlite3",'
            '"result_bundle":"result.json","receipts_dir":"receipts"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(GateError, "BOT_JSON_DUPLICATE_KEY"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())
        self.assertFalse((self.folder / "unexpected.sqlite3").exists())

    def test_duplicate_nested_target_issue_blocks_forecast(self):
        raw = self.snapshot_file.read_text(encoding="utf-8")
        needle = '"target_issue": "29999"'
        self.assertIn(needle, raw)
        raw = raw.replace(needle, '"target_issue": "29998", ' + needle, 1)
        self.snapshot_file.write_text(raw, encoding="utf-8")
        with self.assertRaisesRegex(GateError, "BOT_JSON_DUPLICATE_KEY"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    def test_duplicate_nested_outcome_ball_list_blocks_scoring(self):
        bot.tick(self.config, observed_at=BEFORE)
        self._write_results()
        before = self.ledger.read_bytes()
        raw = self.outcome_file.read_text(encoding="utf-8")
        self.assertIn('"front": ', raw)
        raw = raw.replace('"front": ', '"front": [1, 2, 3, 4, 5, 6], "front": ', 1)
        self.outcome_file.write_text(raw, encoding="utf-8")
        with self.assertRaisesRegex(GateError, "BOT_JSON_DUPLICATE_KEY"):
            bot.tick(self.config, observed_at=AFTER)
        self.assertFalse(list(self.receipts.glob("*-score.json")))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_nonfinite_snapshot_number_is_invalid_evidence(self):
        self.snapshots["SSQ"]["provenance"]["nonfinite"] = float("nan")
        self._write_snapshots()
        with self.assertRaisesRegex(GateError, "BOT_JSON_NONFINITE_NUMBER"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    def test_oversized_snapshot_file_blocked_without_loading(self):
        with self.snapshot_file.open("wb") as handle:
            handle.truncate(32_000_001)
        with self.assertRaisesRegex(GateError, "BOT_INPUT_JSON_TOO_LARGE"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertFalse(self.ledger.exists())

    def test_existing_corrupt_database_never_reinitialized(self):
        self.ledger.write_bytes(b"pretend official ledger")
        original = self.ledger.read_bytes()
        with self.assertRaisesRegex(GateError, "BOT_EXISTING_LEDGER_CANNOT_BE_INSPECTED"):
            bot.tick(self.config, observed_at=BEFORE)
        self.assertEqual(self.ledger.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
