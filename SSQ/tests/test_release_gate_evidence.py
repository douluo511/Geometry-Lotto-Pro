from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "SSQ"))
from derive_gate_status import (  # noqa: E402
    REQUIRED_EXE_CHECKS, _raw_status_allowed, _reparse_manifest,
    _verify_gui_evidence, _verify_reversal_contract, derive,
)
from release_gate_22 import HARD_GATES  # noqa: E402
from glp.constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL  # noqa: E402
from glp.sources import PARSER_VERSION  # noqa: E402


def synthetic_source_bundle(root: Path) -> tuple[dict, list[dict]]:
    """Deterministic contract bytes only; never a live-network acceptance run."""
    day = datetime.now(timezone.utc).date().isoformat()
    issue = f"{day[:4]}001"
    draw = {"issue": issue, "draw_date": day,
            "front": [1, 2, 3, 4, 5, 6], "back": [7]}
    national_raw = json.dumps({"state": 0, "pageNum": 1, "result": [{
        "code": issue, "date": day, "red": "01,02,03,04,05,06", "blue": "07",
    }]}).encode("utf-8")
    shanghai_raw = (
        f"<table><tr><td>{issue}</td><td>{day}</td>"
        "<td>010203040506</td><td>07</td></tr></table>"
    ).encode("utf-8")
    params = {
        "name": "ssq", "issueCount": "", "issueStart": "", "issueEnd": "",
        "dayStart": "", "dayEnd": "", "pageNo": "1", "pageSize": "100",
        "week": "", "systemType": "PC",
    }
    urls = {
        "official_cwl_L0": (NATIONAL_URL, f"{NATIONAL_URL}?{urlencode(params)}",
                            national_raw, "application/json", params),
        "official_shanghai_L1": (SHANGHAI_URL, SHANGHAI_URL,
                                 shanghai_raw, "text/html", {}),
    }
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = []
    (root / "raw_responses").mkdir()
    for source, (requested, actual, raw, media, request_params) in urls.items():
        digest = hashlib.sha256(raw).hexdigest()
        (root / "raw_responses" / f"{digest}.bin").write_bytes(raw)
        records.append({
            "source": source, "requested_url": requested, "url": actual,
            "request_params": request_params, "fetched_at": now,
            "http_status": 200, "content_type": media,
            "parser_version": PARSER_VERSION, "sha256": digest,
            "bytes": len(raw), "artifact": f"raw_responses/{digest}.bin",
            "attempts": [{"attempt": 1, "outcome": "HTTP_RESPONSE",
                          "status_code": 200, "error_type": None,
                          "retry_delay": 0.0, "url": actual}],
        })
    national_record, shanghai_record = records
    page_manifest = [{"page": 1, "sha256": national_record["sha256"],
                      "bytes": national_record["bytes"], "url": national_record["url"]}]
    canonical_hash = hashlib.sha256(json.dumps([draw], ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema": "official-source-evidence-v8.5", "parser_version": PARSER_VERSION,
        "game": "SSQ", "fetched_at": now, "canonical_hash": canonical_hash,
        "canonical_payload_sha256": canonical_hash, "draw_count": 1,
        "latest": draw, "crosscheck_count": 1, "crosscheck_status": "PASS",
        "verification": "CWL_L0_PLUS_1_PROVINCIAL_VALIDATOR",
        "source_receipts": [
            {"source": "official_cwl_L0", "fetched_at": now, "http_status": 200,
             "raw_sha256": hashlib.sha256(json.dumps(page_manifest, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
             "draw_count": 1, "latest_issue": issue, "status": "PASS", "detail": "synthetic fixture"},
            {"source": "official_shanghai_L1", "fetched_at": now, "http_status": 200,
             "raw_sha256": shanghai_record["sha256"], "draw_count": 1,
             "latest_issue": issue, "status": "PASS", "detail": "synthetic fixture"},
            {"source": "official_hebei_L2", "fetched_at": now, "http_status": 0,
             "raw_sha256": "", "draw_count": 0, "latest_issue": "",
             "status": "FAIL", "detail": "synthetic unavailable"},
        ],
        "national_raw_manifest": page_manifest, "raw_responses": records,
        "raw_response_status": "PASS", "baseline_lineage": None,
    }
    return manifest, [draw]


def synthetic_fallback_bundle(root: Path) -> tuple[dict, list[dict]]:
    """A fixture with a prior raw-verified baseline; not a live-network run."""
    baseline, draws = synthetic_source_bundle(root)
    draw = draws[-1]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue, day = draw["issue"], draw["draw_date"]
    home_raw = (
        f'<li class="kj-info-item"><img src="logo_ssq.png"/><p>第 {issue} 期</p>'
        '<div class="cirle-number">'
        + "".join(f"<span>{number:02d}</span>" for number in range(1, 7))
        + '<span class="blue-num">07</span></div></li>'
    ).encode("utf-8")
    announce_raw = f"开奖日期：{day} 开奖号码：01 02 03 04 05 06 07".encode("utf-8")
    records = [dict(next(row for row in baseline["raw_responses"]
                         if row["source"] == "official_shanghai_L1"))]
    hebei_hashes = {}
    for url, raw in ((HEBEI_URL, home_raw), (HEBEI_ANNOUNCE_URL, announce_raw)):
        digest = hashlib.sha256(raw).hexdigest()
        (root / "raw_responses" / f"{digest}.bin").write_bytes(raw)
        hebei_hashes[url] = digest
        records.append({
            "source": "official_hebei_L2", "requested_url": url, "url": url,
            "request_params": {}, "fetched_at": now, "http_status": 200,
            "content_type": "text/html", "parser_version": PARSER_VERSION,
            "sha256": digest, "bytes": len(raw),
            "artifact": f"raw_responses/{digest}.bin",
            "attempts": [{"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": 200,
                          "error_type": None, "retry_delay": 0.0, "url": url}],
        })
    hebei_receipt_hash = hashlib.sha256(json.dumps({
        "home": hebei_hashes[HEBEI_URL], "announce": hebei_hashes[HEBEI_ANNOUNCE_URL],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    shanghai_receipt = dict(baseline["source_receipts"][1])
    fallback = {
        **baseline,
        "fetched_at": now,
        "verification": "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS",
        "crosscheck_count": 2,
        "source_receipts": [
            {"source": "official_cwl_L0", "fetched_at": now, "http_status": 0,
             "raw_sha256": "", "draw_count": 0, "latest_issue": "",
             "status": "FAIL", "detail": "synthetic unavailable"},
            shanghai_receipt,
            {"source": "official_hebei_L2", "fetched_at": now, "http_status": 200,
             "raw_sha256": hebei_receipt_hash, "draw_count": 1,
             "latest_issue": issue, "status": "PASS", "detail": "synthetic fixture"},
        ],
        "national_raw_manifest": [], "raw_responses": records,
        "baseline_lineage": baseline,
        "baseline_canonical_hash": baseline["canonical_hash"],
        "baseline_draw_count": len(draws),
    }
    return fallback, draws


class ReleaseGateEvidenceTests(unittest.TestCase):
    @staticmethod
    def complete_exe_checks() -> dict[str, dict[str, object]]:
        return {name: {"status": "PASS", "exit_code": 0,
                       "exe_hash_matches": True} for name in REQUIRED_EXE_CHECKS}

    @staticmethod
    def write_synthetic_corrupt_repair_contract(root: Path, exe_hash: str) -> None:
        # Local fixture for the *scope label*, never a real-network claim.
        (root / "corrupt-repair.json").write_text(json.dumps({
            "status": "PASS", "scope": "corrupt-repair", "game": "SSQ",
            "platform": "win32", "github_sha": "a" * 40,
            "github_run_id": "12345", "exe_sha256": exe_hash,
            "final_release_gate": "PENDING",
            "test_data_classification": "TEST_ONLY_SYNTHETIC",
            "real_network_status": "PENDING", "real_network_tested": False,
            "production_repair_status": "PENDING", "result": {
                "status": "PASS", "validation_scope": "FAULT_INJECTION_ONLY",
                "test_data_classification": "TEST_ONLY_SYNTHETIC",
                "real_network_status": "PENDING", "real_network_tested": False,
                "production_repair_status": "PENDING",
                "synthetic_artifacts_exported": False,
                "checks": {"synthetic_transport_isolation": True},
            },
        }), encoding="utf-8")

    def test_synthetic_raw_contract_rebuilds_canonical_without_network(self) -> None:
        # This exercises the offline verifier, not the Real Network gate.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, expected = synthetic_source_bundle(root)
            draws, proof = _reparse_manifest(manifest, root)
        self.assertEqual(draws, expected)
        self.assertEqual(proof["sources"], ["official_cwl_L0", "official_shanghai_L1"])
        self.assertEqual(proof["crosscheck_count"], 1)

    def test_synthetic_fallback_reparses_baseline_and_hebei_dual_page(self) -> None:
        # Exercises the strict fallback contract, not Real Network acceptance.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, expected = synthetic_fallback_bundle(root)
            draws, proof = _reparse_manifest(manifest, root)
        self.assertEqual(draws, expected)
        self.assertEqual(proof["crosscheck_count"], 2)
        self.assertEqual(proof["verification"],
                         "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS")

    def test_fallback_missing_raw_verified_baseline_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = synthetic_fallback_bundle(root)
            manifest["baseline_lineage"] = None
            with self.assertRaises(ValueError):
                _reparse_manifest(manifest, root)

    def test_fallback_stale_archived_baseline_cannot_prove_current_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = synthetic_fallback_bundle(root)
            baseline = manifest["baseline_lineage"]
            stale = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            baseline["fetched_at"] = stale
            for row in baseline["raw_responses"]:
                row["fetched_at"] = stale
            for row in baseline["source_receipts"]:
                row["fetched_at"] = stale
            with self.assertRaises(ValueError):
                _reparse_manifest(manifest, root)

    def test_fallback_hebei_announcement_conflict_fails_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = synthetic_fallback_bundle(root)
            announce = next(row for row in manifest["raw_responses"]
                            if row["requested_url"] == HEBEI_ANNOUNCE_URL)
            old = (root / "raw_responses" / f"{announce['sha256']}.bin").read_bytes()
            conflicted = old.replace(b"06 07", b"06 08")
            self.assertNotEqual(old, conflicted)
            digest = hashlib.sha256(conflicted).hexdigest()
            (root / "raw_responses" / f"{digest}.bin").write_bytes(conflicted)
            announce.update(sha256=digest, bytes=len(conflicted),
                            artifact=f"raw_responses/{digest}.bin")
            home_digest = next(row["sha256"] for row in manifest["raw_responses"]
                               if row["requested_url"] == HEBEI_URL)
            manifest["source_receipts"][2]["raw_sha256"] = hashlib.sha256(json.dumps({
                "home": home_digest, "announce": digest,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            with self.assertRaisesRegex(ValueError, "Hebei home and announcement ball sets conflict"):
                _reparse_manifest(manifest, root)

    def test_raw_reparse_rejects_cross_source_conflict_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = synthetic_source_bundle(root)
            shanghai = next(row for row in manifest["raw_responses"]
                            if row["source"] == "official_shanghai_L1")
            original = (root / "raw_responses" / f"{shanghai['sha256']}.bin").read_bytes()
            conflicted = original.replace(b"<td>07</td>", b"<td>08</td>")
            self.assertNotEqual(original, conflicted)
            digest = hashlib.sha256(conflicted).hexdigest()
            (root / "raw_responses" / f"{digest}.bin").write_bytes(conflicted)
            shanghai.update(sha256=digest, bytes=len(conflicted),
                            artifact=f"raw_responses/{digest}.bin")
            manifest["source_receipts"][1]["raw_sha256"] = digest
            with self.assertRaisesRegex(ValueError, "consistent overlap|latest draw conflicts"):
                _reparse_manifest(manifest, root)

    def test_raw_reparse_rejects_receipt_without_terminal_network_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = synthetic_source_bundle(root)
            manifest["raw_responses"][0]["attempts"] = []
            with self.assertRaisesRegex(ValueError, "attempt ledger"):
                _reparse_manifest(manifest, root)

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
        self.assertFalse(any(value == "PASS" for value in report["gates"].values()))
        self.assertTrue(any(value == "FAIL" for value in report["gates"].values()))

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
            self.write_synthetic_corrupt_repair_contract(root, digest)
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
            self.assertEqual(report["gates"][gate], "FAIL", gate)

    def test_updater_mechanics_pass_cannot_replace_real_release_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            updater_exe = root / "Geometry_Lotto_Pro_SSQ_Updater.exe"
            exe.write_bytes(b"candidate-build")
            updater_exe.write_bytes(b"exact-updater")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            updater_hash = hashlib.sha256(updater_exe.read_bytes()).hexdigest()
            checks = self.complete_exe_checks()
            checks["self"]["updater_bundle_integrity"] = True
            checks["self"]["embedded_updater_sha256"] = updater_hash
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(json.dumps({
                "runner_os": "Windows", "artifact": exe.name, "sha256": digest,
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "final_release_gate": "PENDING",
                "hard_fail_count": 0, "checks": checks,
                "updater": {
                    "artifact": updater_exe.name, "sha256": updater_hash,
                    "manifest": {"sha256": updater_hash},
                    "status": "PASS", "software_release_network": "PENDING",
                    "release_gate": "PENDING",
                },
            }), encoding="utf-8")
            self.write_synthetic_corrupt_repair_contract(root, digest)
            updater_checks = {
                name: {
                    "status": "PASS", "exit_code": 0, "hash_matches": True,
                    "separate_process": True, "parent_pid_match": True,
                }
                for name in ("self-test", "software-self-test", "offline-failclosed", "update", "repair")
            }
            (root / "UPDATER_EXACT_EXE_ACCEPTANCE.json").write_text(json.dumps({
                "schema": "ssq-updater-exact-exe-acceptance-v2",
                "artifact": updater_exe.name, "sha256": updater_hash,
                "runner_os": "Windows", "github_sha": "a" * 40,
                "github_run_id": "12345", "checks": updater_checks,
                "hard_fail_count": 0, "updater_exact_exe": "PASS",
                "software_release_network": "PENDING",
                "software_release_reason": "no independent release host",
                "updater_release_gate": "PENDING",
            }), encoding="utf-8")
            (root / "updater-software-self-test.json").write_text(json.dumps({
                "schema": "ssq-independent-updater-v2",
                "mode": "software-self-test", "status": "PASS",
                "github_sha": "a" * 40, "github_run_id": "12345",
                "updater_exe_sha256": updater_hash, "parent_pid_match": True,
                "service_result": {
                    "status": "PASS",
                    "checks": {
                        "atomic_replace_success": True,
                        "previous_bytes_preserved": True,
                        "post_replace_validation_bound": True,
                        "forced_validation_failure_rolls_back": True,
                        "rollback_hash_restored": True,
                    },
                },
            }), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}):
                report = derive(root, exe)
        self.assertEqual(report["gates"]["updater_process"], "PASS")
        self.assertEqual(report["gates"]["updater_exact_exe"], "PASS")
        self.assertEqual(report["gates"]["updater_atomic_rollback"], "PASS")
        self.assertEqual(report["gates"]["updater_same_hash"], "PASS")
        self.assertEqual(report["gates"]["updater_real_network"], "PENDING")

    def test_synthetic_fault_injection_must_not_claim_real_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(json.dumps({
                "runner_os": "Windows", "artifact": exe.name, "sha256": digest,
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "final_release_gate": "PENDING",
                "hard_fail_count": 0, "checks": self.complete_exe_checks(),
            }), encoding="utf-8")
            self.write_synthetic_corrupt_repair_contract(root, digest)
            path = root / "corrupt-repair.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["real_network_status"] = "PASS"
            value["result"]["real_network_status"] = "PASS"
            path.write_text(json.dumps(value), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40,
                                       "GITHUB_RUN_ID": "12345"}):
                report = derive(root, exe)
        self.assertEqual(report["gates"]["windows_build"], "FAIL")
        self.assertEqual(report["gates"]["exact_exe"], "FAIL")
        self.assertEqual(report["gates"]["real_network"], "FAIL")

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

    def test_raw_receipts_without_independent_reparse_fail_closed(self) -> None:
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
            self.write_synthetic_corrupt_repair_contract(root, digest)
            with (patch.dict(os.environ, {"GITHUB_SHA": "a" * 40,
                                           "GITHUB_RUN_ID": "12345"}),
                  patch("derive_gate_status._verify_live_evidence",
                        return_value={"raw_response_count": 24})):
                report = derive(root, exe)
        self.assertEqual(report["gates"]["real_network"], "FAIL")
        self.assertEqual(report["gates"]["same_hash"], "PENDING")
        self.assertIn("error", report["proofs"]["real_network"])

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
                "--repository-independent", "FAIL",
            ], capture_output=True, text=True)
            final = json.loads(report.read_text(encoding="utf-8"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(final["final_gate"], "FAIL")
        self.assertEqual(final["gate_input_integrity"], "FAIL")
        self.assertIn("gate_input_integrity", final["failures"])


    def test_reversal_contract_binds_invariant_science_and_audit_contract(self) -> None:
        reverse = {"remove": True, "shuffle": True, "random_replace": True}
        policy = {"schema": "false-edge-firewall-v8", "alpha": 0.01}
        science = {"result": {
            "court_hash": "science-run-hash",
            "pre_registered_policy": policy,
            "model_hash": "model-proof",
            "selector_hash": "selector-proof",
            "reverse_validation": reverse,
            "ablation": {"executed": True},
        }}
        audit = {"result": {
            "software_verdict": "PASS",
            "court": {
                "software_verdict": "PASS",
                "edge_state": "NO_EDGE",
                "dan_state": "NULL_DAN",
                "court_hash": "audit-run-hash",
                "pre_registered_policy": policy,
                "model_hash": "model-proof",
                "selector_hash": "selector-proof",
                "reverse_validation": reverse,
                "ablation": {"executed": True},
                "final_validation": {"status": "PASS"},
            },
        }}
        proof = _verify_reversal_contract(science, audit)
        self.assertEqual(proof["science_court_hash"], "science-run-hash")
        self.assertEqual(proof["audit_court_hash"], "audit-run-hash")
        audit["result"]["court"]["selector_hash"] = "mismatch"
        with self.assertRaises(ValueError):
            _verify_reversal_contract(science, audit)

if __name__ == "__main__":
    unittest.main()
