"""Opt-in unattended local Bot runner: no scheduler installation in CI."""
import os
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ClosedLoopSchedulerTests(unittest.TestCase):
    def test_configured_runner_and_install_script_exist_and_do_not_auto_install(self):
        handler = (ROOT / "invoke_closed_loop.ps1").read_text(encoding="utf-8")
        install = (ROOT / "windows_closed_loop_tasks.ps1").read_text(encoding="utf-8")
        self.assertIn("research.harness_v46.closed_loop", handler)
        self.assertIn("--workspace", handler)
        self.assertIn("--snapshot-bundle", handler)
        self.assertIn("closed_loop", handler)
        self.assertIn("exit_code=", handler)
        self.assertIn("SSQDLT-V47-CLOSED-LOOP-SHADOW", install)
        self.assertIn("[switch]$Install", install)
        self.assertIn("if (-not $Install)", install)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", install)
        self.assertIn("-RepetitionInterval", install)
        self.assertIn("IgnoreNew", install)
        self.assertIn("TASK_ALREADY_EXISTS_REFUSING_OVERWRITE", install)
        self.assertNotIn("Register-ScheduledTask -Force", install)
        self.assertNotIn("Register-ScheduledTask -TaskName $TaskName -Force", install)

    def test_bot_invoker_supports_independent_ssq_and_dlt_game_snapshots(self):
        script = (ROOT / "invoke_closed_loop.ps1").read_text(encoding="utf-8")
        self.assertIn("ssq_snapshot_bundle", script)
        self.assertIn("dlt_snapshot_bundle", script)
        self.assertIn("--game-snapshot", script)
        self.assertIn("--game", script)
        self.assertIn("foreach", script)
        self.assertIn("SSQ", script)
        self.assertIn("DLT", script)


    def test_bot_operational_mode_is_opt_in_and_uses_bounded_worker_cli(self):
        script = (ROOT / "invoke_closed_loop.ps1").read_text(encoding="utf-8")
        self.assertIn("operational_tick", script)
        self.assertIn("--operational-tick", script)
        self.assertIn("--intake-timeout-seconds", script)
        self.assertIn("CLOSED_LOOP_OPERATIONAL_MODE_INPUTS_CONFLICT", script)

    @unittest.skipUnless(os.name == "nt", "Actual opt-in operational invocation requires Windows")
    def test_real_windows_optin_operational_mode_persists_two_attempts(self):
        import sys
        import sqlite3
        from contextlib import closing
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("Windows PowerShell unavailable")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workspace = base / "persist"
            config = base / "config.json"
            config.write_text(json.dumps({
                "repository_root": str(ROOT.parents[1]),
                "python_exe": sys.executable,
                "workspace": str(workspace),
                "log_path": str(base / "bot.log"),
                "operational_tick": True,
                "intake_timeout_seconds": 0.01,
            }), encoding="utf-8")
            cmd = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                   "Bypass", "-File", str(ROOT / "invoke_closed_loop.ps1"),
                   "-ConfigFile", str(config)]
            for count in (1, 2):
                run = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
                with closing(sqlite3.connect(workspace / "ledger.sqlite3")) as conn:
                    events = conn.execute(
                        "SELECT tick_id,event_type FROM operational_events ORDER BY event_id"
                    ).fetchall()
                    self.assertEqual(len(events), count * 4)
                    self.assertEqual(len({e[0] for e in events}), count)
                    self.assertFalse(conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='game_predictions'").fetchone())
            log = (base / "bot.log").read_text(encoding="utf-8-sig")
            self.assertIn("SSQ-DLT-OPERATIONAL", log)
            self.assertIn("NO_EDGE", log)
            manifests = list((workspace / "operational_intake").glob("*/*/intake.json"))
            self.assertEqual(len(manifests), 4)
            for path in manifests:
                body = json.loads(path.read_text(encoding="utf-8"))
                game = path.parent.name
                self.assertEqual(
                    body["games"][game]["status"], "WORKER_OUTPUT_QUARANTINED")


    @unittest.skipUnless(os.name == "nt", "Actual PowerShell Bot tick Windows only")
    def test_bot_actual_powershell_tick_freezes_two_game_issues_without_shared_run(self):
        from datetime import datetime, timedelta, timezone
        from contextlib import closing
        from research.harness_v46.tests.test_core import fixture
        import sqlite3
        import sys
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("PowerShell unavailable")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = datetime.now(timezone.utc)
            paths = {}
            for game in ("SSQ", "DLT"):
                snap = fixture(game)
                snap["as_of"] = (now - timedelta(minutes=10)).isoformat()
                snap["sales_cutoff"] = (now + timedelta(hours=3)).isoformat()
                snap["target_draw_at"] = (now + timedelta(hours=4)).isoformat()
                f = base / (game + ".json")
                f.write_text(json.dumps(snap), encoding="utf-8")
                paths[game] = str(f)
            workspace = base / "persist"
            cfg = base / "config.json"
            cfg.write_text(json.dumps({
                "repository_root": str(ROOT.parents[1]),
                "python_exe": sys.executable,
                "workspace": str(workspace), "log_path": str(base / "bot.log"),
                "ssq_snapshot_bundle": paths["SSQ"],
                "dlt_snapshot_bundle": paths["DLT"],
            }), encoding="utf-8")
            command = [exe, "-NoProfile", "-NonInteractive",
                       "-ExecutionPolicy", "Bypass", "-File",
                       str(ROOT / "invoke_closed_loop.ps1"),
                       "-ConfigFile", str(cfg)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=70)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            with closing(sqlite3.connect(workspace / "ledger.sqlite3")) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM game_predictions").fetchone()[0], 12)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM game_runs").fetchone()[0], 2)
            log = (base / "bot.log").read_text(encoding="utf-8-sig")
            self.assertIn("SSQ", log)
            self.assertIn("DLT", log)
            again = subprocess.run(command, capture_output=True, text=True, timeout=70)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            with closing(sqlite3.connect(workspace / "ledger.sqlite3")) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM game_predictions").fetchone()[0], 12)

    @unittest.skipUnless(os.name == "nt", "Actual Windows Bot fail-closed tick only")
    def test_bot_source_blocked_ssq_still_processes_dlt_without_fake_ssq(self):
        import sqlite3
        import sys
        from contextlib import closing
        from datetime import datetime, timedelta, timezone
        from research.harness_v46.tests.test_core import fixture
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("PowerShell unavailable")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            now = datetime.now(timezone.utc)
            snap = fixture("DLT")
            snap["as_of"] = (now - timedelta(minutes=10)).isoformat()
            snap["sales_cutoff"] = (now + timedelta(hours=3)).isoformat()
            snap["target_draw_at"] = (now + timedelta(hours=4)).isoformat()
            source = base / "dlt.json"
            source.write_text(json.dumps(snap), encoding="utf-8")
            workspace = base / "state"
            config = base / "bot.json"
            config.write_text(json.dumps({
                "repository_root": str(ROOT.parents[1]),
                "python_exe": sys.executable,
                "workspace": str(workspace),
                "log_path": str(base / "bot.log"),
                "dlt_snapshot_bundle": str(source),
                "ssq_snapshot_bundle": None
            }), encoding="utf-8")
            command = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                       "Bypass", "-File", str(ROOT / "invoke_closed_loop.ps1"),
                       "-ConfigFile", str(config)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=70)
            self.assertNotEqual(run.returncode, 0, "SSQ source absence MUST not claim total success")
            with closing(sqlite3.connect(workspace / "ledger.sqlite3")) as c:
                self.assertEqual(c.execute("SELECT count(*) FROM game_predictions").fetchone()[0], 6)
                self.assertEqual([x[0] for x in c.execute("SELECT lottery FROM game_runs")], ["DLT"])
            log = (base / "bot.log").read_text(encoding="utf-8-sig")
            self.assertIn("GAME_RUN_NOT_REGISTERED", log)
            self.assertIn("[DLT][exit_code=0]", log)
            self.assertIn("NO_EDGE", log)

    @unittest.skipUnless(os.name == "nt", "Windows dry run only")
    def test_windows_real_dry_run_does_not_register_task(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell installed")
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "bot-config.json"
            cfg_path.write_text(json.dumps({
                "repository_root": str(ROOT.parents[1]),
                "python_exe": "python.exe",
                "workspace": str(Path(td) / "workspace"),
                "log_path": str(Path(td) / "bot.log"),
                "snapshot_bundle": None,
                "research_history_bundle": None
            }), encoding="utf-8")
            out = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "windows_closed_loop_tasks.ps1"),
                 "-ConfigFile", str(cfg_path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
            self.assertIn("NOT_INSTALLED", out.stdout)
            self.assertFalse((Path(td) / "workspace" / "ledger.sqlite3").exists())

    @unittest.skipUnless(os.name == "nt", "PowerShell AST on Windows CI only")
    def test_windows_powershell_ast_syntax(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("No Windows PowerShell installed")
        for name in ("windows_closed_loop_tasks.ps1", "invoke_closed_loop.ps1"):
            file = ROOT / name
            code = ("$tokens=$null;$errors=$null;"
                    "[void][System.Management.Automation.Language.Parser]::ParseFile("
                    "'" + str(file).replace("'", "''") + "',[ref]$tokens,[ref]$errors);"
                    "if($errors.Count -gt 0){$errors|Out-String|Write-Error;exit 1}")
            run = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", code],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)


if __name__ == "__main__":
    unittest.main()
