"""Synthetic adversarial fixtures ONLY; these tests are not Windows/network acceptance."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_status", MODULE_DIR / "validate_status.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
STAMP = "2026-09-30T11:59:00Z"
COMMIT = "a" * 40
CANDIDATE = "synthetic-unit-test-candidate"


def raw(value):
    return json.dumps(value, sort_keys=True).encode("utf-8")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schema = (MODULE_DIR / "project-status-v2.schema.json").read_bytes()
        self.report = json.loads((MODULE_DIR / "project-status-v2.template.json").read_bytes())
        self.baseline = {
            "schema_version": "1.0", "project_id": "test", "baseline_id": "b1",
            "frozen_at_utc": "2026-09-30T10:00:00Z", "max_evidence_age_seconds": 3600,
            "max_report_age_seconds": 3600,
            "criteria": [
                {"criterion_id": "eng", "stream": "engineering", "weight": 100, "mandatory": True,
                 "allowed_evidence_modes": ["OBSERVED", "UNIT_FIXTURE", "CONTROLLED_FAULT"],
                 "required_evidence_kinds": ["exact_exe", "real_network", "contract"]},
                {"criterion_id": "biz", "stream": "business", "weight": 100, "mandatory": True,
                 "allowed_evidence_modes": ["OBSERVED"], "required_evidence_kinds": ["business_result"]}],
            "entry_points": [{"entry_id": "update", "kind": "button", "requirement_id": "req1",
                              "required_test_kinds": ["contract"], "required_effect_kinds": ["real_network"]}],
            "network_sources": [{"source_id": "official", "source_uri": "https://example.invalid/data",
                                 "source_role": "primary", "required_success": True}]}
        self.report.update(project_id="test", name="Synthetic test only", updated_at_utc=STAMP)
        self.report["baseline"].update(id="b1", uri="baseline.json", frozen_at_utc=self.baseline["frozen_at_utc"],
                                       engineering_total_weight=100, business_total_weight=100)
        exe_hash = self.asset("binary.exe", b"NOT AN EXECUTABLE; UNIT FIXTURE ONLY")
        network_hash = self.asset("response.raw", b"TEST DATA ONLY")
        self.asset("trace.txt", b"SYNTHETIC TEST LOG; NO REAL EXECUTION")
        self.report["candidate"].update(
            id=CANDIDATE, commit_sha=COMMIT, tree_sha="b" * 40, config_sha256="c" * 64,
            dependencies_sha256="d" * 64, data_sha256="e" * 64, model_sha256="f" * 64,
            build_run_url="https://example.invalid/run/1", windows_environment="synthetic fixture",
            tested_exe_sha256=exe_hash, release_exe_sha256=exe_hash, release_artifact_uri="binary.exe",
            release_manifest_sha256="1" * 64, same_hash_verified=True)
        self.report["scores"] = {key: 100 for key in self.report["scores"]}
        self.add_evidence("x", "exact_exe", {"exe_path": "binary.exe", "exe_sha256": exe_hash})
        self.add_evidence("n", "real_network", {"attempt_id": "a1", "source_id": "official",
            "source_uri": "https://example.invalid/data", "raw_response_sha256": network_hash})
        self.add_evidence("u", "contract", {}, mode="UNIT_FIXTURE")
        self.add_evidence("b", "business_result", {})
        self.report["checks"] = [{"check_id": cid, "stream": stream, "criterion_id": cid,
            "mandatory": True, "status": "PASS", "candidate_id": CANDIDATE,
            "evidence_ids": ids, "valid_until_utc": "2026-09-30T12:30:00Z"}
            for cid, stream, ids in [("eng", "engineering", ["x", "n", "u"]), ("biz", "business", ["b"])]]
        self.report["entry_points"] = [{"entry_id": "update", "kind": "button", "requirement_id": "req1",
            "candidate_id": CANDIDATE, "implementation_ref": "src/update.py:update", "production_call_path": "UI -> service -> client",
            "real_input_or_data_ref": "response.raw", "test_evidence_ids": ["u"], "effect_evidence_ids": ["n"], "status": "PASS"}]
        implementation_hash = self.asset("source.txt", b"SYNTHETIC SOURCE ASSET ONLY")
        output_hash = self.asset("output.txt", b"SYNTHETIC OUTPUT ASSET ONLY")
        binding = {key: self.report["entry_points"][0][key] for key in (
            "entry_id", "requirement_id", "implementation_ref", "production_call_path", "real_input_or_data_ref")}
        binding.update(exe_sha256=exe_hash, input_sha256=network_hash,
                       implementation_asset={"path": "source.txt", "sha256": implementation_hash},
                       output_asset={"path": "output.txt", "sha256": output_hash})
        self.modify_receipt("n", lambda r: r["payload"].update(entry_bindings=[binding]))
        self.report["network_attempts"] = [{"attempt_id": "a1", "candidate_id": CANDIDATE,
            "source_id": "official", "source_role": "primary", "observed_at_utc": STAMP,
            "status": "PASS", "raw_response_uri": "response.raw", "raw_response_sha256": network_hash,
            "schema_status": "PASS", "content_status": "PASS", "freshness_status": "PASS",
            "conflict_status": "PASS", "failure_detail": None}]

    def asset(self, name, content):
        (self.root / name).write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def add_evidence(self, eid, kind, payload, mode="OBSERVED"):
        record = {"evidence_id": eid, "candidate_id": CANDIDATE, "kind": kind,
                  "collected_at_utc": STAMP, "environment": "synthetic unit test",
                  "source_uri": "https://example.invalid/tests", "artifact_uri": eid + ".json",
                  "assertions": ["SYNTHETIC FIXTURE; never evidence of real acceptance"], "status": "PASS"}
        receipt = {key: record[key] for key in ("evidence_id", "candidate_id", "kind", "collected_at_utc", "environment", "assertions", "status")}
        receipt.update(format="acceptance-evidence/1", commit_sha=COMMIT,
                       candidate_fingerprint=validator.candidate_fingerprint(self.report["candidate"]), mode=mode, payload=payload,
                       assets=[{"path": "trace.txt", "sha256": hashlib.sha256((self.root / "trace.txt").read_bytes()).hexdigest()}])
        record["artifact_sha256"] = self.asset(eid + ".json", raw(receipt))
        self.report["evidence"].append(record)

    def modify_receipt(self, eid, change):
        path = self.root / (eid + ".json")
        data = json.loads(path.read_bytes())
        change(data)
        sha = self.asset(eid + ".json", raw(data))
        next(e for e in self.report["evidence"] if e["evidence_id"] == eid)["artifact_sha256"] = sha

    def audit(self, report_raw=None, baseline_raw=None, approved=None, schema=None):
        baseline_raw = baseline_raw if baseline_raw is not None else raw(self.baseline)
        return validator.preflight(report_raw if report_raw is not None else raw(self.report), baseline_raw,
            approved if approved is not None else hashlib.sha256(baseline_raw).hexdigest(),
            schema if schema is not None else self.schema, self.root, CANDIDATE, COMMIT, now=NOW)

    def assert_rejected(self, outcome=None):
        outcome = outcome or self.audit()
        self.assertIn(outcome["status"], ("FAIL", "BLOCKED"), outcome)
        self.assertFalse(outcome["release_authorized"])

    def test_consistent_synthetic_fixture_only_passes_preflight_never_release(self):
        outcome = self.audit()
        self.assertEqual("PASS", outcome["status"], outcome)
        self.assertEqual("NOT_CERTIFIED", outcome["final_gate"])
        self.assertFalse(outcome["release_authorized"])

    def test_default_incomplete_report_is_blocked_or_failed(self):
        self.assert_rejected(self.audit(report_raw=(MODULE_DIR / "project-status-v2.template.json").read_bytes()))

    def test_unfrozen_default_baseline_blocks(self):
        outcome = self.audit(baseline_raw=(MODULE_DIR / "baseline.template.json").read_bytes())
        self.assertEqual("BLOCKED", outcome["status"])

    def test_unapproved_baseline_digest(self):
        self.assert_rejected(self.audit(approved="0" * 64))

    def test_missing_approval_blocks(self):
        self.assertEqual("BLOCKED", self.audit(approved="")["status"])

    def test_duplicate_json_keys(self):
        self.assert_rejected(self.audit(report_raw=b'{"schema_version":"2.1","schema_version":"2.1"}'))

    def test_nan_infinity_and_overflow(self):
        for value in (b"NaN", b"Infinity", b"-Infinity", b"1e9999"):
            with self.subTest(value=value):
                self.assert_rejected(self.audit(report_raw=b'{"x":' + value + b'}'))

    def test_wrong_candidate_every_reference(self):
        for section in ("checks", "evidence", "entry_points", "network_attempts"):
            original = self.report[section][0]["candidate_id"]
            self.report[section][0]["candidate_id"] = "other"
            self.assert_rejected()
            self.report[section][0]["candidate_id"] = original

    def test_missing_and_duplicate_inventories(self):
        for section in ("checks", "entry_points", "evidence", "network_attempts"):
            original = copy.deepcopy(self.report[section])
            self.report[section] = original + [original[0]]
            self.assert_rejected()
            self.report[section] = []
            self.assert_rejected()
            self.report[section] = original

    def test_baseline_duplicate_and_shrunken_denominator(self):
        self.baseline["criteria"].append(copy.deepcopy(self.baseline["criteria"][0]))
        self.assert_rejected()
        self.baseline["criteria"].pop()
        self.report["baseline"]["engineering_total_weight"] = 1
        self.assert_rejected()

    def test_unresolved_evidence(self):
        self.report["checks"][0]["evidence_ids"] = ["not-there"]
        self.assert_rejected()

    def test_tampered_file(self):
        (self.root / "trace.txt").write_bytes(b"tampered")
        self.assert_rejected()

    def test_path_escape_and_remote_or_windows_paths(self):
        for path in ("../secret", "/etc/passwd", "C:/Windows/file", "folder\\file", "https://example.invalid/file", "a//b", "./trace.txt", "trace.txt:ads"):
            with self.subTest(path=path):
                self.report["evidence"][0]["artifact_uri"] = path
                self.assert_rejected()

    def test_bad_and_future_and_expired_dates(self):
        for stamp in ("2026-02-30T11:00:00Z", "2026-09-30T13:00:00Z", "2026-09-30T10:00:01Z", "2026-09-30T11:00:00+00:00"):
            with self.subTest(stamp=stamp):
                self.report["evidence"][0]["collected_at_utc"] = stamp
                self.assert_rejected()

    def test_expired_check(self):
        self.report["checks"][0]["valid_until_utc"] = "2026-09-30T12:00:00Z"
        self.assert_rejected()

    def test_false_same_hash(self):
        self.report["candidate"]["tested_exe_sha256"] = "0" * 64
        self.assert_rejected()

    def test_false_percentages(self):
        self.report["scores"]["overall_pct"] = 99
        self.assert_rejected()

    def test_each_nonpass_is_zero_never_counted(self):
        for state in ("PENDING", "WARNING", "FAIL", "BLOCKED", "UNAVAILABLE", "UNKNOWN", "SKIPPED"):
            with self.subTest(state=state):
                self.report["checks"][0]["status"] = state
                outcome = self.audit()
                self.assert_rejected(outcome)
                self.assertEqual(0, outcome["computed_scores"]["engineering_pct"])

    def test_production_evidence_cannot_be_mock(self):
        self.modify_receipt("n", lambda r: r.update(mode="UNIT_FIXTURE"))
        self.assert_rejected()

    def test_fault_contract_evidence_is_permitted_but_not_production_effect(self):
        self.modify_receipt("u", lambda r: r.update(mode="CONTROLLED_FAULT"))
        self.assertEqual("PASS", self.audit()["status"])
        self.report["entry_points"][0]["effect_evidence_ids"] = ["u"]
        self.assert_rejected()

    def test_failed_primary_preserved_with_approved_successful_fallback(self):
        self.baseline["network_sources"][0].update(source_role="fallback")
        self.report["network_attempts"][0]["source_role"] = "fallback"
        self.baseline["network_sources"].append({"source_id": "primary", "source_uri": "https://example.invalid/primary",
                                                 "source_role": "primary", "required_success": False})
        failed = copy.deepcopy(self.report["network_attempts"][0])
        failed.update(attempt_id="failed", source_id="primary", source_role="primary", status="FAIL",
                      schema_status="FAIL", content_status="FAIL", freshness_status="FAIL", conflict_status="UNKNOWN",
                      failure_detail="HTTP 403 synthetic test")
        self.report["network_attempts"].append(failed)
        self.assertEqual("PASS", self.audit()["status"], self.audit())
        self.report["checks"][0]["evidence_ids"] = ["failed"]
        self.assert_rejected()

    def test_receipt_wrong_commit(self):
        self.modify_receipt("x", lambda r: r.update(commit_sha="e" * 40))
        self.assert_rejected()

    def test_config_change_invalidates_existing_evidence(self):
        self.report["candidate"]["config_sha256"] = "0" * 64
        self.assert_rejected()

    def test_other_entry_effect_cannot_be_reused(self):
        self.modify_receipt("n", lambda r: r["payload"]["entry_bindings"][0].update(entry_id="other"))
        self.assert_rejected()

    def test_entry_placeholder_or_missing_source_asset_rejected(self):
        self.report["entry_points"][0]["implementation_ref"] = "TODO"
        self.assert_rejected()
        self.report["entry_points"][0]["implementation_ref"] = "src/update.py:update"
        (self.root / "source.txt").unlink()
        self.assert_rejected()

    def test_entry_effect_must_bind_same_exact_exe(self):
        self.modify_receipt("n", lambda r: r["payload"]["entry_bindings"][0].update(exe_sha256="0" * 64))
        self.assert_rejected()

    def test_bad_status_schema_does_not_traceback(self):
        self.assert_rejected(self.audit(schema=b'{"type":3}'))

    def test_cli_missing_argument_is_json_nonzero_without_traceback(self):
        completed = subprocess.run([sys.executable, str(MODULE_DIR / "validate_status.py")], capture_output=True, text=True)
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("FAIL", json.loads(completed.stdout)["status"])
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
