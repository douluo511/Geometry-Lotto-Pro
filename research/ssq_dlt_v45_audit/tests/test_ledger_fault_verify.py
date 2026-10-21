"""Falsify crash receipts, including rehashed corruption and disabled assertions."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from research.ssq_dlt_v45_audit.ledger_faults import ROOT, run
from research.ssq_dlt_v45_audit.ledger_fault_verify import verify


class FaultReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="v45-fault-verifier-tests-")
        cls.root = Path(cls.temp.name)
        cls.good = cls.root / "real-process-run"
        with contextlib.redirect_stdout(io.StringIO()):
            if run(cls.good) != 0:
                raise AssertionError((cls.good / "faults.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def changed_copy(self):
        target = self.root / self.id().rsplit(".", 1)[-1]
        shutil.copytree(self.good, target)
        return target

    @staticmethod
    def replace_report(target, report):
        (target / "faults.json").write_text(json.dumps(report), encoding="utf-8")

    def test_native_recovery_readonly_positive(self):
        report = verify(self.good)
        self.assertTrue(report["original_evidence_unchanged"])
        self.assertEqual(report["final_rows"], 4)
        self.assertFalse(report["producer_wal_parser_or_store_executed"])

    def test_zero_exit_cannot_be_called_killed(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][0]["child_exit_code"] = 0
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "KILL_NOT_ESTABLISHED"):
            verify(target)

    def test_report_cannot_relabel_raw_fault_point(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][0]["fault_point"]["phase"] = "APPEND_RETURNED"
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "RAW_FAULT_POINT_MISMATCH"):
            verify(target)

    def test_rehashed_corrupt_committed_wal_cannot_pass(self):
        target = self.changed_copy()
        path = target / "after_commit.captured.wal"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][1]["captured_wal"]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "WAL_FRAME_SUMMARY_MISMATCH"):
            verify(target)

    def test_invalid_control_cannot_pass(self):
        target = self.changed_copy()
        path = target / "control.json"
        control = json.loads(path.read_bytes())
        control.update(schema="INVALID", owner_pid=-12345)
        path.write_text(json.dumps(control), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "FIXTURE_CONTROL_CONTRACT"):
            verify(target)

    def test_positive_relabelled_parent_cannot_pass(self):
        target = self.changed_copy()
        path = target / "control.json"
        control = json.loads(path.read_bytes())
        control["owner_pid"] += 1000000
        path.write_text(json.dumps(control), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "FAULT_PARENT_CHILD_BINDING"):
            verify(target)

    def test_missing_barrier_cannot_pass(self):
        target = self.changed_copy()
        (target / "concurrent_same.start.json").unlink()
        with self.assertRaisesRegex(ValueError, "CONCURRENT_BARRIER_REQUIRED"):
            verify(target)

    def test_false_payload_digest_cannot_pass(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][2]["final_payload_sha256"] = "0" * 64
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "FINAL_PAYLOAD_DIGEST_MISMATCH"):
            verify(target)

    def test_empty_rehashed_precommit_wal_cannot_pass(self):
        target = self.changed_copy()
        path = target / "before_commit.captured.wal"
        path.write_bytes(b"")
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][0]["captured_wal"].update(bytes=0, sha256=hashlib.sha256(b"").hexdigest(),
            valid_frames=0, commit_frames=0, valid_frames_after_last_commit=0)
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "WAL_HEADER_REQUIRED"):
            verify(target)

    def test_rehashed_false_producer_source_cannot_pass(self):
        target = self.changed_copy()
        path = target / "source_manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["research/ssq_dlt_v45_audit/ledger_faults.py"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        report = json.loads((target / "faults.json").read_bytes())
        compact = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        report["source_manifest_sha256"] = hashlib.sha256(compact.encode()).hexdigest()
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "CURRENT_PRODUCER_AND_VERIFIER_SOURCE_BINDING_REQUIRED"):
            verify(target)

    def test_string_false_source_unchanged_cannot_pass(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["source_unchanged"] = "false"
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_EXECUTION"):
            verify(target)

    def test_string_false_children_exited_cannot_pass(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["owned_children_exited"] = "false"
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_EXECUTION"):
            verify(target)

    def test_boolean_cannot_replace_zero_formal_samples(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["formal_A"] = False
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "BOUNDARY_CHANGED"):
            verify(target)

    def test_boolean_cannot_replace_commit_frame_count(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        report["cases"][1]["captured_wal"]["commit_frames"] = True
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "WAL_FRAME_SUMMARY_MISMATCH"):
            verify(target)

    def test_float_concurrency_ready_pid_cannot_alias_integer_result(self):
        target = self.changed_copy()
        report = json.loads((target / "faults.json").read_bytes())
        point = report["cases"][2]["ready_points"][0]
        point["pid"] = float(point["pid"])
        (target / "concurrent_same_a.ready.json").write_text(json.dumps(point), encoding="utf-8")
        self.replace_report(target, report)
        with self.assertRaisesRegex(ValueError, "RAW_CONCURRENCY_POINT_MISMATCH"):
            verify(target)

    def test_optimized_python_rejected_without_output(self):
        output = self.root / "optimized-must-not-write"
        result = subprocess.run([sys.executable, "-O", "-B", "-m",
            "research.ssq_dlt_v45_audit.ledger_faults", "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAULT_ACCEPTANCE_REQUIRES_ASSERTIONS_ENABLED", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
