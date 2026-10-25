"""Real files and SQLite; doubles stop only at external process boundaries.

Each test names the production regression it catches. Feature discovery is an
assertion inside each test, so the tests-only RED has no collection import error.
"""
from contextlib import closing
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from research.harness_v46 import closed_loop, core

ROOT = Path(__file__).resolve().parents[3]
OWNER_SID = "S-1-5-21-111111111-222222222-333333333-1001"
OTHER_SID = "S-1-5-21-111111111-222222222-333333333-1002"
CLI_RESULT = {
    "schema": "V47-OPERATIONAL-TICK-SHADOW-1",
    "tick_id": "V47T-0123456789abcdef0123456789abcdef",
    "games": {
        "SSQ": {"target_gate": "BLOCKED_NO_EXPLICIT_SNAPSHOT",
                "source_status": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
                "scoring": {"status": "BLOCKED", "reason": "NO_FROZEN_ROSTER"}},
        "DLT": {"target_gate": "BLOCKED_NO_EXPLICIT_SNAPSHOT",
                "source_status": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
                "scoring": {"status": "BLOCKED", "reason": "NO_FROZEN_ROSTER"}}},
    "operational_attempt_count": 1, "formal_A": 0, "decision": "NO_EDGE",
    "formal_future_denominator": "NOT_VERIFIED"}
CLI_STDOUT = (json.dumps(CLI_RESULT, sort_keys=True) + "\n").encode("utf-8")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v47-desktop-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.workspace = self.base / "existing SHADOW workspace"
        self.workspace.mkdir()
        self.logdir = self.base / "logs"
        self.logdir.mkdir()
        self.config = self.base / "bot config.json"
        self.cfg = {"repository_root": str(ROOT), "python_exe": sys.executable,
                    "workspace": str(self.workspace),
                    "log_path": str(self.logdir / "bot.log"),
                    "operational_tick": True, "intake_timeout_seconds": 37.5}
        self.save_config()

    def load(self):
        name = "research.harness_v46.desktop"
        self.assertIsNotNone(importlib.util.find_spec(name),
                             "missing V4.7 desktop/controller implementation")
        return importlib.import_module(name)

    def save_config(self):
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")

    def controller(self, **kwargs):
        return self.load().DesktopController(self.config, **kwargs)

    def tree(self):
        return {str(p.relative_to(self.base)): p.read_bytes()
                for p in self.base.rglob("*") if p.is_file()}

    def journal(self, *, unfinished=False):
        """Legal fixtures independently canonicalized and hashed, no collector."""
        ledger = self.workspace / "ledger.sqlite3"
        with closing(sqlite3.connect(ledger)) as conn, conn:
            conn.executescript(closed_loop.OPERATIONAL_SCHEMA)
            for serial in (1, 2):
                tick = "V47T-" + str(serial) * 32
                games = {
                    "SSQ": {"target_gate": "BLOCKED_NO_EXPLICIT_SNAPSHOT",
                            "source_status": "BLOCKED", "source_errors": {"ssq": "offline"},
                            "scoring": {"status": "BLOCKED", "reason": "NO_FROZEN_ROSTER"}},
                    "DLT": {"target_gate": "BLOCKED_NO_EXPLICIT_SNAPSHOT",
                            "source_status": "BLOCKED", "source_errors": {"dlt": "offline"},
                            "scoring": {"status": "PASS", "completed_issues": ["26120"],
                                        "details": {"model": "EWMA", "D2": 0}}}}
                events = [("STARTED", None, {"tick_id": tick})]
                if serial == 1 or not unfinished:
                    events += [("GAME_RESULT", game,
                                {"tick_id": tick, "game": game, "state": state})
                               for game, state in games.items()]
                    result = {"schema": "V47-OPERATIONAL-TICK-SHADOW-1",
                              "tick_id": tick, "games": games,
                              "operational_attempt_count": serial,
                              "formal_A": 0, "decision": "NO_EDGE",
                              "formal_future_denominator": "NOT_VERIFIED"}
                    events.append(("FINISHED", None, {"tick_id": tick, "result": result}))
                for kind, game, payload in events:
                    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
                    conn.execute("INSERT INTO operational_events "
                                 "(tick_id,event_type,lottery,event_payload,event_sha256) "
                                 "VALUES(?,?,?,?,?)", (tick, kind, game, raw,
                                     hashlib.sha256(raw.encode("utf-8")).hexdigest()))
        return ledger

    def assert_receipt(self, result, stdout, stderr):
        folder = Path(result["receipt_dir"])
        self.assertTrue(folder.is_relative_to(self.workspace))
        self.assertEqual((folder / "stdout.bin").read_bytes(), stdout)
        self.assertEqual((folder / "stderr.bin").read_bytes(), stderr)
        saved = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["command"], result["command"])
        self.assertTrue(saved["started_at"])
        self.assertTrue(saved["finished_at"])
        self.assertEqual(saved["returncode"], result["returncode"])
        return saved

    def boundary(self, calls, *, stdout=CLI_STDOUT, stderr=b"", code=0, timeout=False):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if timeout:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"],
                                                output=stdout, stderr=stderr)
            return subprocess.CompletedProcess(command, code, stdout, stderr)
        return run

    def test_refresh_missing_ledger_creates_no_database_or_receipt(self):
        controller = self.controller()
        before = self.tree()
        with patch("subprocess.run", side_effect=AssertionError("refresh launched process")):
            result = controller.read_status()
        self.assertEqual(result["status"], "MISSING")
        self.assertIsNone(result["latest_complete_tick"])
        self.assertEqual(result["formal_future_denominator"], "NOT_VERIFIED")
        self.assertEqual(self.tree(), before)

    def test_refresh_reads_latest_complete_result_without_mutating_real_journal(self):
        self.load()
        self.journal()
        before = self.tree()
        result = self.controller().read_status()
        latest = result["latest_complete_tick"]
        self.assertEqual(latest["tick_id"], "V47T-" + "2" * 32)
        self.assertEqual(latest["games"]["DLT"]["scoring"]["details"],
                         {"model": "EWMA", "D2": 0})
        self.assertEqual(latest["games"]["SSQ"]["source_errors"], {"ssq": "offline"})
        self.assertEqual(result["operational_attempt_count"], 2)
        self.assertEqual(result["formal_future_denominator"], "NOT_VERIFIED")
        self.assertEqual((result["formal_A"], result["decision"]), (0, "NO_EDGE"))
        self.assertEqual(self.tree(), before)

    def test_unfinished_attempt_never_replaces_complete_tick_or_invents_game_pair(self):
        self.load()
        self.journal(unfinished=True)
        before = self.tree()
        result = self.controller().read_status()
        self.assertEqual(result["latest_complete_tick"]["tick_id"], "V47T-" + "1" * 32)
        self.assertEqual(result["unfinished_tick_ids"], ["V47T-" + "2" * 32])
        self.assertEqual(result["operational_attempt_count"], 2)
        self.assertEqual(self.tree(), before)

    def test_tampered_journal_is_blocked_instead_of_presented_as_latest_success(self):
        self.load()
        ledger = self.journal()
        with closing(sqlite3.connect(ledger)) as conn, conn:
            conn.execute("DROP TRIGGER protect_operational_events_update")
            conn.execute("UPDATE operational_events SET event_payload='{}' WHERE event_id=1")
        before = self.tree()
        result = self.controller().read_status()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["latest_complete_tick"])
        self.assertIn("OPERATIONAL_EVENT", result["error"])
        self.assertEqual(self.tree(), before)

    def test_non_sqlite_ledger_remains_visible_as_read_failure(self):
        self.load()
        (self.workspace / "ledger.sqlite3").write_bytes(b"invalid sqlite bytes")
        before = self.tree()
        result = self.controller().read_status()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["error"])
        self.assertEqual(self.tree(), before)

    def test_refresh_refuses_clean_wal_database_without_creating_sidecars(self):
        self.load()
        ledger = self.journal()
        with closing(sqlite3.connect(ledger)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        self.assertEqual(ledger.read_bytes()[18:20], b"\x02\x02")
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["ledger.sqlite3"])
        before = self.tree()
        result = self.controller().read_status()
        self.assertEqual(self.tree(), before, "read-only refresh created WAL sidecars")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("WAL", result["error"])
        self.assertIsNone(result["latest_complete_tick"])
        self.assertEqual(result["operational_attempt_count"], 0)

    def test_refresh_refuses_live_wal_without_reporting_a_stale_complete_tick(self):
        self.load()
        ledger = self.journal()
        with closing(sqlite3.connect(ledger)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE pending_writer_data(value)")
            writer.commit()
            self.assertTrue(Path(str(ledger) + "-wal").exists())
            before = self.tree()
            result = self.controller().read_status()
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("WAL", result["error"])
            self.assertIsNone(result["latest_complete_tick"])
            self.assertEqual(result["operational_attempt_count"], 0)
            self.assertEqual(self.tree(), before)

    def test_only_exact_boolean_operational_mode_is_accepted(self):
        self.load()
        for value in (False, 1, "true", None):
            with self.subTest(value=value):
                self.cfg["operational_tick"] = value
                self.save_config()
                with self.assertRaises(core.GateError):
                    self.controller()

    def test_old_bundle_presence_cannot_silently_select_another_forecaster(self):
        self.load()
        for key in ("snapshot_bundle", "research_history_bundle", "ssq_snapshot_bundle",
                    "dlt_snapshot_bundle"):
            for value in ("old-mode.json", None, ""):
                with self.subTest(key=key, value=value):
                    self.cfg[key] = value
                    self.save_config()
                    with self.assertRaises(core.GateError):
                        self.controller()
            del self.cfg[key]

    def test_declared_game_path_must_be_nonempty_existing_file(self):
        self.load()
        for key in ("ssq_snapshot_path", "dlt_snapshot_path"):
            for value in (None, "", "  ", 7, str(self.base / "missing.json"), str(self.base)):
                with self.subTest(key=key, value=value):
                    self.cfg[key] = value
                    self.save_config()
                    with self.assertRaises(core.GateError):
                        self.controller()
            del self.cfg[key]

    def test_config_duplicate_keys_and_nonfinite_values_use_strict_reader(self):
        self.load()
        for raw in ('{"operational_tick":true,"operational_tick":false}',
                    '{"intake_timeout_seconds":NaN}'):
            with self.subTest(raw=raw):
                self.config.write_text(raw, encoding="utf-8")
                with self.assertRaises(core.GateError):
                    self.controller()

    def test_required_paths_and_existing_log_parent_checked_before_side_effects(self):
        self.load()
        for key, value in (("repository_root", str(self.base)),
                           ("python_exe", str(self.base / "missing-python.exe")),
                           ("log_path", ""),
                           ("log_path", str(self.base / "missing" / "bot.log")),
                           ("workspace", "")):
            with self.subTest(key=key, value=value):
                original = self.cfg[key]
                self.cfg[key] = value
                self.save_config()
                before = self.tree()
                with self.assertRaises(core.GateError):
                    self.controller()
                self.assertEqual(self.tree(), before)
                self.cfg[key] = original

    def test_worker_timeout_preserves_original_handler_range(self):
        self.load()
        for value in (0, -1, 120.01, True, "bad"):
            with self.subTest(value=value):
                self.cfg["intake_timeout_seconds"] = value
                self.save_config()
                with self.assertRaises(core.GateError):
                    self.controller()

    def test_lexical_parent_traversal_is_rejected_before_resolving_or_receipting(self):
        desktop = self.load()
        subdir = self.base / "subdir"
        subdir.mkdir()
        snapshot = self.base / "snapshot.json"
        snapshot.write_text("{}", encoding="utf-8")
        for field, raw in (
                ("config_file", subdir / ".." / self.config.name),
                ("workspace", subdir / ".." / self.workspace.name),
                ("ssq_snapshot_path", subdir / ".." / snapshot.name)):
            with self.subTest(field=field):
                original = self.cfg.copy()
                if field != "config_file":
                    self.cfg[field] = str(raw)
                    self.save_config()
                before = self.tree()
                with patch("subprocess.run", side_effect=AssertionError("invalid path launched process")):
                    with self.assertRaises(core.GateError):
                        desktop.DesktopController(raw if field == "config_file" else self.config)
                self.assertEqual(self.tree(), before)
                self.cfg = original
                self.save_config()

    def test_real_symlink_inputs_are_rejected_before_resolving_or_receipting(self):
        desktop = self.load()
        snapshot = self.base / "snapshot.json"
        snapshot.write_text("{}", encoding="utf-8")
        links = {"config_file": self.base / "config-link.json",
                 "workspace": self.base / "workspace-link",
                 "ssq_snapshot_path": self.base / "snapshot-link.json"}
        try:
            links["config_file"].symlink_to(self.config)
            links["workspace"].symlink_to(self.workspace, target_is_directory=True)
            links["ssq_snapshot_path"].symlink_to(snapshot)
        except OSError as exc:
            self.skipTest("real symlink creation unavailable: " + str(exc))
        for field, raw in links.items():
            with self.subTest(field=field):
                original = self.cfg.copy()
                if field != "config_file":
                    self.cfg[field] = str(raw)
                    self.save_config()
                before = self.tree()
                with patch("subprocess.run", side_effect=AssertionError("symlink launched process")):
                    with self.assertRaises(core.GateError):
                        desktop.DesktopController(raw if field == "config_file" else self.config)
                self.assertEqual(self.tree(), before)
                self.cfg = original
                self.save_config()

    def test_tick_uses_configured_python_budget_and_only_explicit_game_tokens(self):
        self.load()
        # A distinct existing executable path catches hard-coded sys.executable.
        python = self.base / ("configured-python.exe" if os.name == "nt" else "configured-python")
        python.write_bytes(Path(sys.executable).read_bytes())
        self.cfg["python_exe"] = str(python)
        snapshot = self.base / "SSQ explicit input.json"
        snapshot.write_text("{}", encoding="utf-8")
        self.cfg["ssq_snapshot_path"] = str(snapshot)
        self.save_config()
        calls = []
        with patch("subprocess.run", self.boundary(calls)):
            result = self.controller().run_tick()
        command, options = calls[0]
        self.assertEqual(command, [str(python), "-m", "research.harness_v46.closed_loop",
            "--workspace", str(self.workspace), "--operational-tick",
            "--intake-timeout-seconds", "37.5", "--ssq-snapshot-path", str(snapshot)])
        self.assertEqual(Path(options["cwd"]), ROOT)
        self.assertEqual(options["timeout"], 580)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["result"], CLI_RESULT)
        self.assert_receipt(result, CLI_STDOUT, b"")

    def test_absent_snapshot_never_infers_target_and_default_worker_budget_is_45(self):
        self.load()
        del self.cfg["intake_timeout_seconds"]
        self.save_config()
        calls = []
        with patch("subprocess.run", self.boundary(calls)):
            self.controller().run_tick()
        self.assertEqual(calls[0][0], [sys.executable, "-m",
            "research.harness_v46.closed_loop", "--workspace", str(self.workspace),
            "--operational-tick", "--intake-timeout-seconds", "45"])

    def test_nonzero_exit_preserves_raw_stdout_stderr_and_never_retries(self):
        self.load()
        calls = []
        with patch("subprocess.run", self.boundary(calls, stdout=b"partial\xff\n",
                                                    stderr=b"BLOCKED\xfe\n", code=2)):
            result = self.controller().run_tick()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["returncode"], 2)
        self.assertEqual(len(calls), 1)
        self.assert_receipt(result, b"partial\xff\n", b"BLOCKED\xfe\n")

    def test_timeout_retains_partial_bytes_and_never_retries(self):
        self.load()
        calls = []
        with patch("subprocess.run", self.boundary(calls, stdout=b"started\n",
                                                    stderr=b"waiting\n", timeout=True)):
            result = self.controller().run_tick()
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIsNone(result["returncode"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.assert_receipt(result, b"started\n", b"waiting\n")["timed_out"])

    def test_receipt_binds_process_attempt_to_actual_controller_and_runner_sources(self):
        desktop = self.load()
        calls = []
        with patch("subprocess.run", self.boundary(calls)):
            result = self.controller().run_tick()
        saved = self.assert_receipt(result, CLI_STDOUT, b"")
        self.assertEqual(saved.get("controller_source_sha256"),
                         hashlib.sha256(Path(desktop.__file__).read_bytes()).hexdigest())
        self.assertEqual(saved.get("runner_source_sha256"),
                         hashlib.sha256(Path(closed_loop.__file__).read_bytes()).hexdigest())

    def test_malformed_success_output_and_second_attempt_keep_distinct_receipts(self):
        self.load()
        calls = []
        with patch("subprocess.run", self.boundary(calls, stdout=b"not json\n")):
            first = self.controller().run_tick()
            second = self.controller().run_tick()
        self.assertEqual(first["status"], "FAILED")
        self.assertNotEqual(first["receipt_dir"], second["receipt_dir"])
        self.assert_receipt(first, b"not json\n", b"")
        self.assert_receipt(second, b"not json\n", b"")

    def test_exit_zero_with_invalid_json_identity_or_claims_is_failed_and_retained(self):
        self.load()
        invalid = [{}, [], {**CLI_RESULT, "schema": "LEGACY-DLT-PREDICTOR"},
                   {**CLI_RESULT, "tick_id": "inferred-next-draw"},
                   {**CLI_RESULT, "games": {}},
                   {**CLI_RESULT, "games": {"SSQ": CLI_RESULT["games"]["SSQ"]}},
                   {**CLI_RESULT, "formal_A": 1},
                   {**CLI_RESULT, "decision": "EDGE_PROVEN"}]
        for payload in invalid:
            with self.subTest(payload=payload):
                raw = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
                calls = []
                with patch("subprocess.run", self.boundary(calls, stdout=raw)):
                    result = self.controller().run_tick()
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["returncode"], 0)
                self.assertEqual(len(calls), 1)
                self.assert_receipt(result, raw, b"")

    def identity_boundary(self, calls, name, sid, *, query_error=False):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if Path(command[0]).stem.lower() == "whoami":
                raw = ('"User Name","SID"\r\n"' + name + '","' + sid + '"\r\n').encode()
                return subprocess.CompletedProcess(command, 0, raw, b"")
            if "-Install" in command:
                return subprocess.CompletedProcess(command, 0, b"REGISTERED\r\n", b"")
            return subprocess.CompletedProcess(command, 1 if query_error else 0,
                    b"", b"QUERY_ACCESS_DENIED\r\n" if query_error else b"")
        return run

    def test_actual_sandbox_identity_refused_even_when_config_claims_owner(self):
        self.load()
        self.cfg["username"] = "15928"
        self.save_config()
        calls = []
        with patch("subprocess.run", self.identity_boundary(calls, "host\\CodexSandbox", OWNER_SID)):
            result = self.controller(owner_sid=OWNER_SID).install_task()
        self.assertEqual(result["status"], "REFUSED")
        self.assertTrue(calls)
        self.assertTrue(all(Path(command[0]).stem.lower() == "whoami" for command, _ in calls))
        self.assertNotIn("capture-", Path(result["receipt_dir"]).name)
        self.assertTrue(Path(result["receipt_dir"]).is_relative_to(self.workspace))

    def test_install_requires_matching_well_formed_durable_owner_sid(self):
        self.load()
        for expected in (None, "", "not-a-sid", OTHER_SID):
            with self.subTest(expected=expected):
                calls = []
                with patch("subprocess.run", self.identity_boundary(calls, "host\\15928", OWNER_SID)):
                    result = self.controller(owner_sid=expected).install_task()
                self.assertEqual(result["status"], "REFUSED")
                self.assertTrue(all(Path(command[0]).stem.lower() == "whoami"
                                    for command, _ in calls))

    def test_matching_owner_invokes_original_installer_with_normal_file_policy(self):
        self.load()
        calls = []
        with patch("subprocess.run", self.identity_boundary(calls, "host\\15928", OWNER_SID)):
            result = self.controller(owner_sid=OWNER_SID).install_task()
        installs = [command for command, _ in calls if "-Install" in command]
        self.assertEqual(installs, [["powershell.exe", "-NoProfile", "-NonInteractive",
            "-File", str(ROOT / "research" / "harness_v46" / "windows_closed_loop_tasks.ps1"),
            "-ConfigFile", str(self.config), "-Install"]])
        self.assertTrue(any("/user" in command for command, _ in calls))
        for command, _ in calls:
            self.assertFalse({"-executionpolicy", "bypass", "-force"} &
                             {str(token).lower() for token in command})
        self.assertEqual(result["host_acceptance"], "NOT_VERIFIED")
        folder = Path(result["receipt_dir"])
        self.assertEqual(folder.parent, self.config.parent)
        self.assertTrue(folder.name.startswith("capture-"))

    def test_readonly_task_query_failures_are_retained_without_claiming_absence(self):
        self.load()
        calls = []
        with patch("subprocess.run", self.identity_boundary(calls, "host\\15928", OWNER_SID,
                                                            query_error=True)):
            result = self.controller(owner_sid=OWNER_SID).install_task()
        self.assertEqual(result["host_acceptance"], "NOT_VERIFIED")
        self.assertEqual(result["task_query_status"], "NOT_VERIFIED")
        queries = [command for command, _ in calls
                   if Path(command[0]).stem.lower() != "whoami" and "-Install" not in command]
        self.assertGreaterEqual(len(queries), 2, "TaskXML and TaskInfo evidence both required")
        retained = [p.read_bytes() for p in Path(result["receipt_dir"]).rglob("*") if p.is_file()]
        self.assertGreaterEqual(sum(raw == b"QUERY_ACCESS_DENIED\r\n" for raw in retained), 2)

    def test_research_view_reads_supplied_evidence_without_promoting_formal_denominator(self):
        self.load()
        report = self.base / "exploratory.json"
        report.write_text(json.dumps({"evidence_tier": "POST_RESULT_RECONSTRUCTION_EXPLORATORY",
                                      "formal_A": 0, "decision": "NO_EDGE"}), encoding="utf-8")
        before = self.tree()
        result = self.controller(reports=(report,)).research_status()
        self.assertIn("POST_RESULT_RECONSTRUCTION_EXPLORATORY", json.dumps(result))
        self.assertEqual(result["formal_future_denominator"], "NOT_VERIFIED")
        self.assertEqual(self.tree(), before)

    def test_controller_import_is_lazy_and_preserves_preexisting_global_glp(self):
        self.load()
        code = """import importlib,sys,types
sentinel=types.ModuleType('glp'); sentinel.owner='SSQ'
sys.modules['glp']=sentinel
importlib.import_module('research.harness_v46.desktop')
assert sys.modules['glp'] is sentinel
assert 'glp.gui' not in sys.modules
assert not any(k.endswith('.gui') and 'desktop' in k for k in sys.modules)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    @unittest.skipUnless(os.name == "nt", "native Win32 widget smoke")
    def test_real_native_close_waits_for_explicit_acknowledgement_after_fsync_failure(self):
        desktop = self.load()
        started, release = threading.Event(), threading.Event()
        receipt = self.base / "receipt.json"
        class InertController:
            def read_status(inner, progress=None):
                return {"status": "MISSING", "formal_A": 0, "decision": "NO_EDGE"}
            def run_tick(inner, progress=None):
                started.set()
                release.wait(3)
                desktop._write_json(receipt, {"status": "COMPLETED"})
                return {"status": "COMPLETED", "formal_A": 0, "decision": "NO_EDGE"}
            install_task = research_status = read_status
        app = desktop.build_window(InertController())
        try:
            with patch.object(desktop.os, "fsync", side_effect=OSError("injected receipt fsync failure")):
                app._start(1001)
                self.assertTrue(started.wait(1))
                app._wndproc(app.hwnd, app.WM_CLOSE, 0, 0)
                release.set()
                deadline = time.monotonic() + 3
                while app.busy and time.monotonic() < deadline:
                    app._drain()
                    time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertTrue(app.user32.IsWindow(app.hwnd),
                            "close hid the persistence failure before acknowledgement")
            size = app.user32.GetWindowTextLengthW(app.controls["output"]) + 1
            text = app.ctypes.create_unicode_buffer(size)
            app.user32.GetWindowTextW(app.controls["output"], text, size)
            self.assertIn("injected receipt fsync failure", text.value)
            self.assertFalse(app.close_requested)
            app._wndproc(app.hwnd, app.WM_CLOSE, 0, 0)
            self.assertFalse(app.user32.IsWindow(app.hwnd))
        finally:
            release.set()
            if app.worker:
                app.worker.join(3)
            if app.user32.IsWindow(app.hwnd):
                app.user32.DestroyWindow(app.hwnd)

    def pythonw_startup(self, missing=None, receipt=None, extra=()):
        import ctypes
        from ctypes import wintypes
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        self.assertTrue(pythonw.is_file())
        command = [str(pythonw), "-B", "-m", "research.harness_v46.desktop"]
        if missing is not None:
            command += ["--config", str(missing)]
        if receipt is not None:
            command += ["--result-file", str(receipt)]
        command += list(extra)
        process = subprocess.Popen(command,
                                   cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
        windows, texts = [], []
        def read_text(hwnd):
            size = user32.GetWindowTextLengthW(hwnd) + 1
            value = ctypes.create_unicode_buffer(size)
            user32.GetWindowTextW(hwnd, value, size)
            return value.value
        @callback_type
        def child(hwnd, unused):
            texts.append(read_text(hwnd))
            return True
        @callback_type
        def top(hwnd, unused):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process.pid:
                windows.append(hwnd)
                texts.append(read_text(hwnd))
                user32.EnumChildWindows(hwnd, child, 0)
            return True
        try:
            deadline = time.monotonic() + 5
            while process.poll() is None and time.monotonic() < deadline:
                windows.clear()
                texts.clear()
                user32.EnumWindows(top, 0)
                if windows and any("BLOCKED:" in item for item in texts):
                    break
                time.sleep(.02)
            for hwnd in windows:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return process.wait(timeout=3), windows, "\n".join(texts)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)

    @unittest.skipUnless(os.name == "nt", "pythonw native startup diagnostic")
    def test_pythonw_missing_config_retains_receipt_and_shows_native_error(self):
        missing = self.base / "missing config.json"
        receipt = self.base / "startup.json"
        code, windows, text = self.pythonw_startup(missing, receipt)
        self.assertTrue(receipt.exists(), "pythonw startup error did not retain a receipt")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "BLOCKED")
        self.assertIn("FileNotFoundError", saved["error"])
        self.assertIn(missing.name, saved["error"])
        self.assertEqual(saved["config_file"], str(missing))
        self.assertEqual((saved["formal_A"], saved["decision"]), (0, "NO_EDGE"))
        self.assertTrue(windows, "pythonw startup error remained invisible")
        self.assertIn(str(missing), text)
        self.assertIn(str(receipt), text)
        self.assertEqual(code, 2)
        self.assertFalse((self.workspace / "operator_receipts").exists())

    @unittest.skipUnless(os.name == "nt", "pythonw native startup diagnostic")
    def test_pythonw_startup_diagnostic_does_not_overwrite_and_keeps_original_error_visible(self):
        missing = self.base / "missing config.json"
        receipt = self.base / "existing.json"
        receipt.write_bytes(b"original diagnostic bytes")
        code, windows, text = self.pythonw_startup(missing, receipt)
        self.assertTrue(windows, "failed diagnostic persistence left pythonw invisible")
        self.assertIn("FileNotFoundError", text)
        self.assertIn(str(missing), text)
        self.assertIn("FileExistsError", text)
        self.assertEqual(receipt.read_bytes(), b"original diagnostic bytes")
        self.assertEqual(code, 2)

    @unittest.skipUnless(os.name == "nt", "pythonw native startup diagnostic")
    def test_pythonw_startup_without_result_path_uses_exclusive_config_parent_receipt(self):
        missing = self.base / "missing config.json"
        code, windows, text = self.pythonw_startup(missing)
        receipts = list((self.base / "desktop_startup_receipts").glob("startup-*.json"))
        self.assertEqual(len(receipts), 1, "startup error was not retained below config parent")
        self.assertTrue(windows)
        self.assertIn(str(receipts[0]), text)
        self.assertEqual(json.loads(receipts[0].read_text(encoding="utf-8"))["config_file"], str(missing))
        self.assertLess(len(receipts[0].name), 64)
        self.assertEqual(code, 2)

    @unittest.skipUnless(os.name == "nt", "pythonw native startup diagnostic")
    def test_pythonw_missing_config_flag_and_bad_arguments_are_visible(self):
        for extra, expected in (((), "config"), (("--not-a-real-flag",), "unrecognized")):
            with self.subTest(extra=extra):
                receipt = self.base / ("arguments-" + str(len(extra)) + ".json")
                code, windows, text = self.pythonw_startup(receipt=receipt, extra=extra)
                self.assertTrue(windows, "pythonw parser error remained invisible")
                self.assertIn(expected, text)
                self.assertTrue(receipt.exists())
                self.assertEqual(code, 2)

    @unittest.skipUnless(os.name == "nt", "native Win32 widget smoke")
    def test_real_native_buttons_use_inert_callbacks_and_close_waits_for_receipt(self):
        desktop = self.load()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []
        class InertController:
            def read_status(inner, progress=None):
                calls.append("read")
                return {"status": "MISSING", "formal_future_denominator": "NOT_VERIFIED",
                        "formal_A": 0, "decision": "NO_EDGE"}
            def run_tick(inner, progress=None):
                calls.append("run")
                started.set()
                release.wait(3)
                finished.set()
                return {"status": "BLOCKED", "source_status": "BLOCKED", "decision": "NO_EDGE"}
            def install_task(inner, progress=None):
                calls.append("install-inert")
                return {"status": "REFUSED", "decision": "NO_EDGE"}
            def research_status(inner, progress=None):
                calls.append("research")
                return {"evidence_tier": "TEST_ONLY_SYNTHETIC", "decision": "NO_EDGE"}
        acceptance = self.base / "legacy-acceptance"
        before = self.tree()
        with patch.dict(os.environ, {"GLP_GUI_ACCEPTANCE_DIR": str(acceptance)}), \
                patch("subprocess.run", side_effect=AssertionError("native smoke launched external process")):
            app = desktop.build_window(InertController())
            try:
                self.assertTrue(app.user32.IsWindow(app.hwnd))
                self.assertEqual(len(app.buttons), 4)
                self.assertTrue(all(app.user32.IsWindow(h) for h in app.buttons))
                self.assertEqual(calls, ["read"])
                cids = list(app.renderers)
                for cid, expected in ((cids[1], "read"), (cids[2], "install-inert"),
                                      (cids[3], "research")):
                    app._start(cid)
                    deadline = time.monotonic() + 3
                    while app.busy and time.monotonic() < deadline:
                        app._drain()
                        time.sleep(.01)
                    self.assertFalse(app.busy)
                    self.assertEqual(calls[-1], expected)
                app._start(cids[0])
                self.assertTrue(started.wait(1))
                app._wndproc(app.hwnd, app.WM_CLOSE, 0, 0)
                self.assertTrue(app.user32.IsWindow(app.hwnd), "close discarded in-flight receipt")
                release.set()
                deadline = time.monotonic() + 3
                while app.user32.IsWindow(app.hwnd) and time.monotonic() < deadline:
                    app._drain()
                    time.sleep(.01)
                self.assertTrue(finished.is_set())
                self.assertFalse(app.user32.IsWindow(app.hwnd))
            finally:
                release.set()
                if app.user32.IsWindow(app.hwnd):
                    app.user32.DestroyWindow(app.hwnd)
        self.assertFalse(acceptance.exists())
        self.assertEqual(self.tree(), before)


if __name__ == "__main__":
    unittest.main()
