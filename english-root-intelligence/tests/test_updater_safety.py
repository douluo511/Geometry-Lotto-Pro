from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain import SourceReceipt
from net_client import NetClient
from service import create_service
from updater import _atomic_json, _receipt_without_raw
from updater_gate import healthy_self_test, manifest_bytes, updater_with


class UpdaterSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "Main.exe"
        self.old, self.new = b"MZ-old", b"MZ-new"
        self.target.write_bytes(self.old)
        self.manifest = manifest_bytes(version="0.2.1", artifact=self.new)

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_receipt_dataclass_keeps_exact_raw_bytes(self):
        value = SourceReceipt("software", "https://updates.example/a", "https://updates.example/a", 200,
                              "application/octet-stream", hashlib.sha256(self.new).hexdigest(),
                              "2026-10-03T00:00:00Z", len(self.new), 1,
                              ({"attempt": 1, "outcome": "HTTP_RESPONSE"},), base64.b64encode(self.new).decode())
        result = _receipt_without_raw(value)
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(base64.b64decode(result["raw_b64"]), self.new)
        self.assertEqual(result["attempt_ledger"], value.attempt_ledger)

    def test_wrong_candidate_version_rolls_back(self):
        def wrong_health(args, **kwargs):
            output = Path(args[args.index("--result-file") + 1])
            output.write_text(json.dumps({"status": "PASS", "version": "0.2.0"}), encoding="utf-8")
            return type("Completed", (), {"returncode": 0})()
        with patch("updater.subprocess.run", side_effect=wrong_health):
            result = updater_with(self.manifest, self.new).install(target_exe=self.target, current_version="0.2.0")
        self.assertEqual(result["action"], "ROLLED_BACK")
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_evidence_persistence_failure_restores_old_bytes(self):
        evidence = self.root / "result.json"
        def failing_evidence(path, value):
            if Path(path) == evidence:
                raise PermissionError("evidence cannot persist")
            _atomic_json(path, value)
        with patch("updater._atomic_json", side_effect=failing_evidence), patch("updater.subprocess.run", side_effect=healthy_self_test):
            with self.assertRaises(PermissionError):
                updater_with(self.manifest, self.new).install(target_exe=self.target, current_version="0.2.0", evidence_file=evidence)
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_restart_launch_failure_rolls_back(self):
        with patch("updater.subprocess.run", side_effect=healthy_self_test), patch("updater.subprocess.Popen", side_effect=OSError("restart denied")):
            result = updater_with(self.manifest, self.new).install(target_exe=self.target, current_version="0.2.0", restart=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["action"], "ROLLED_BACK")
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_up_to_date_restarts_main_without_replacement(self):
        with patch("updater.subprocess.Popen") as process:
            result = updater_with(self.manifest).install(target_exe=self.target, current_version="0.2.1", restart=True)
        self.assertEqual(result["action"], "UP_TO_DATE")
        process.assert_called_once()
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_stream_limit_stops_read_and_closes_response(self):
        class Response:
            status_code, url = 200, "https://updates.example/a"
            headers = {"Content-Type": "application/octet-stream"}
            consumed, closed = 0, False
            def iter_content(self, **kwargs):
                for chunk in (b"1234", b"5678", b"must-not-be-read"):
                    self.consumed += 1
                    yield chunk
            def close(self):
                self.closed = True
        response = Response()
        session = type("Session", (), {"get": lambda *args, **kwargs: response})()
        with self.assertRaises(ValueError):
            NetClient(session=session, max_payload_bytes=5).get_bytes(response.url)
        self.assertEqual(response.consumed, 2)
        self.assertTrue(response.closed)

    def test_repair_preserves_healthy_progress_bytes(self):
        service = create_service(self.root / "profile")
        progress = service.storage.store.progress_path
        raw = b'{"schema":1,"practiced":{"dict":11},"analyses":42,"last_update":null}\n'
        progress.write_bytes(raw)
        self.assertEqual(service.one_click_repair()["status"], "PASS")
        self.assertEqual(progress.read_bytes(), raw)

    def test_repair_archives_corrupt_original_before_reset(self):
        service = create_service(self.root / "profile")
        progress = service.storage.store.progress_path
        raw = b'\xffbroken learning progress'
        progress.write_bytes(raw)
        self.assertEqual(service.one_click_repair()["status"], "PASS")
        preserved = service.storage.root / "recovery" / f"progress.json.{hashlib.sha256(raw).hexdigest()}.original"
        self.assertEqual(preserved.read_bytes(), raw)
        self.assertEqual(service.storage.load_progress()["practiced"], {})


if __name__ == "__main__":
    unittest.main()
