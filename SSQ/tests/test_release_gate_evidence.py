from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from derive_gate_status import (  # noqa: E402
    REQUIRED_EXE_CHECKS, _raw_status_allowed, _verify_gui_evidence, derive,
)
from release_gate_22 import HARD_GATES  # noqa: E402


class ReleaseGateEvidenceTests(unittest.TestCase):
    @staticmethod
    def complete_exe_checks() -> dict[str, dict[str, object]]:
        return {name: {"status": "PASS", "exit_code": 0,
                       "exe_hash_matches": True} for name in REQUIRED_EXE_CHECKS}

    def test_gui_v2_claim_without_backend_ledgers_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"exact candidate")
            rows = []
            for index, (control, operation) in enumerate(
                ((101, "predict"), (102, "update"), (103, "repair"), (104, "audit")), 1
            ):
                leaf = f"physical-gui-run-{index:032x}"
                run_dir = root / leaf
                run_dir.mkdir()
                before_text = "before"
                after_text = "Alpha Beta fabricated"
                (run_dir / "gui_before.txt").write_text(before_text, encoding="utf-8")
                (run_dir / "gui_after.txt").write_text(after_text, encoding="utf-8")
                before_hash = hashlib.sha256(before_text.encode()).hexdigest()
                after_hash = hashlib.sha256(after_text.encode()).hexdigest()
                rows.append({
                    "button_index": index, "control_id": control,
                    "operation": operation, "status": "PASS", "control_class": "BUTTON",
                    "control_name": operation, "process_id": 123,
                    "control_verified": True, "physical_click_verified": True,
                    "output_verified": True, "backend_effect_verified": True,
                    "before_output_sha256": before_hash,
                    "after_output_sha256": after_hash,
                    "before_output_artifact": f"{leaf}/gui_before.txt",
                    "after_output_artifact": f"{leaf}/gui_after.txt",
                    "before_output_artifact_sha256": before_hash,
                    "after_output_artifact_sha256": after_hash,
                    "output_markers": ["Alpha", "Beta"], "after_status": "Ready",
                    "data_dir": leaf,
                    "displayed_backend_token": "fabricated",
                    "backend_effect": {"status": "PASS", "display_token": "fabricated"},
                })
            report = {
                "schema": "physical-gui-click-smoke-v2", "status": "PASS",
                "exe": exe.name, "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "github_sha": "a" * 40, "github_run_id": "12345",
                "tested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "coordinate_fallback": False, "visual_hash_as_proof": False,
                "buttons": rows,
            }
            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}):
                with self.assertRaises(ValueError):
                    _verify_gui_evidence(report, root, exe, True)

    def test_failed_source_body_is_allowed_only_as_failed_receipt(self) -> None:
        # A CWL 403 body must remain hash-checkable evidence during a valid
        # Shanghai+Hebei fallback, but it can never be a PASS-source page.
        self.assertTrue(_raw_status_allowed(403, "FAIL"))
        self.assertTrue(_raw_status_allowed(200, "FAIL"))  # parse/schema failure
        self.assertTrue(_raw_status_allowed(200, "PASS"))
        self.assertFalse(_raw_status_allowed(403, "PASS"))
        self.assertFalse(_raw_status_allowed(200, "PENDING"))

    def test_missing_evidence_never_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = derive(root, root / "missing.exe")
        self.assertEqual(set(report["gates"]), set(HARD_GATES))
        self.assertTrue(all(value == "PENDING" for value in report["gates"].values()))

    def test_gui_report_without_exact_acceptance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "physical_gui_click.json").write_text(
                json.dumps({"schema": "physical-gui-click-smoke-v2", "status": "PASS"}),
                encoding="utf-8",
            )
            report = derive(root, root / "missing.exe")
        self.assertEqual(report["gates"]["gui_smoke"], "FAIL")

    def test_fabricated_acceptance_cannot_replace_exe_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(
                json.dumps({
                    "runner_os": "Windows", "artifact": "candidate.exe",
                    "sha256": "0" * 64, "windows_exact_exe_acceptance": "PASS",
                    "final_release_gate": "PASS", "hard_fail_count": 0,
                    "checks": {"self": {"status": "PASS", "exit_code": 0, "exe_hash_matches": True}},
                }), encoding="utf-8",
            )
            report = derive(root, root / "candidate.exe")
        for gate in ("windows_build", "exact_exe", "same_hash", "self_test", "real_network"):
            self.assertEqual(report["gates"][gate], "FAIL", gate)

    def test_exact_artifact_proves_only_narrow_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            acceptance = {
                "runner_os": "Windows", "artifact": exe.name, "sha256": digest,
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "final_release_gate": "PENDING",
                "hard_fail_count": 0,
                "checks": self.complete_exe_checks(),
            }
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(
                json.dumps(acceptance), encoding="utf-8",
            )
            (root / "physical_gui_click.json").write_text(json.dumps({
                "status": "PASS", "exe": exe.name,
                "buttons": [{"status": "PASS", "visual_changed": True} for _ in range(4)],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}):
                report = derive(root, exe)
        for gate in ("windows_build", "exact_exe", "self_test"):
            self.assertEqual(report["gates"][gate], "PASS", gate)
        self.assertEqual(report["gates"]["same_hash"], "FAIL")
        self.assertEqual(report["gates"]["real_network"], "FAIL")
        self.assertEqual(report["gates"]["gui_smoke"], "FAIL")
        for gate in ("business_content", "contract_test", "fault_injection"):
            self.assertEqual(report["gates"][gate], "PENDING", gate)

    def test_partial_checks_or_premature_final_claim_do_not_prove_exact_exe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            report_path = root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json"
            base = {
                "runner_os": "Windows", "artifact": exe.name,
                "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "hard_fail_count": 0,
                "checks": self.complete_exe_checks(),
            }
            for final_claim, checks in (
                ("PASS", self.complete_exe_checks()),
                ("PENDING", {"self": self.complete_exe_checks()["self"]}),
            ):
                with self.subTest(final_claim=final_claim, checks=len(checks)):
                    report_path.write_text(json.dumps({**base,
                        "final_release_gate": final_claim, "checks": checks}),
                        encoding="utf-8")
                    with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40,
                                               "GITHUB_RUN_ID": "12345"}):
                        result = derive(root, exe)
                    self.assertEqual(result["gates"]["windows_build"], "FAIL")
                    self.assertEqual(result["gates"]["exact_exe"], "FAIL")
                    self.assertEqual(result["gates"]["same_hash"], "FAIL")

    def test_raw_receipts_without_independent_reparse_remain_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(json.dumps({
                "runner_os": "Windows", "artifact": exe.name, "sha256": digest,
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "final_release_gate": "PENDING",
                "hard_fail_count": 0,
                "checks": self.complete_exe_checks(),
            }), encoding="utf-8")
            with (patch.dict(os.environ, {"GITHUB_SHA": "a" * 40,
                                           "GITHUB_RUN_ID": "12345"}),
                  patch("derive_gate_status._verify_live_evidence",
                        return_value={"raw_response_count": 24})):
                report = derive(root, exe)
        self.assertEqual(report["gates"]["real_network"], "PENDING")
        self.assertEqual(report["gates"]["same_hash"], "PENDING")
        self.assertEqual(report["proofs"]["real_network"]["canonical_reparse"], "PENDING")

    def test_hand_authored_all_pass_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            acceptance = root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json"
            acceptance.write_text(json.dumps({
                "sha256": digest, "hard_fail_count": 0, "final_release_gate": "PASS",
            }), encoding="utf-8")
            gates = root / "mother-gates.json"
            gates.write_text(json.dumps({"gates": {gate: "PASS" for gate in HARD_GATES}}), encoding="utf-8")
            report = root / "final.json"
            result = subprocess.run([
                sys.executable, "-B", str(TOOLS / "release_gate_22.py"),
                "--gate-input", str(gates), "--acceptance", str(acceptance),
                "--exe", str(exe), "--report", str(report),
            ], capture_output=True, text=True)
            final = json.loads(report.read_text(encoding="utf-8"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(final["final_gate"], "FAIL")
        self.assertEqual(final["gate_input_integrity"], "FAIL")
        self.assertIn("gate_input_integrity", final["failures"])


if __name__ == "__main__":
    unittest.main()
