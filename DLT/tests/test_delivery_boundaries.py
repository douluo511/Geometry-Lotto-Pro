"""Controlled regression fixtures only. No test here claims live/GUI acceptance."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from glp import gui, service
from glp.acceptance_evidence import preserve_live_evidence
from glp.storage import Store
from glp.util import sha256_json
import main


class ServiceBoundaryTests(unittest.TestCase):
    def test_self_test_never_writes_the_production_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production"
            production.mkdir()
            sentinel = production / "ledger.sqlite3"
            sentinel.write_bytes(b"USER_DATA_DO_NOT_TOUCH")
            with patch.dict(os.environ, {"GLP_DATA_DIR": str(production)}):
                result = service.self_test(root / "test-parent")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["real_network_status"], "PENDING")
            self.assertEqual(result["test_data_classification"], "TEST_ONLY_SYNTHETIC")
            self.assertEqual(sentinel.read_bytes(), b"USER_DATA_DO_NOT_TOUCH")
            self.assertEqual(list((root / "test-parent").iterdir()), [])
            self.assertEqual([p.name for p in production.iterdir()], ["ledger.sqlite3"])

    def test_audit_uses_current_court_and_never_calls_predict_or_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            svc = service.LottoService(store)
            court = {"software_verdict": "PASS", "model_hash": "current-model"}
            with patch.object(svc, "ensure_seed"), \
                 patch.object(store, "integrity_check", return_value={"status": "PASS"}), \
                 patch.object(store, "load_draws", return_value=(["TEST_ONLY_DRAW"], "dataset")), \
                 patch.object(store, "prospective_replays", return_value=[]), \
                 patch.object(service, "run_evidence_court", return_value=court), \
                 patch.object(service, "make_prediction", return_value=(object(), {"current": True})) as preview, \
                 patch.object(svc, "predict", side_effect=AssertionError("formal predict forbidden")), \
                 patch.object(store, "freeze", side_effect=AssertionError("formal freeze forbidden")):
                result = svc.audit()
            self.assertIs(preview.call_args.args[2], court)
            self.assertFalse(result["formal_freeze_written"])
            self.assertEqual(result["freeze_before"], result["freeze_after"])
            with store._connection() as db:
                kinds = [r[0] for r in db.execute("SELECT kind FROM experiments")]
            self.assertEqual(kinds, ["evidence_court"])
            self.assertEqual(store.freezes(), [])

    def test_repair_failure_is_raised_and_recorded_without_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            svc = service.LottoService(store)
            with patch.object(svc, "_repair_impl", side_effect=RuntimeError("source timeout")):
                with self.assertRaisesRegex(RuntimeError, "source timeout"):
                    svc.repair()
            with store._connection() as db:
                rows = db.execute("SELECT kind,status,payload_json FROM experiments").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0][0], rows[0][1]), ("repair", "FAIL"))
            self.assertEqual(json.loads(rows[0][2])["error"], "source timeout")

    def test_repair_evidence_write_failure_is_not_swallowed(self):
        store = SimpleNamespace(append_experiment=Mock(side_effect=OSError("disk full")))
        svc = service.LottoService(store)
        with patch.object(svc, "_repair_impl", side_effect=ValueError("bad source")):
            with self.assertRaisesRegex(RuntimeError, "bad source.*evidence write also failed.*disk full"):
                svc.repair()

    def test_unrepaired_integrity_cannot_return_success(self):
        checks = [{"name": name, "status": "PASS"} for name in (
            "SQLite integrity", "Freeze archive", "Canonical hash", "Source evidence")]
        store = SimpleNamespace(
            integrity_check=Mock(side_effect=[{"checks": checks}, {"checks": checks}, {"status": "FAIL"}]),
            append_experiment=Mock(),
        )
        svc = service.LottoService(store)
        with patch.object(svc, "replay_all", return_value=0):
            with self.assertRaisesRegex(ValueError, "did not restore"):
                svc.repair()
        self.assertEqual(store.append_experiment.call_args.args[:2], ("repair", "FAIL"))


class GuiFailureTests(unittest.TestCase):
    def app(self):
        app = gui.NativeApp.__new__(gui.NativeApp)
        app.events = queue.Queue()
        app.busy = True
        app._set = Mock()
        app._enable = Mock()
        return app

    def test_renderer_error_unlocks_buttons_and_shows_failure(self):
        app = self.app()
        app.events.put(("done", ({}, Mock(side_effect=ValueError("invalid result")))))
        app._drain()
        self.assertFalse(app.busy)
        app._enable.assert_called_once_with(True)
        self.assertTrue(any("Fail-Closed" in c.args[1] for c in app._set.call_args_list))

    def test_all_nonpass_backend_statuses_are_rejected(self):
        for status in ("FAIL", "PENDING", "BLOCKED", "UNAVAILABLE", "SKIPPED", "WARNING", "UNKNOWN", None):
            with self.subTest(status=status):
                app = self.app()
                renderer = Mock()
                app.events.put(("done", ({"status": status}, renderer)))
                app._drain()
                renderer.assert_not_called()
                self.assertFalse(app.busy)

    def test_failed_repair_payload_never_reaches_success_renderer(self):
        app = self.app()
        renderer = Mock()
        app.events.put(("done", ({"after": {"status": "FAIL"}}, renderer)))
        app._drain()
        renderer.assert_not_called()

    def test_update_formatter_does_not_hardcode_pass_for_failed_network(self):
        for value in ({}, {"network_gate": "FAIL"}, {"network_gate": "PASS", "crosscheck_status": "WARNING"}):
            with self.assertRaises(ValueError):
                gui._format_update(value)


class AcceptanceBoundaryTests(unittest.TestCase):
    def test_source_python_hash_is_not_an_exact_exe(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(main._exe_sha256(), "")

    def test_source_cannot_emit_final_pass_and_environment_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            result_file = Path(directory) / "result.json"
            with patch.dict(os.environ, {"GLP_DATA_DIR": "original-user-location"}), \
                 patch.object(sys, "frozen", False, create=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.run_acceptance(str(result_file)), 2)
                self.assertEqual(os.environ["GLP_DATA_DIR"], "original-user-location")
            report = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertNotEqual(report["final_release_gate"], "PASS")
            self.assertEqual(report["exact_acceptance_gate"], "FAIL")

    def test_live_bytes_survive_temporary_store_and_bind_exact_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tempfile.TemporaryDirectory(dir=root) as store_dir:
                store = self.fixture(Path(store_dir))
                proof = preserve_live_evidence(store, str(root / "result.json"), "a" * 64)
            manifest = json.loads((root / proof["directory"] / "manifest.json").read_text())
            row = manifest["raw_responses"][0]
            raw = root / proof["directory"] / row["artifact"]
            self.assertEqual(raw.read_bytes(), b"TEST_ONLY_RAW\r\n")
            self.assertEqual(manifest["exe_sha256"], "a" * 64)
            self.assertEqual(manifest["final_release_gate"], "PENDING")

    def test_tampered_raw_or_missing_bodies_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.fixture(root)
            evidence = json.loads(store.evidence_path.read_text())
            evidence["response"]["sha256"] = "0" * 64
            store.evidence_path.write_text(json.dumps(evidence))
            with self.assertRaises(ValueError):
                preserve_live_evidence(store, str(root / "result.json"), "a" * 64)
            del evidence["response"]
            store.evidence_path.write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError, "missing"):
                preserve_live_evidence(store, str(root / "result.json"), "a" * 64)

    @staticmethod
    def fixture(root):
        raw = b"TEST_ONLY_RAW\r\n"
        draws = [{"issue": "26001", "draw_date": "2026-01-03", "front": [1, 2, 3, 4, 5], "back": [1, 2]}]
        canonical_hash = sha256_json(draws)
        evidence = {
            "network_gate": "PASS", "freshness_gate": "PASS", "crosscheck_status": "PASS",
            "canonical_hash": canonical_hash, "response": {
                "body_b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "http_status": 200, "final_url": "https://example.invalid/test-only",
                "fetched_at": "2026-10-01T00:00:00Z", "parser_version": "test-only",
                "validation_result": "PASS",
            },
        }
        ep = root / "source_evidence.json"
        hp = root / "canonical_history.json"
        ep.write_text(json.dumps(evidence))
        hp.write_text(json.dumps({"game": "DLT", "draws": draws, "canonical_hash": canonical_hash}))
        return SimpleNamespace(evidence_path=ep, history_path=hp)


if __name__ == "__main__":
    unittest.main()
