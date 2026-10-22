import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from research.harness_v46 import official_intake as oi
from research.harness_v46.audit_intake_bundle import audit_bundle, main as audit_main
from research.harness_v46.core import MAX_RAW_SOURCE_BYTES
from research.harness_v46.tests.test_official_intake import _payload


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


def make_worker_bundle(parent: Path, *, stdout=b"untrusted worker\r\n\xff",
                       stderr=b"untrusted stderr\r\n", complete=True):
    result = oi._quarantine_worker_output(
        "SSQ", "synthetic parent validation failure", stdout, stderr,
        returncode=2 if complete else None, capture_complete=complete)
    bundle = {
        "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1", "games": {"SSQ": result},
        "errors": {"SSQ": "synthetic failure"}, "formal_A": 0, "decision": "NO_EDGE",
        "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
    }
    path = oi.write_bundle(bundle, parent / "worker-evidence")
    physical = oi._physical_root(path)
    return physical.parent, json.loads(physical.read_text(encoding="utf-8"))


class IntakeBundleAuditTests(unittest.TestCase):
    def check_long_bundle_round_trip_and_tamper(self, result, *, http_count, stream_count):
        bundle = {
            "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1", "games": {"SSQ": result},
            "errors": {"SSQ": "synthetic long path fixture"},
            "formal_A": 0, "decision": "NO_EDGE", "official_target_admission": "BLOCKED",
            "external_tsa": "NOT_RUN",
        }
        # An extended temporary root also lets Windows clean up >260-character
        # children without changing registry or machine-wide path settings.
        with tempfile.TemporaryDirectory(dir=oi._physical_root(tempfile.gettempdir())) as tmp:
            destination = Path(tmp).joinpath("a" * 60, "b" * 60, "c" * 60, "d" * 60)
            manifest = oi.write_bundle(bundle, destination)
            self.assertGreater(len(str(manifest)), 260)
            self.assertFalse(str(manifest).startswith("\\\\?\\"))
            physical_manifest = oi._physical_root(manifest)
            root = physical_manifest.parent
            saved = json.loads(physical_manifest.read_text(encoding="utf-8"))
            saved_result = saved["games"]["SSQ"]
            if stream_count:
                relative = saved_result["worker_output_capture"]["streams"][0]["artifact_path"]
            else:
                relative = saved_result["sources"][0]["raw_artifacts"][0]["artifact_path"]
            self.assertFalse(Path(relative).is_absolute())
            self.assertNotIn("\\\\?\\", relative)
            target = root / relative
            self.assertGreater(len(str(target)), 260)
            self.assertEqual(audit_main(["--bundle-dir", str(manifest.parent)]), 0)
            receipt_path = root / "intake-audit.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["verified_artifact_records"], http_count)
            self.assertEqual(receipt["verified_worker_output_stream_records"], stream_count)
            old_manifest, old_receipt = physical_manifest.read_bytes(), receipt_path.read_bytes()
            with self.assertRaises(FileExistsError):
                oi.write_bundle(bundle, manifest.parent)
            with self.assertRaises(FileExistsError):
                audit_main(["--bundle-dir", str(manifest.parent)])
            self.assertEqual(physical_manifest.read_bytes(), old_manifest)
            self.assertEqual(receipt_path.read_bytes(), old_receipt)
            target.write_bytes(b"X" * len(target.read_bytes()))
            tampered = audit_bundle(manifest.parent)
            self.assertEqual(tampered["status"], "FAIL")
            self.assertTrue(any("MISMATCH" in error for error in tampered["errors"]))

    def test_long_absolute_diagnostic_paths_support_write_cli_audit_and_tamper(self):
        result = oi._quarantine_worker_output("SSQ", "synthetic long path failure",
                                             b"worker stdout\r\n", b"stderr\xff",
                                             returncode=2, capture_complete=True)
        self.check_long_bundle_round_trip_and_tamper(result, http_count=0, stream_count=2)

    def test_long_absolute_raw_paths_support_write_cli_audit_and_tamper(self):
        result = oi._quarantine_second_process_replay(
            oi.validate_worker_payload(_payload("SSQ")), "synthetic long path fixture")
        self.check_long_bundle_round_trip_and_tamper(result, http_count=2, stream_count=0)

    def test_diagnostic_only_capture_passes_byte_audit_without_http_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = make_worker_bundle(Path(tmp))
            before = {p.relative_to(root).as_posix(): p.read_bytes()
                      for p in root.rglob("*") if p.is_file()}
            report = audit_bundle(root)
            after = {p.relative_to(root).as_posix(): p.read_bytes()
                     for p in root.rglob("*") if p.is_file()}
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(before, after)
        self.assertEqual(report["artifact_records"], 0)
        self.assertEqual(report["verified_artifact_records"], 0)
        self.assertEqual(report["worker_output_stream_records"], 2)
        self.assertEqual(report["verified_worker_output_stream_records"], 2)
        self.assertEqual(report["http_raw_evidence_status"],
                         "NOT_PRESENT_OR_UNVALIDATED_PROCESS_OUTPUT_ONLY")
        self.assertEqual(report["admission_guard"]["formal_A"], 0)
        self.assertEqual(report["admission_guard"]["decision"], "NO_EDGE")

    def test_worker_capture_byte_tamper_and_missing_file_fail_audit(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                stream = bundle["games"]["SSQ"]["worker_output_capture"]["streams"][0]
                saved = root / stream["artifact_path"]
                if missing:
                    saved.unlink()
                else:
                    saved.write_bytes(b"X" * stream["size_bytes"])
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertTrue(any("WORKER_OUTPUT_" in error for error in report["errors"]))

    def test_worker_capture_wrong_game_stream_sha_and_traversal_paths_fail(self):
        for path in ("../escape.bin", "diagnostics/DLT/worker/stdout/" + "0" * 64 + ".bin",
                     "diagnostics/SSQ/worker/stderr/" + "0" * 64 + ".bin"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                bundle["games"]["SSQ"]["worker_output_capture"]["streams"][0]["artifact_path"] = path
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_NONCANONICAL_PATH:SSQ:stdout", report["errors"])

    def test_worker_capture_guard_rejects_claims_and_non_integer_zero_counts(self):
        replacements = {
            "source_origin_authenticity": "VERIFIED",
            "publication_time_authenticity": "VERIFIED",
            "history_validation_tier": "VERIFIED_HISTORY",
            "official_history_admission": "SHADOW_HISTORY_ONLY",
            "raw_byte_sha_validation": "PASS",
            "source_count": False,
            "raw_artifact_count": 0.0,
            "consensus_draw_count": False,
            "primary_history_draw_count": 0.0,
            "consensus_draws": [{"issue": "untrusted"}],
        }
        for field, value in replacements.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                bundle["games"]["SSQ"][field] = value
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_QUARANTINE_GUARD_INVALID:SSQ", report["errors"])

    def test_worker_capture_cannot_attach_http_records_through_diagnostic_aliases(self):
        for field in ("unadmitted_raw_artifacts", "transport_failures"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                raw = b"plausible synthetic HTTP body"
                sha = hashlib.sha256(raw).hexdigest()
                rel = f"raw/SSQ/national/{sha}.bin"
                saved = root / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(raw)
                bundle["games"]["SSQ"][field] = [{
                    "source_id": "national", "artifact_path": rel,
                    "raw_sha256": sha, "size_bytes": len(raw), "http_status": 200,
                }]
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_QUARANTINE_GUARD_INVALID:SSQ", report["errors"])

    def test_removed_worker_capture_cannot_launder_failed_stdout_as_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, bundle = make_worker_bundle(Path(tmp))
            result = bundle["games"]["SSQ"]
            capture = result.pop("worker_output_capture")
            raw = (root / capture["streams"][0]["artifact_path"]).read_bytes()
            for stream in capture["streams"]:
                (root / stream["artifact_path"]).unlink()
            sha = hashlib.sha256(raw).hexdigest()
            rel = f"raw/SSQ/national/{sha}.bin"
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            result.update(source_count=1, raw_artifact_count=1, sources=[{
                "source_id": "national", "raw_reparse_status": "PASS",
                "draws": [{"issue": "invented worker claim"}],
                "raw_artifacts": [{"artifact_path": rel, "raw_sha256": sha,
                                   "size_bytes": len(raw), "http_status": 200}],
            }])
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("WORKER_OUTPUT_CAPTURE_MISSING:SSQ", report["errors"])
        self.assertIn("WORKER_OUTPUT_QUARANTINE_GUARD_INVALID:SSQ", report["errors"])
        self.assertEqual(report["artifact_records"], 0)
        self.assertEqual(report["verified_artifact_records"], 0)

    def test_worker_capture_unreferenced_output_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = make_worker_bundle(Path(tmp))
            extra = root / "diagnostics" / "unlisted.bin"
            extra.write_bytes(b"unlisted diagnostic")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNREFERENCED_WORKER_OUTPUT_FILE:diagnostics/unlisted.bin", report["errors"])

    def test_worker_capture_checks_every_parent_directory_for_symlinks(self):
        for relative in ("diagnostics", "diagnostics/SSQ", "diagnostics/SSQ/worker",
                         "diagnostics/SSQ/worker/stdout"):
            with self.subTest(parent=relative), tempfile.TemporaryDirectory() as tmp:
                root, _ = make_worker_bundle(Path(tmp))
                original = Path.is_symlink
                def is_symlink(path):
                    return path == root / relative or original(path)
                with patch.object(Path, "is_symlink", is_symlink):
                    report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_FILE_UNSAFE_OR_MISSING:SSQ:stdout", report["errors"])

    def test_worker_capture_rejects_reparse_points_at_every_path_component(self):
        relatives = ("diagnostics", "diagnostics/SSQ", "diagnostics/SSQ/worker",
                     "diagnostics/SSQ/worker/stdout")
        for relative in relatives:
            with self.subTest(parent=relative), tempfile.TemporaryDirectory() as tmp:
                root, _ = make_worker_bundle(Path(tmp))
                original_lstat = Path.lstat
                def lstat(path):
                    actual = original_lstat(path)
                    if path == root / relative:
                        return SimpleNamespace(st_mode=actual.st_mode,
                                               st_file_attributes=0x400)
                    return actual
                with patch.object(Path, "lstat", lstat):
                    # is_symlink remains False for the simulated Windows junction.
                    self.assertFalse((root / relative).is_symlink())
                    report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_FILE_UNSAFE_OR_MISSING:SSQ:stdout", report["errors"])
                self.assertEqual(report["verified_worker_output_stream_records"],
                                 1 if relative.endswith("stdout") else 0)

    def test_original_raw_evidence_rejects_reparse_points_at_every_path_component(self):
        for relative in ("raw", "raw/DLT", "raw/DLT/national"):
            with self.subTest(parent=relative), tempfile.TemporaryDirectory() as tmp:
                root = oi._physical_root(tmp)
                make_bundle(root)
                original_lstat = Path.lstat
                def lstat(path):
                    actual = original_lstat(path)
                    if path == root / relative:
                        return SimpleNamespace(st_mode=actual.st_mode,
                                               st_file_attributes=0x400)
                    return actual
                with patch.object(Path, "lstat", lstat):
                    report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["verified_artifact_records"], 0)
                self.assertTrue(any("REPARSE_POINT" in error for error in report["errors"]))

    def test_worker_capture_malformed_stream_names_or_missing_status_fail_closed(self):
        for name in ([], {}, None, "stderr"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                bundle["games"]["SSQ"]["worker_output_capture"]["streams"][0]["stream"] = name
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_STREAM_SET_INVALID:SSQ", report["errors"])

    def test_incomplete_worker_capture_reports_missing_stream_without_inventing_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = make_worker_bundle(Path(tmp), stdout=b"partial output", stderr=None,
                                         complete=False)
            report = audit_bundle(root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verified_worker_output_stream_records"], 1)
        self.assertEqual(report["unavailable_worker_output_streams"], 1)
        self.assertEqual(report["incomplete_worker_output_games"], ["SSQ"])
        self.assertEqual(report["artifact_records"], 0)
        self.assertTrue(report["worker_output_limitations"])

    def test_worker_capture_non_string_byte_representation_returns_fail_receipt(self):
        for value in ([], {}, None):
            with self.subTest(representation=value), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp))
                bundle["games"]["SSQ"]["worker_output_capture"]["streams"][0]["byte_representation"] = value
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_STREAM_SCHEMA_INVALID:SSQ:stdout", report["errors"])

    def test_no_worker_output_never_certifies_preserved_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = make_worker_bundle(Path(tmp), stdout=None, stderr=None, complete=False)
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["artifact_records"], 0)
        self.assertEqual(report["verified_worker_output_stream_records"], 0)
        self.assertEqual(report["unavailable_worker_output_streams"], 2)
        self.assertIn("NO_RAW_ARTIFACT_RECORDS_FOUND", report["errors"])

    def test_not_captured_worker_stream_cannot_claim_bytes_or_complete_capture(self):
        for complete in (False, True):
            with self.subTest(complete=complete), tempfile.TemporaryDirectory() as tmp:
                root, bundle = make_worker_bundle(Path(tmp), stdout=b"partial", stderr=None,
                                                  complete=False)
                capture = bundle["games"]["SSQ"]["worker_output_capture"]
                capture["capture_complete"] = complete
                capture["returncode"] = 2 if complete else None
                if not complete:
                    capture["streams"][1]["size_bytes"] = 0
                (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
                report = audit_bundle(root)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WORKER_OUTPUT_NOT_CAPTURED_CONFLICT:SSQ:stderr", report["errors"])

    def test_valid_blocked_bundle_passes_integrity_and_marks_http_failure_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bundle(root, status=567)
            report = audit_bundle(root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["auditor_source_sha256"]), 64)
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

    def test_explicitly_unpreserved_oversized_body_cannot_pass_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, _ = make_bundle(root)
            artifact["body_preserved"] = False
            artifact.pop("artifact_path")
            artifact["size_bytes"] = MAX_RAW_SOURCE_BYTES + 1
            bundle["games"]["DLT"]["sources"][0]["raw_artifacts"] = [artifact]
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["unpreserved_oversized_records"], 1)
        self.assertEqual(report["verified_artifact_records"], 0)
        self.assertTrue(any("RAW_ARTIFACT_UNPRESERVED_OVERSIZED" in x for x in report["errors"]))

    def test_correct_sha_but_wrong_game_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, raw_path = make_bundle(root)
            swapped = root / "raw" / "SSQ" / "national" / raw_path.name
            swapped.parent.mkdir(parents=True, exist_ok=True)
            swapped.write_bytes(raw_path.read_bytes())
            artifact["artifact_path"] = swapped.relative_to(root).as_posix()
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("RAW_ARTIFACT_NONCANONICAL_SOURCE_PATH" in x for x in report["errors"]))

    def test_correct_sha_but_unexpected_source_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, _, _ = make_bundle(root)
            bundle["games"]["DLT"]["sources"][0]["source_id"] = "hebei"
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("RAW_ARTIFACT_SOURCE_ID_INVALID:DLT:hebei", report["errors"])

    def test_correct_sha_but_wrong_sha_named_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, artifact, raw_path = make_bundle(root)
            wrongly_named = raw_path.with_name("f" * 64 + ".bin")
            wrongly_named.write_bytes(raw_path.read_bytes())
            artifact["artifact_path"] = wrongly_named.relative_to(root).as_posix()
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("RAW_ARTIFACT_NONCANONICAL_SOURCE_PATH" in x for x in report["errors"]))

    def test_unlisted_raw_binary_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bundle(root)
            extra = root / "raw" / "DLT" / "national" / ("f" * 64 + ".bin")
            extra.write_bytes(b"unlisted raw bytes")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("UNREFERENCED_RAW_ARTIFACT" in x for x in report["errors"]))

    def test_unlisted_nonbinary_file_in_raw_tree_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bundle(root)
            extra = root / "raw" / "DLT" / "national" / "unlisted-receipt.txt"
            extra.write_text("untracked content", encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("UNREFERENCED_RAW_ARTIFACT" in x for x in report["errors"]))

    def test_existing_audit_receipt_must_not_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_bundle(root)
            audit_path = root / "intake-audit.json"
            audit_path.write_text('{"original":true}', encoding="utf-8")
            with self.assertRaises(FileExistsError):
                audit_main(["--bundle-dir", str(root)])
            self.assertEqual(audit_path.read_text(encoding="utf-8"), '{"original":true}')

    def test_empty_bundle_cannot_pass_integrity_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = {
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "official_target_admission": "BLOCKED",
                "external_tsa": "NOT_RUN",
                "formal_A": 0,
                "decision": "NO_EDGE",
                "games": {},
            }
            (root / "intake.json").write_text(json.dumps(bundle), encoding="utf-8")
            report = audit_bundle(root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("GAMES_EMPTY", report["errors"])
        self.assertIn("NO_RAW_ARTIFACT_RECORDS_FOUND", report["errors"])

    def test_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_bundle(tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("INTAKE_MANIFEST_MISSING", report["errors"])


if __name__ == "__main__":
    unittest.main()
