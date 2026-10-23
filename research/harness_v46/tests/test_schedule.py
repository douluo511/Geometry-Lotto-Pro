"""JST policy/transaction tests; do not mistake runner CI for host startup evidence."""
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from research.harness_v46 import core, convergence as cv
from research.harness_v46 import schedule as sch
from research.harness_v46.tests.test_core import fixture


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.snaps = {game: fixture(game) for game in ("SSQ", "DLT")}
        self.now = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc)

    def test_exact_jst_window(self):
        self.assertTrue(sch.due_in_jst(self.now))
        self.assertFalse(sch.due_in_jst(self.now - timedelta(minutes=1)))
        self.assertFalse(sch.due_in_jst(self.now + timedelta(days=1)))
        self.assertTrue(sch.due_in_jst(self.now + timedelta(days=3)))
        with self.assertRaisesRegex(core.GateError, "AWARE_CLOCK"):
            sch.due_in_jst(datetime(2026, 10, 21, 7, 0))

    def test_one_transaction_and_halfhour_retry(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "evidence.sqlite3"
            first = sch.scheduled_once(self.snaps, db_path, self.now)
            retry = sch.scheduled_once(self.snaps, db_path, self.now + timedelta(minutes=30))
            self.assertEqual(first["run_id"], retry["run_id"])
            self.assertEqual(first["status"], "SHADOW_ONLY")
            self.assertEqual(first["external_tsa"], "NOT_VERIFIED")
            self.assertEqual(len(first["manifest_sha256"]), 64)
            db = sqlite3.connect(db_path)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM run_manifests").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workflow_events").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shadow_trace_events").fetchone()[0], 12)
            for item in db.execute("SELECT payload FROM workflow_events"):
                event = __import__("json").loads(item[0])
                self.assertEqual(event["stage"], "SYNC")
                self.assertEqual(event["evidence"]["gate_status"], "BLOCKED")
                self.assertEqual(event["evidence"]["evidence_class"], "SHADOW")
            self.assertEqual(first["gate_status"], "BLOCKED")
            self.assertEqual(first["shadow_trace_status"], "UNVERIFIED_EXECUTION_ONLY")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scheduled_target_guard").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tsa_claims").fetchone()[0], 2)
            db.close()

    def test_target_cannot_be_reissued_from_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "evidence.sqlite3"
            sch.scheduled_once(self.snaps, path, self.now)
            altered = {k: dict(v) for k, v in self.snaps.items()}
            altered["SSQ"]["provenance"] = {"status": "other-snapshot"}
            with self.assertRaisesRegex(core.GateError, "TARGET_ALREADY_FROZEN"):
                sch.scheduled_once(altered, path, self.now + timedelta(minutes=30))
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scheduled_target_guard").fetchone()[0], 2)
            db.close()

    def test_late_recovery_does_not_backfill(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "evidence.sqlite3"
            with self.assertRaisesRegex(core.GateError, "NO_RETROACTIVE"):
                sch.scheduled_once(self.snaps, path,
                                   datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc))
            self.assertFalse(path.exists())

    def test_numeric_issue_alias_cannot_create_another_frozen_run(self):
        cases = ((g, original, alias) for g in core.RULES
                 for original, alias in (("29999", "029999"), ("029999", "29999"),
                                         ("29999", "\uff12\uff19\uff19\uff19\uff19")))
        for game, original, alias in cases:
            with self.subTest(game=game, original=original, alias=alias), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "evidence.sqlite3"
                first = {g: {**s, "target_issue": original} for g, s in self.snaps.items()}
                altered = {g: {**s, "target_issue": alias if g == game else "30000"}
                           for g, s in self.snaps.items()}
                sch.scheduled_once(first, path, self.now)
                db = sqlite3.connect(path)
                before = list(db.iterdump())
                db.close()
                with self.assertRaisesRegex(core.GateError, "TARGET_ALREADY_FROZEN"):
                    sch.scheduled_once(altered, path, self.now + timedelta(minutes=30))
                db = sqlite3.connect(path)
                self.assertEqual(list(db.iterdump()), before)
                db.close()

    def test_sql_fault_rolls_back_both_games(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "evidence.sqlite3"
            conn = sqlite3.connect(path)
            core.init_ledger(conn)
            conn.execute(
                "CREATE TRIGGER simulate_dlt_disk_failure BEFORE INSERT ON predictions "
                "WHEN NEW.lottery='DLT' BEGIN SELECT RAISE(ABORT, 'injected_failure'); END;")
            conn.commit()
            conn.close()
            with self.assertRaises(sqlite3.DatabaseError):
                sch.scheduled_once(self.snaps, path, self.now)
            conn = sqlite3.connect(path)
            for table in ("run_manifests", "predictions", "audit_events", "scheduled_target_guard",
                          "workflow_events", "shadow_trace_events", "tsa_claims", "run_context"):
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
            conn.close()

    def test_windows_installer_is_non_destructive_and_v47_labelled(self):
        folder = Path(sch.__file__).parent
        installer = (folder / "windows_shadow_tasks.ps1").read_text(encoding="utf-8")
        handler = (folder / "invoke_v46_shadow.ps1").read_text(encoding="utf-8")
        self.assertIn("$TaskName = 'SSQDLT-V47-SHADOW'", installer)
        self.assertIn("TASK_ALREADY_EXISTS_REFUSING_OVERWRITE", installer)
        self.assertNotRegex(installer, r"(?m)^Register-ScheduledTask.*-Force")
        self.assertNotIn("SSQDLT-V46-SHADOW", installer)
        self.assertIn("V4.7 SHADOW-only as-of guarded runner", installer)
        self.assertIn("V47-SHADOW actual handler invocation", handler)
        self.assertIn("V47_SHADOW_COMPENSATION_RUN_FAILED", handler)
        self.assertNotIn("V46-SHADOW", handler)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser only")
    def test_windows_powershell_syntax(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 unavailable")
        folder = Path(sch.__file__).parent
        for name in ("windows_shadow_tasks.ps1", "invoke_v46_shadow.ps1"):
            path = folder / name
            script = (
                "$tokens=$null;$errors=$null;"
                "[void][System.Management.Automation.Language.Parser]::ParseFile("
                "'" + str(path).replace("'", "''") + "',[ref]$tokens,[ref]$errors);"
                "if($errors.Count -gt 0){$errors|Out-String|Write-Error;exit 1}"
            )
            r = subprocess.run([pwsh, "-NoProfile", "-Command", script],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
