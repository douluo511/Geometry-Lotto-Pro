"""Controlled verifier contracts only: never claim these fixtures are GUI/live proof."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from derive_gate_status import _verify_gui_failure_evidence, derive
from release_gate_22 import HARD_GATES


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class RepairFailureEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.exe = self.root / "Geometry_Lotto_Pro_SSQ_Windows_Verified.exe"
        updater = self.root / "Geometry_Lotto_Pro_SSQ_Updater.exe"
        self.exe.write_bytes(b"TEST_ONLY_main")
        updater.write_bytes(b"TEST_ONLY_updater")
        updater_hash = digest(updater.read_bytes())
        source = self.root / ("physical-gui-run-" + "1" * 32)
        self.run = self.root / ("physical-gui-failure-" + "2" * 32)
        source.mkdir()
        self.run.mkdir()
        history = b'{"game":"SSQ","draws":[]}'
        evidence = b'{"TEST_ONLY":true}'
        corrupt = b"SSQ_CONTROLLED_CORRUPT_HISTORY_V1\n"
        (source / "canonical_history.json").write_bytes(history)
        (source / "source_evidence.json").write_bytes(evidence)
        (self.run / "canonical_history.json").write_bytes(corrupt)
        (self.run / "source_evidence.json").write_bytes(evidence)
        materialized = self.run / "updater" / updater_hash / updater.name
        materialized.parent.mkdir(parents=True)
        materialized.write_bytes(updater.read_bytes())
        failure = self.run / "failed" / ("3" * 24)
        failure.mkdir(parents=True)
        (failure / "failure_evidence.json").write_text(json.dumps({
            "status": "FAIL", "crosscheck_status": "FAIL", "raw_response_status": "UNAVAILABLE",
        }), encoding="utf-8")
        self.payload = {"status": "FAIL", "repaired": False, "before": {"ok": False},
                        "repair_attempts": [{"attempt": 1, "status": "FAIL"}]}
        with closing(sqlite3.connect(self.run / "ledger.sqlite3", isolation_level=None)) as db:
            db.execute("CREATE TABLE experiments(kind TEXT,status TEXT,payload_json TEXT)")
            db.execute("INSERT INTO experiments VALUES('repair','FAIL',?)", (json.dumps(self.payload),))
        self.label = "\u4e00\u952e\u4fee\u590d"
        ui = (self.label + " FAIL\nFail-Closed").encode("utf-8")
        (self.run / "gui_failure_output.txt").write_bytes(ui)
        self.report = {
            "schema": "physical-gui-failure-smoke-v2", "status": "PASS",
            "operation": "repair", "control_id": 103, "process_id": 4321,
            "click_x": 100, "click_y": 100, "scenario": "controlled Windows outbound block",
            "exe": self.exe.name, "exe_sha256": digest(self.exe.read_bytes()),
            "updater_exe": updater.name, "updater_sha256": updater_hash,
            "materialized_updater": str(materialized), "materialized_updater_sha256": updater_hash,
            "firewall_programs": [str(self.exe), str(updater), str(materialized)],
            "github_sha": "a" * 40, "github_run_id": "12345", "firewall_rules_created": True,
            "ui_fail_closed": True, "ui_status": self.label + "\uff1aFAIL", "ui_output_sha256": digest(ui),
            "tested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_dir": self.run.name, "source_success_data_dir": source.name,
            "original_canonical_sha256": digest(history), "corruption_injected": True,
            "before_canonical_sha256": digest(corrupt), "after_canonical_sha256": digest(corrupt),
            "before_evidence_sha256": digest(evidence), "after_evidence_sha256": digest(evidence),
            "canonical_unchanged": True, "evidence_unchanged": True,
            "failure_manifest_count": 1, "official_update_pass_count": 0,
            "repair_fail_count": 1, "repair_pass_count": 0,
        }
        context = patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"})
        context.start()
        self.addCleanup(context.stop)

    def verify(self):
        return _verify_gui_failure_evidence(self.report, self.root, self.exe, True, "repair")

    def test_corrupt_offline_repair_requires_own_evidence(self):
        proof = self.verify()
        self.assertEqual(proof["operation"], "repair")
        self.assertEqual(proof["repair_fail_count"], 1)
        self.assertEqual(proof["repair_pass_count"], 0)

    def test_update_report_cannot_stand_in_for_repair(self):
        self.report["operation"] = "update"
        self.report["control_id"] = 102
        with self.assertRaises(ValueError):
            self.verify()

    def test_healthy_noop_and_undeclared_corruption_fail(self):
        for value in (False, None, "true"):
            self.report["corruption_injected"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verify()
        self.report["corruption_injected"] = True
        raw = b'{"game":"SSQ","draws":[]}'
        (self.run / "canonical_history.json").write_bytes(raw)
        self.report["before_canonical_sha256"] = self.report["after_canonical_sha256"] = digest(raw)
        with self.assertRaises(ValueError):
            self.verify()

    def test_changed_ui_or_rehashed_wrong_operation_fail(self):
        for raw in (b"PASS", "\u4e00\u952e\u66f4\u65b0 FAIL\nFail-Closed".encode("utf-8")):
            (self.run / "gui_failure_output.txt").write_bytes(raw)
            self.report["ui_output_sha256"] = digest(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.verify()

    def test_empty_ledger_or_false_success_fail(self):
        with closing(sqlite3.connect(self.run / "ledger.sqlite3", isolation_level=None)) as db:
            db.execute("DELETE FROM experiments")
        with self.assertRaises(ValueError):
            self.verify()
        with closing(sqlite3.connect(self.run / "ledger.sqlite3", isolation_level=None)) as db:
            db.execute("INSERT INTO experiments VALUES('repair','PASS',?)", (json.dumps(self.payload),))
        with self.assertRaises(ValueError):
            self.verify()

    def test_failed_ledger_must_prove_failed_rebuild(self):
        for value in ({**self.payload, "repaired": True}, {**self.payload, "repair_attempts": []},
                      {**self.payload, "before": {"ok": True}}, [],
                      {**self.payload, "repair_attempts": [{"status": "PASS"}]}):
            with closing(sqlite3.connect(self.run / "ledger.sqlite3", isolation_level=None)) as db:
                db.execute("UPDATE experiments SET payload_json=?", (json.dumps(value),))
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verify()

    def test_modified_dataset_and_false_integer_counts_fail(self):
        self.report["repair_fail_count"] = True
        with self.assertRaises(ValueError):
            self.verify()
        self.report["repair_fail_count"] = 1
        (self.run / "canonical_history.json").write_bytes(b"unexpected repair overwrite")
        with self.assertRaises(ValueError):
            self.verify()

    def test_old_run_or_missing_control_identity_fails(self):
        for key, value in (("github_run_id", "old"), ("control_id", 102), ("process_id", True),
                           ("click_x", None), ("schema", "physical-gui-failure-smoke-v1")):
            old = self.report[key]
            self.report[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.report[key] = old

    def test_missing_repair_report_is_required_nonpass(self):
        self.assertIn("physical_gui_repair_failure", HARD_GATES)
        result = derive(self.root, self.exe)
        self.assertNotEqual(result["gates"]["physical_gui_repair_failure"], "PASS")
        self.assertNotEqual(result["gates"]["integration_test"], "PASS")


if __name__ == "__main__":
    unittest.main()
