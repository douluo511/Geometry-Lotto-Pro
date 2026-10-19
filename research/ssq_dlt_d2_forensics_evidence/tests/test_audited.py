"""Durable audit custody regressions: only tiny disposable synthetic evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from research.ssq_dlt_d2_forensics_evidence import audited, verify
from research.ssq_dlt_d2_forensics_evidence.tests import test_verify as fixtures


class DurableSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="d2-durable-tiny-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "studies").mkdir()
        (self.root / "sessions").mkdir()
        self.study = self.root / "studies" / "study"
        self.session = self.root / "sessions" / "run"
        self.protocol = fixtures.AdapterIntegrityTests().fixture(self.study)
        self.sources = {"files": {"pinned.py": {"kind": "file", "size": 1, "sha256": "a" * 64}}, "errors": []}
        (self.study / "plan.json").write_text(json.dumps({"source_sha256": {"pinned.py": "a" * 64}}), encoding="utf-8")

    def native(self, study, receipt):
        return verify.verify_study(study, receipt, protocol=self.protocol)

    def run_session(self, callback=None, source_provider=None):
        return audited.audit(self.study, self.session, verifier=callback or self.native,
                             source_provider=source_provider or (lambda: copy.deepcopy(self.sources)))

    def load(self, name):
        return json.loads((self.session / name).read_text(encoding="utf-8"))

    def test_success_keeps_native_byte_failure_distinct_and_zero_edge(self):
        answer = self.run_session()
        self.assertEqual(answer["status"], audited.AUDITED_PASS)
        self.assertEqual(answer["native_result"]["native_report_check"]["status"], "FAIL_REPORT_RESULT_MISMATCH")
        self.assertEqual(answer["decision"], "NO_EDGE")
        self.assertEqual(answer["qualified_prospective_samples_added"], 0)
        self.assertEqual(self.load("START.json")["status"], "INCOMPLETE")
        self.assertEqual(audited.inspect(self.session)["status"], audited.AUDITED_PASS)

    def test_start_and_before_reach_fsync_before_verifier_runs(self):
        calls = []
        real = os.fsync

        def observed_fsync(descriptor):
            calls.append(descriptor)
            return real(descriptor)

        def checked_native(study, receipt):
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue((self.session / "START.json").is_file())
            self.assertTrue((self.session / "before.json").is_file())
            self.assertFalse((self.session / "receipt.json").exists())
            return self.native(study, receipt)

        with mock.patch.object(audited.os, "fsync", side_effect=observed_fsync):
            self.assertEqual(self.run_session(checked_native)["status"], audited.AUDITED_PASS)

    def test_nonempty_wal_early_refusal_retains_before_after_and_failure(self):
        (self.study / "research.sqlite3-wal").write_bytes(b"synthetic uncheckpointed data")
        answer = self.run_session()
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("UNCHECKPOINTED_WAL", answer["errors"][0]["message"])
        self.assertTrue((self.session / "before.json").is_file())
        self.assertTrue((self.session / "after.json").is_file())
        self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_html_early_refusal_has_persistent_failure(self):
        path = self.study / "report.html"
        path.write_text(path.read_text(encoding="utf-8").replace("11/240", "99/240"), encoding="utf-8")
        answer = self.run_session()
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("HTML_SEMANTIC", answer["errors"][0]["message"])
        self.assertTrue((self.session / "after.json").is_file())

    def test_frozen_pin_mismatch_stops_before_verifier(self):
        self.sources["files"]["pinned.py"]["sha256"] = "b" * 64
        forbidden = mock.Mock(side_effect=AssertionError("must not execute"))
        answer = self.run_session(forbidden)
        forbidden.assert_not_called()
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("PIN_MISMATCH", answer["errors"][0]["message"])
        self.assertEqual(self.load("before.json")["frozen_source_pins"]["status"], "FAIL")

    def test_missing_study_is_a_durable_failure_in_safe_external_session(self):
        missing = self.root / "studies" / "not-created"
        answer = audited.audit(missing, self.session, verifier=self.native,
                               source_provider=lambda: copy.deepcopy(self.sources))
        self.assertEqual(answer["status"], "FAIL")
        self.assertEqual(self.load("before.json")["inputs"]["errors"][0]["error"], "DIRECTORY_REQUIRED")
        self.assertTrue((self.session / "after.json").is_file())

    def test_output_inside_study_parent_subtree_is_rejected_without_write(self):
        for target in (self.study / "run", self.study.parent / "other-run", self.study.parent):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "OUTSIDE_STUDY_PARENT"):
                audited.audit(self.study, target)
            self.assertFalse((target / "START.json").exists())

    def test_output_ancestor_is_rejected_without_write(self):
        with self.assertRaisesRegex(ValueError, "ANCESTORS"):
            audited.audit(self.study, self.root)
        self.assertFalse((self.root / "START.json").exists())

    def test_existing_session_cannot_be_overwritten(self):
        self.run_session()
        before = audited._snapshot(self.session)
        with self.assertRaises(FileExistsError):
            self.run_session()
        self.assertEqual(audited._snapshot(self.session), before)

    def test_added_input_is_named_in_persistent_diff(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            (study / "unexpected.txt").write_bytes(b"added")
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        self.assertEqual(set(answer["input_diff"]["added"]), {"unexpected.txt"})
        self.assertEqual(self.load("before.json")["inputs"]["files"].get("unexpected.txt"), None)

    def test_removed_input_is_named_in_persistent_diff(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            (study / "report.html").unlink()
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        self.assertEqual(set(answer["input_diff"]["removed"]), {"report.html"})

    def test_modified_input_preserves_both_hashes(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            (study / "report.html").write_bytes(b"modified")
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        change = answer["input_diff"]["modified"]["report.html"]
        self.assertNotEqual(change["before"]["sha256"], change["after"]["sha256"])

    def test_added_audit_source_is_detected(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            self.sources["files"]["new_audit.py"] = {"kind": "file", "size": 1, "sha256": "c" * 64}
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        self.assertEqual(set(answer["source_diff"]["added"]), {"new_audit.py"})

    def test_removed_source_is_detected_and_pin_fails(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            self.sources["files"].pop("pinned.py")
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        self.assertEqual(set(answer["source_diff"]["removed"]), {"pinned.py"})
        self.assertEqual(self.load("after.json")["frozen_source_pins"]["status"], "FAIL")

    def test_changed_source_preserves_both_hashes(self):
        def change(study, receipt):
            answer = self.native(study, receipt)
            self.sources["files"]["pinned.py"]["sha256"] = "d" * 64
            return answer
        answer = self.run_session(change)
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("pinned.py", answer["source_diff"]["modified"])

    def test_primary_verifier_and_integrity_errors_both_survive(self):
        def hostile(where):
            (Path(where) / "report.html").write_bytes(b"synthetic mutation")
            raise ValueError("PRIMARY_NATIVE_ERROR")
        self.protocol.verify = hostile
        answer = self.run_session()
        self.assertEqual(answer["status"], "FAIL")
        group = answer["errors"][0]
        self.assertEqual(group["type"], "ExceptionGroup")
        messages = [child["message"] for child in group["exceptions"]]
        self.assertEqual(messages, ["PRIMARY_NATIVE_ERROR", "FROZEN_STUDY_BYTES_CHANGED_DURING_VERIFICATION"])
        self.assertIn("report.html", answer["input_diff"]["modified"])

    def test_catchable_interrupt_and_exit_are_failures_with_receipts(self):
        for number, exception in enumerate((KeyboardInterrupt("synthetic interrupt"), SystemExit(0))):
            with self.subTest(exception=type(exception).__name__):
                self.session = self.root / "sessions" / str(number)
                def stop(study, receipt):
                    raise exception
                answer = self.run_session(stop)
                self.assertEqual(answer["status"], "FAIL")
                self.assertEqual(answer["errors"][0]["type"], type(exception).__name__)
                self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_cyclic_exception_cause_preserves_primary_and_durable_failure(self):
        primary, other = ValueError("PRIMARY_CYCLIC_ERROR"), RuntimeError("SECONDARY_CYCLIC_ERROR")
        primary.__cause__, other.__cause__ = other, primary
        def fail(study, receipt):
            raise primary
        answer = self.run_session(fail)
        self.assertEqual(answer["status"], "FAIL")
        first = answer["errors"][0]
        self.assertEqual(first["message"], "PRIMARY_CYCLIC_ERROR")
        self.assertEqual(first["cause"]["message"], "SECONDARY_CYCLIC_ERROR")
        self.assertEqual(first["cause"]["cause"]["truncated"], "EXCEPTION_REFERENCE_ALREADY_RECORDED")
        self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_error_group_duplicate_references_and_deep_causes_are_bounded(self):
        shared = ValueError("SHARED_PRIMARY")
        group = ExceptionGroup("BOTH_FAILURES", [shared, shared])
        value = audited._error(group)
        self.assertEqual(value["exceptions"][0]["message"], "SHARED_PRIMARY")
        self.assertEqual(value["exceptions"][1]["truncated"], "EXCEPTION_REFERENCE_ALREADY_RECORDED")
        primary = cursor = ValueError("FIRST_DEEP_ERROR")
        for number in range(40):
            cursor.__cause__ = ValueError(str(number))
            cursor = cursor.__cause__
        value = audited._error(primary)
        self.assertEqual(value["message"], "FIRST_DEEP_ERROR")
        for _ in range(32):
            value = value["cause"]
        self.assertEqual(value["truncated"], "EXCEPTION_DEPTH_LIMIT_32")

    def test_uncatchable_child_exit_stays_incomplete_and_inspect_is_read_only(self):
        script = """import json,os,sys
from pathlib import Path
from research.ssq_dlt_d2_forensics_evidence import audited
def stop(study,receipt): os._exit(23)
audited.audit(Path(sys.argv[1]),Path(sys.argv[2]),verifier=stop,source_provider=lambda:json.loads(sys.argv[3]))
"""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(verify.frozen_protocol.ROOT))
        child = subprocess.run([sys.executable, "-B", "-c", script, str(self.study), str(self.session), json.dumps(self.sources)],
                               env=environment, capture_output=True, timeout=30)
        self.assertEqual(child.returncode, 23, child.stderr)
        self.assertTrue((self.session / "START.json").is_file())
        self.assertTrue((self.session / "before.json").is_file())
        before = audited._snapshot(self.session)
        answer = audited.inspect(self.session)
        self.assertEqual(answer["status"], "INCOMPLETE")
        self.assertEqual(set(answer["missing"]), {"after.json", "receipt.json"})
        self.assertEqual(audited._snapshot(self.session), before)

    def test_inspect_detects_before_manifest_tampering(self):
        self.run_session()
        (self.session / "before.json").write_text("{}", encoding="utf-8")
        self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_inspect_detects_native_receipt_tampering(self):
        self.run_session()
        (self.session / "native-verification.json").write_text("{}", encoding="utf-8")
        self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_inspect_rejects_failed_receipt_relabeled_pass(self):
        (self.study / "research.sqlite3-wal").write_bytes(b"not checkpointed")
        self.run_session()
        receipt = self.load("receipt.json")
        receipt["status"] = audited.AUDITED_PASS
        (self.session / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        self.assertEqual(audited.inspect(self.session)["status"], "FAIL")

    def test_snapshot_failure_is_durable_and_verifier_is_not_run(self):
        forbidden = mock.Mock(side_effect=AssertionError("must not execute"))
        def unreadable():
            raise PermissionError("synthetic source read denied")
        answer = self.run_session(forbidden, unreadable)
        forbidden.assert_not_called()
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("synthetic source read denied", json.dumps(self.load("before.json")))
        self.assertTrue((self.session / "after.json").is_file())

    def test_native_pass_without_matching_written_receipt_is_rejected(self):
        answer = self.run_session(lambda study, receipt: {"status": audited.NATIVE_PASS})
        self.assertEqual(answer["status"], "FAIL")
        self.assertIn("NATIVE_RECEIPT_MISSING", answer["errors"][0]["message"])

    def test_production_source_closure_includes_audit_adapter_and_all_frozen_pins(self):
        sources = audited.source_snapshot()
        self.assertEqual(sources["errors"], [])
        for relative, checksum in verify.frozen_protocol.source_manifest().items():
            self.assertEqual(sources["files"][relative]["sha256"], checksum)
        for name in ("audited.py", "verify.py", "tests/test_audited.py", "tests/test_verify.py"):
            self.assertIn("research/ssq_dlt_d2_forensics_evidence/" + name, sources["files"])


if __name__ == "__main__":
    unittest.main()
