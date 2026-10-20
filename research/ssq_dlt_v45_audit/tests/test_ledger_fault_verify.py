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
        with self.assertRaisesRegex(ValueError, "NATIVE_CAPTURE_RECOVERY_MISMATCH"):
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
