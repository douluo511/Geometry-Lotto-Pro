import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.harness_v46.audit_intake_bundle import audit_bundle
from research.harness_v46.core import MAX_RAW_SOURCE_BYTES


def make_bundle(root: Path, *, body=b"blocked HTTP 567 body", status=567):
    raw_dir = root / "raw" / "DLT" / "national"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / (hashlib.sha256(body).hexdigest() + ".bin")
    raw_path.write_bytes(body)
    rel = raw_path.relative_to(root).as_posix()
    artifact = {
        "artifact_path": rel,
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "http_status": status,
        "body_preserved": True,
    }
    bundle = {
        "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
        "official_target_admission": "BLOCKED",
        "external_tsa": "NOT_RUN",
        "formal_A": 0,
        "decision": "NO_EDGE",
        "errors": {"DLT": "SOURCE_FETCH_PARTIAL"},
        "games": {
            "DLT": {
                "status": "SOURCE_FETCH_PARTIAL",
                "official_target_admission": "BLOCKED",
                "external_tsa": "NOT_RUN",
                "formal_A": 0,
                "decision": "NO_EDGE",
                "sources": [{
                    "source_id": "national",
                    "draws": [],
                    "raw_reparse_status": "NOT_RUN_SOURCE_FETCH_FAILED",
                    "raw_artifacts": [artifact],
                }],
            },
        },
    }
    (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
    return bundle, artifact, raw_path


class IntakeBundleAuditTests(unittest.TestCase):
    def test_valid_blocked_bundle_passes_integrity_and_marks_http_failure_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bundle(root, status=567)
            report = audit_bundle(root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["artifact_records"], 1)
        self.assertEqual(report["verified_artifact_records"], 1)
        self.assertEqual(report["unique_raw_file_paths"], 1)
        self.assertEqual(report["diagnostic_non_200_responses"], 1)
        self.assertEqual(report["admission_guard"]["formal_A"], 0)
        self.assertEqual(report["admission_guard"]["official_target_admission"], "BLOCKED")

    def test_tampered_raw_bytes_fail_sha256_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, raw_path = make_bundle(root)
            raw_path.write_bytes(b"X" * len(b"blocked HTTP 567 body"))
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("RAW_ARTIFACT_SHA256_MISMATCH" in error for error in report["errors"]))

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, _ = make_bundle(root)
            artifact["artifact_path"] = "../escape.bin"
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("RAW_ARTIFACT_PATH_UNSAFE" in error for error in report["errors"]))

    def test_bundle_cannot_promote_formal_a_or_target_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, _, _ = make_bundle(root)
            bundle["formal_A"] = 1
            bundle["official_target_admission"] = "PASS"
            bundle["games"]["DLT"]["formal_A"] = 1
            bundle["games"]["DLT"]["official_target_admission"] = "PASS"
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("FORMAL_A_NOT_ZERO", report["errors"])
        self.assertIn("OFFICIAL_TARGET_ADMISSION_NOT_BLOCKED", report["errors"])
        self.assertIn("GAME_FORMAL_A_NOT_ZERO:DLT", report["errors"])
        self.assertIn("GAME_TARGET_ADMISSION_NOT_BLOCKED:DLT", report["errors"])

    def test_duplicate_retry_receipts_may_share_one_sha_addressed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, _ = make_bundle(root)
            duplicate = dict(artifact)
            bundle["games"]["DLT"]["sources"][0]["raw_artifacts"].append(duplicate)
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["artifact_records"], 2)
        self.assertEqual(report["verified_artifact_records"], 2)
        self.assertEqual(report["unique_raw_file_paths"], 1)

    def test_explicitly_unpreserved_oversized_body_is_counted_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, _ = make_bundle(root)
            artifact["body_preserved"] = False
            artifact.pop("artifact_path")
            artifact["size_bytes"] = MAX_RAW_SOURCE_BYTES + 1
            bundle["games"]["DLT"]["sources"][0]["raw_artifacts"] = [artifact]
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["unpreserved_oversized_records"], 1)
        self.assertEqual(report["verified_artifact_records"], 0)

    def test_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_bundle(tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("INTAKE_MANIFEST_MISSING", report["errors"])


if __name__ == "__main__":
    unittest.main()
