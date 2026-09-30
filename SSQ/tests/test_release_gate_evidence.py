from __future__ import annotations

import hashlib
import json
import os
import sqlite3
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
    REQUIRED_BUSINESS_CHECKS, REQUIRED_EXE_CHECKS, REQUIRED_NETCLIENT_CHECKS,
    _raw_status_allowed, _reparse_manifest, _verify_checkout_identity,
    _verify_gui_evidence, _verify_gui_update_source, _verify_reversal_contract,
    _verify_updater_release_network, derive,
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


def synthetic_gui_update_bundle(root: Path) -> tuple[dict, dict, dict]:
    """Isolated parser/ledger contract fixture, never GUI or live-network proof."""
    manifest, draws = synthetic_source_bundle(root)
    canonical = {"schema": 4, "game": "SSQ", "draws": draws,
                 "canonical_hash": manifest["canonical_hash"]}
    payload = {
        "canonical_hash": manifest["canonical_hash"],
        "source_receipts": manifest["source_receipts"],
        "draw_count": len(draws), "latest": draws[-1],
        "latest_issue": draws[-1]["issue"], "crosscheck_status": "PASS",
        "crosscheck_count": manifest["crosscheck_count"],
        "verification": manifest["verification"],
    }
    (root / "source_evidence.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "canonical_history.json").write_text(json.dumps(canonical), encoding="utf-8")
    db = sqlite3.connect(root / "ledger.sqlite3")
    try:
        db.execute("CREATE TABLE experiments(id INTEGER PRIMARY KEY, kind TEXT, "
                   "status TEXT, payload_json TEXT)")
        db.execute("INSERT INTO experiments VALUES(1, 'official_update', 'PASS', ?)",
                   (json.dumps(payload),))
        db.commit()
    finally:
        db.close()
    observed = {"experiment_id": 1, "display_token": manifest["canonical_hash"]}
    return manifest, canonical, observed


def _sha_for_test(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class ReleaseGateEvidenceTests(unittest.TestCase):
    def test_gui_update_contract_reparses_same_directory_synthetic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _, observed = synthetic_gui_update_bundle(root)
            proof = _verify_gui_update_source(root, observed)
            self.assertEqual(proof["canonical_hash"], manifest["canonical_hash"])
            self.assertEqual(proof["canonical_reparse"], "PASS")
            self.assertEqual(proof["raw_response_count"], 2)
            self.assertEqual(proof["manifest_sha256"], hashlib.sha256(
                (root / "source_evidence.json").read_bytes()).hexdigest())

    def test_gui_update_rejects_stale_manifest_receipts_and_each_raw(self) -> None:
        for component in ("manifest", "receipt", "raw0", "raw1"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, _, observed = synthetic_gui_update_bundle(root)
                stale = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
                target = manifest if component == "manifest" else (
                    manifest["source_receipts"][0] if component == "receipt"
                    else manifest["raw_responses"][int(component[-1])])
                target["fetched_at"] = stale
                (root / "source_evidence.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _verify_gui_update_source(root, observed)

    def test_gui_update_rejects_other_click_token_or_canonical_rows(self) -> None:
        for change in ("token", "hash", "rows", "game", "missing"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, canonical, observed = synthetic_gui_update_bundle(root)
                if change == "token":
                    observed["display_token"] = "f" * 64
                elif change == "hash":
                    canonical["canonical_hash"] = "f" * 64
                elif change == "rows":
                    canonical["draws"][0]["back"] = [8]
                elif change == "game":
                    canonical["game"] = "DLT"
                if change == "missing":
                    (root / "canonical_history.json").unlink()
                else:
                    (root / "canonical_history.json").write_text(json.dumps(canonical), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _verify_gui_update_source(root, observed)

    def test_gui_update_rejects_ledger_source_mismatch(self) -> None:
        for field, value in (("source_receipts", []), ("canonical_hash", "f" * 64),
                             ("latest_issue", "unrelated"), ("crosscheck_status", "FAIL")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, observed = synthetic_gui_update_bundle(root)
                db = sqlite3.connect(root / "ledger.sqlite3")
                try:
                    payload = json.loads(db.execute("SELECT payload_json FROM experiments WHERE id=1").fetchone()[0])
                    payload[field] = value
                    db.execute("UPDATE experiments SET payload_json=? WHERE id=1", (json.dumps(payload),))
                    db.commit()
                finally:
                    db.close()
                with self.assertRaises(ValueError):
                    _verify_gui_update_source(root, observed)

    def test_gui_update_rejects_wrong_raw_bytes_or_provenance(self) -> None:
        for change in ("bytes", "url"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, _, observed = synthetic_gui_update_bundle(root)
                record = manifest["raw_responses"][0]
                if change == "bytes":
                    (root / record["artifact"]).write_bytes(b"not the recorded official response")
                else:
                    record["url"] = "https://example.invalid/data"
                    (root / "source_evidence.json").write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _verify_gui_update_source(root, observed)

    def _derive_static_report(self, filename: str, report: dict) -> dict:
        # Report decoder unit test only: no candidate, network or GUI is tested.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report.update(status="PASS", github_sha="a" * 40, github_run_id="12345")
            (root / filename).write_text(json.dumps(report), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}):
                return derive(root, root / "absent.exe")

    def test_business_report_requires_all_named_checks_and_literal_true(self) -> None:
        for bad in ("FAIL", "WARNING", "PASS", 1, False, None):
            with self.subTest(bad=bad):
                checks = dict.fromkeys(REQUIRED_BUSINESS_CHECKS, True)
                checks["business_model_inventory"] = bad
                result = self._derive_static_report("BUSINESS_GATE.json", {
                    "schema": "ssq-business-gate-v1", "checks": checks})
                self.assertEqual(result["gates"]["business_content"], "FAIL")
        for missing in REQUIRED_BUSINESS_CHECKS:
            with self.subTest(missing=missing):
                checks = dict.fromkeys(REQUIRED_BUSINESS_CHECKS - {missing}, True)
                result = self._derive_static_report("BUSINESS_GATE.json", {
                    "schema": "ssq-business-gate-v1", "checks": checks})
                self.assertEqual(result["gates"]["business_content"], "FAIL")

    def test_netclient_report_requires_all_named_explicit_passes_and_integer_count(self) -> None:
        complete = {name: {"status": "PASS"} for name in REQUIRED_NETCLIENT_CHECKS}
        for missing in REQUIRED_NETCLIENT_CHECKS:
            with self.subTest(missing=missing):
                result = self._derive_static_report("NETCLIENT_CONTRACT_GATE.json", {
                    "schema": "ssq-netclient-contract-gate-v2", "hard_fail_count": 0,
                    "checks": {key: row for key, row in complete.items() if key != missing}})
                self.assertEqual(result["gates"]["contract_test"], "FAIL")
        for bad in (False, True, "0", 0.0, None, -1, 1):
            with self.subTest(count=bad):
                result = self._derive_static_report("NETCLIENT_CONTRACT_GATE.json", {
                    "schema": "ssq-netclient-contract-gate-v2", "hard_fail_count": bad,
                    "checks": complete})
                self.assertEqual(result["gates"]["contract_test"], "FAIL")
        for bad in ("FAIL", "WARNING", "SKIPPED", True, {}, {"status": "FAIL"}):
            with self.subTest(check=bad):
                checks = dict(complete)
                checks["https_only"] = bad
                result = self._derive_static_report("NETCLIENT_CONTRACT_GATE.json", {
                    "schema": "ssq-netclient-contract-gate-v2", "hard_fail_count": 0,
                    "checks": checks})
                self.assertEqual(result["gates"]["contract_test"], "FAIL")

    def test_complete_static_contract_is_accepted_without_claiming_final_pass(self) -> None:
        for filename, report, gate in (
            ("BUSINESS_GATE.json", {"schema": "ssq-business-gate-v1",
                "checks": dict.fromkeys(REQUIRED_BUSINESS_CHECKS, True)}, "business_content"),
            ("NETCLIENT_CONTRACT_GATE.json", {"schema": "ssq-netclient-contract-gate-v2",
                "hard_fail_count": 0, "checks": {
                    name: {"status": "PASS"} for name in REQUIRED_NETCLIENT_CHECKS}}, "contract_test"),
        ):
            with self.subTest(filename=filename):
                result = self._derive_static_report(filename, report)
                self.assertEqual(result["gates"][gate], "PASS")
                self.assertNotEqual(result["gates"]["real_network"], "PASS")
                self.assertNotEqual(result["gates"]["exact_exe"], "PASS")
                self.assertEqual(result["gates"]["repository_independence"], "FAIL")

    @staticmethod
    def complete_exe_checks() -> dict[str, dict[str, object]]:
        return {name: {"status": "PASS", "exit_code": 0,
                       "exe_hash_matches": True} for name in REQUIRED_EXE_CHECKS}

    @staticmethod
    def write_current_checkout_identity(root: Path, sha: str = "a" * 40,
                                        run_id: str = "12345") -> None:
        # Fixture for tests that intentionally isolate gates *after* checkout
        # identity. Negative identity tests build their own malformed reports.
        (root / "CHECKOUT_IDENTITY_GATE.json").write_text(json.dumps({
            "schema": "ssq-checkout-identity-v1",
            "status": "PASS",
            "github_sha": sha,
            "github_run_id": run_id,
            "event": "push",
            "event_head_sha": "",
            "actual_checkout_sha": sha,
            "parent_shas": [],
        }), encoding="utf-8")

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

    def test_gui_replay_preserves_recorded_parent_pid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"exact candidate")
            rows = []
            expected_pids = []
            operations = (
                (101, "predict", "prediction_freeze"),
                (102, "update", "official_update"),
                (103, "repair", "repair"),
                (104, "audit", "audit"),
            )
            for index, (control_id, operation, kind) in enumerate(operations, 1):
                leaf = f"physical-gui-run-{index:032x}"
                run_dir = root / leaf
                run_dir.mkdir()
                before_text = f"before-{operation}"
                token = f"{operation}-token"
                after_text = f"Alpha Beta {token}"
                before_path = run_dir / "gui_before.txt"
                after_path = run_dir / "gui_after.txt"
                before_path.write_text(before_text, encoding="utf-8")
                after_path.write_text(after_text, encoding="utf-8")
                (run_dir / "ledger.sqlite3").write_bytes(b"ledger")
                before_hash = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
                after_hash = hashlib.sha256(after_text.encode("utf-8")).hexdigest()
                process_id = 4200 + index
                expected_pids.append(process_id)
                effect = {
                    "status": "PASS",
                    "operation": operation,
                    "after_id": 0,
                    "experiment_id": index,
                    "kind": kind,
                    "event_status": "PASS",
                    "payload_sha256": f"{index:064x}",
                    "display_token": token,
                }
                rows.append({
                    "button_index": index,
                    "control_id": control_id,
                    "operation": operation,
                    "status": "PASS",
                    "control_class": "BUTTON",
                    "control_name": operation,
                    "process_id": process_id,
                    "control_verified": True,
                    "physical_click_verified": True,
                    "output_verified": True,
                    "backend_effect_verified": True,
                    "before_output_sha256": before_hash,
                    "after_output_sha256": after_hash,
                    "before_output_artifact": f"{leaf}/gui_before.txt",
                    "after_output_artifact": f"{leaf}/gui_after.txt",
                    "before_output_artifact_sha256": before_hash,
                    "after_output_artifact_sha256": after_hash,
                    "output_markers": ["Alpha", "Beta"],
                    "after_status": "DONE",
                    "data_dir": leaf,
                    "displayed_backend_token": token,
                    "backend_effect": effect,
                })

            report = {
                "schema": "physical-gui-click-smoke-v2",
                "status": "PASS",
                "exe": exe.name,
                "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "github_sha": "a" * 40,
                "github_run_id": "12345",
                "tested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "coordinate_fallback": False,
                "visual_hash_as_proof": False,
                "buttons": rows,
            }
            seen_pids = []

            def fake_inspect(data_dir, operation, after_id=0, experiment_id=None, parent_pid=0):
                row = next(item for item in rows if item["operation"] == operation)
                self.assertEqual(after_id, 0)
                self.assertEqual(experiment_id, row["backend_effect"]["experiment_id"])
                self.assertEqual(parent_pid, row["process_id"])
                seen_pids.append(parent_pid)
                return dict(row["backend_effect"])

            with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}):
                with patch("verify_gui_effect.inspect_effect", side_effect=fake_inspect):
                    with patch("derive_gate_status._verify_gui_update_source", return_value={"status": "PASS"}):
                        proof = _verify_gui_evidence(report, root, exe, True)

            self.assertEqual(len(proof["ledgers"]), 4)
            self.assertEqual(seen_pids, expected_pids)

    def test_failed_source_body_is_allowed_only_as_failed_receipt(self) -> None:
        # A CWL 403 body must remain hash-checkable evidence during a valid
        # Shanghai+Hebei fallback, but it can never be a PASS-source page.
        self.assertTrue(_raw_status_allowed(403, "FAIL"))
        self.assertTrue(_raw_status_allowed(200, "FAIL"))  # parse/schema failure
        self.assertTrue(_raw_status_allowed(200, "PASS"))
        self.assertFalse(_raw_status_allowed(403, "PASS"))
        self.assertFalse(_raw_status_allowed(200, "PENDING"))

    def test_checkout_identity_accepts_current_pr_head_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            merge_sha = "1" * 40
            head_sha = "2" * 40
            report = {
                "schema": "ssq-checkout-identity-v1", "status": "PASS",
                "github_sha": merge_sha, "github_run_id": "12345",
                "event": "pull_request", "event_head_sha": head_sha,
                "actual_checkout_sha": merge_sha, "parent_shas": ["3" * 40, head_sha],
            }
            (root / "CHECKOUT_IDENTITY_GATE.json").write_text(json.dumps(report), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": merge_sha, "GITHUB_RUN_ID": "12345"}):
                proof = _verify_checkout_identity(root)
            self.assertEqual(proof["event_head_sha"], head_sha)

    def test_checkout_identity_rejects_stale_pr_merge_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            merge_sha = "1" * 40
            report = {
                "schema": "ssq-checkout-identity-v1", "status": "PASS",
                "github_sha": merge_sha, "github_run_id": "12345",
                "event": "pull_request", "event_head_sha": "2" * 40,
                "actual_checkout_sha": merge_sha, "parent_shas": ["3" * 40, "4" * 40],
            }
            (root / "CHECKOUT_IDENTITY_GATE.json").write_text(json.dumps(report), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": merge_sha, "GITHUB_RUN_ID": "12345"}):
                with self.assertRaises(ValueError):
                    _verify_checkout_identity(root)

    def test_checkout_identity_rejects_push_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {
                "schema": "ssq-checkout-identity-v1", "status": "PASS",
                "github_sha": "1" * 40, "github_run_id": "12345",
                "event": "push", "event_head_sha": "",
                "actual_checkout_sha": "2" * 40, "parent_shas": ["3" * 40],
            }
            (root / "CHECKOUT_IDENTITY_GATE.json").write_text(json.dumps(report), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_SHA": "1" * 40, "GITHUB_RUN_ID": "12345"}):
                with self.assertRaises(ValueError):
                    _verify_checkout_identity(root)
    def test_repository_independence_is_machine_derived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro",
                "GITHUB_SERVER_URL": "https://github.com",
            }, clear=False):
                shared = derive(root, root / "missing.exe")
            self.assertEqual(shared["gates"]["repository_independence"], "FAIL")
            self.assertFalse(
                shared["proofs"]["repository_independence"]["checks"]["repository_exact"]
            )

            with patch.dict(os.environ, {
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro-SSQ",
                "GITHUB_SERVER_URL": "https://github.com",
            }, clear=False):
                independent = derive(root, root / "missing.exe")
            self.assertEqual(independent["gates"]["repository_independence"], "PASS")
            self.assertTrue(all(
                independent["proofs"]["repository_independence"]["checks"].values()
            ))

            with patch.dict(os.environ, {
                "GITHUB_ACTIONS": "false",
                "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro-SSQ",
                "GITHUB_SERVER_URL": "https://github.com",
            }, clear=False):
                local_spoof = derive(root, root / "missing.exe")
            self.assertEqual(local_spoof["gates"]["repository_independence"], "FAIL")

    def test_verification_version_cannot_be_portfolio_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "candidate.exe"
            exe.write_bytes(b"candidate-build")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            acceptance = {
                "runner_os": "Windows", "artifact": exe.name, "sha256": digest,
                "github_sha": "a" * 40, "github_run_id": "12345",
                "windows_exact_exe_acceptance": "PASS", "final_release_gate": "PENDING",
                "hard_fail_count": 0, "checks": self.complete_exe_checks(),
            }
            (root / "WINDOWS_EXACT_EXE_ACCEPTANCE.json").write_text(
                json.dumps(acceptance), encoding="utf-8",
            )
            self.write_synthetic_corrupt_repair_contract(root, digest)
            self.write_current_checkout_identity(root)
            self_result = {
                "status": "PASS", "scope": "self", "game": "SSQ", "platform": "win32",
                "github_sha": "a" * 40, "github_run_id": "12345",
                "exe_sha256": digest, "final_release_gate": "PENDING",
                "version": "8.5.0-verification",
            }
            (root / "self.json").write_text(json.dumps(self_result), encoding="utf-8")
            with patch.dict(os.environ, {
                "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345",
            }):
                report = derive(root, exe)
            self.assertEqual(report["gates"]["release_version"], "FAIL")
            self.assertEqual(
                report["proofs"]["release_version"]["version"],
                "8.5.0-verification",
            )

    def test_portfolio_final_requires_independent_main_release_context(self) -> None:
        base = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro-SSQ",
            "GITHUB_SERVER_URL": "https://github.com",
        }
        cases = [
            ("pull_request", "refs/pull/7/merge", "FAIL"),
            ("push", "refs/heads/feature/test", "FAIL"),
            ("push", "refs/heads/ssq-final-candidate", "FAIL"),
            ("push", "refs/heads/main", "PASS"),
            ("workflow_dispatch", "refs/heads/main", "PASS"),
        ]
        from derive_gate_status import _release_context_proof
        for event, ref, expected in cases:
            with self.subTest(event=event, ref=ref):
                with patch.dict(os.environ, {
                    **base, "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref,
                }, clear=False):
                    status, proof = _release_context_proof()
                self.assertEqual(status, expected)
                self.assertEqual(proof["status"], expected)

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
            self.write_current_checkout_identity(root)
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

    def test_updater_release_pass_requires_real_current_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            updater_hash = "a" * 64
            report = {
                "schema": "ssq-independent-updater-v2",
                "mode": "software-update",
                "status": "PASS",
                "github_sha": "a" * 40,
                "github_run_id": "12345",
                "updater_exe_sha256": updater_hash,
                "parent_pid_match": True,
                "service_result": {},
                "service_result_sha256": _sha_for_test({}),
            }
            (root / "updater-software-release-network.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            with patch.dict(os.environ, {
                "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345",
            }):
                with self.assertRaises(ValueError):
                    _verify_updater_release_network(root, updater_hash, "b" * 64)

    def test_updater_release_network_requires_real_waited_pid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            updater_hash = "a" * 64
            digest = "b" * 64
            version = "9.0.0"
            manifest_url = (
                "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                "releases/download/v9/manifest.json"
            )
            artifact_url = (
                "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                "releases/download/v9/app.exe"
            )

            def write_report(wait: dict) -> None:
                service = {
                    "status": "PASS",
                    "schema": "ssq-software-update-result-v1",
                    "manifest": {
                        "schema": "ssq-software-update-manifest-v1",
                        "app": "Geometry Lotto Pro SSQ",
                        "version": version,
                        "artifact_url": artifact_url,
                        "artifact_sha256": digest,
                        "artifact_bytes": 123,
                    },
                    "manifest_receipt": {
                        "status": "PASS", "http_status": 200, "bytes": 99,
                        "sha256": "c" * 64, "requested_url": manifest_url,
                        "final_url": manifest_url,
                    },
                    "manifest_raw_sha256": "c" * 64,
                    "artifact_receipt": {
                        "status": "PASS", "http_status": 200, "bytes": 123,
                        "sha256": digest, "requested_url": artifact_url,
                        "final_url": "https://release-assets.githubusercontent.com/fake",
                    },
                    "replacement": {
                        "status": "PASS", "expected_sha256": digest,
                        "staged_sha256": digest, "installed_sha256": digest,
                        "previous_preserved": True,
                        "post_replace_validation": {
                            "status": "PASS", "expected_version": version,
                            "reported_version": version, "target_sha256": digest,
                        },
                    },
                    "wait_for_main": wait,
                    "from_version": "8.9.0",
                    "to_version": version,
                }
                report = {
                    "schema": "ssq-independent-updater-v2",
                    "mode": "software-update", "status": "PASS",
                    "github_sha": "a" * 40, "github_run_id": "12345",
                    "updater_exe_sha256": updater_hash, "parent_pid_match": True,
                    "service_result": service,
                    "service_result_sha256": _sha_for_test(service),
                }
                (root / "updater-software-release-network.json").write_text(
                    json.dumps(report), encoding="utf-8"
                )

            with patch.dict(os.environ, {
                "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345",
            }):
                write_report({"status": "PASS", "waited": False})
                with self.assertRaisesRegex(ValueError, "wait evidence"):
                    _verify_updater_release_network(root, updater_hash, digest)

                good_wait = {
                    "status": "PASS", "waited": True, "pid": 4321, "elapsed": 0.5,
                }
                write_report(good_wait)
                release_report = root / "updater-software-release-network.json"
                summary = {
                    "schema": "ssq-updater-real-release-acceptance-v1",
                    "status": "PASS",
                    "github_sha": "a" * 40,
                    "github_run_id": "12345",
                    "repository": "douluo511/Geometry-Lotto-Pro-SSQ",
                    "updater_exe_sha256": updater_hash,
                    "candidate_exe_sha256": digest,
                    "candidate_version": version,
                    "installed_sha256": digest,
                    "installed_version": version,
                    "base_version": "8.9.0",
                    "base_artifact_sha256": "d" * 64,
                    "base_artifact_bytes": 456,
                    "base_manifest_url": (
                        "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                        "releases/download/v8.9/base-manifest.json"
                    ),
                    "base_manifest_raw_sha256": "e" * 64,
                    "base_manifest_receipt": {
                        "status": "PASS", "http_status": 200, "bytes": 99,
                        "sha256": "e" * 64,
                        "requested_url": (
                            "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                            "releases/download/v8.9/base-manifest.json"
                        ),
                        "final_url": (
                            "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                            "releases/download/v8.9/base-manifest.json"
                        ),
                    },
                    "base_artifact_receipt": {
                        "status": "PASS", "http_status": 200, "bytes": 456,
                        "sha256": "d" * 64,
                        "requested_url": (
                            "https://github.com/douluo511/Geometry-Lotto-Pro-SSQ/"
                            "releases/download/v8.9/base.exe"
                        ),
                        "final_url": "https://release-assets.githubusercontent.com/base",
                    },
                    "wait_target": {
                        "kind": "exact_base_main_exe",
                        "pid": 4321,
                        "sha256": "d" * 64,
                        "version": "8.9.0",
                        "artifact": "updater-release-base-main.exe",
                    },
                    "wait_for_main": good_wait,
                    "exact_updater_report": "updater-software-release-network.json",
                    "exact_updater_report_sha256": hashlib.sha256(
                        release_report.read_bytes()
                    ).hexdigest(),
                }
                (root / "UPDATER_REAL_RELEASE_ACCEPTANCE.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )
                proof = _verify_updater_release_network(root, updater_hash, digest)
                self.assertTrue(proof["waited_for_main"])
                self.assertEqual(proof["wait_pid"], 4321)
                self.assertGreater(proof["wait_elapsed"], 0)

    def test_updater_release_network_rejects_shared_repo_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            updater_hash = "a" * 64
            digest = "b" * 64
            version = "9.0.0"
            service = {
                "status": "PASS",
                "schema": "ssq-software-update-result-v1",
                "manifest": {
                    "schema": "ssq-software-update-manifest-v1",
                    "app": "Geometry Lotto Pro SSQ",
                    "version": version,
                    "artifact_url": "https://github.com/douluo511/Geometry-Lotto-Pro/releases/download/v9/app.exe",
                    "artifact_sha256": digest,
                    "artifact_bytes": 123,
                },
                "manifest_receipt": {
                    "status": "PASS", "http_status": 200, "bytes": 99,
                    "sha256": "c" * 64,
                    "requested_url": "https://github.com/douluo511/Geometry-Lotto-Pro/releases/download/v9/manifest.json",
                    "final_url": "https://github.com/douluo511/Geometry-Lotto-Pro/releases/download/v9/manifest.json",
                },
                "manifest_raw_sha256": "c" * 64,
                "artifact_receipt": {
                    "status": "PASS", "http_status": 200, "bytes": 123,
                    "sha256": digest,
                    "requested_url": "https://github.com/douluo511/Geometry-Lotto-Pro/releases/download/v9/app.exe",
                    "final_url": "https://release-assets.githubusercontent.com/fake",
                },
                "replacement": {
                    "status": "PASS", "expected_sha256": digest,
                    "staged_sha256": digest, "installed_sha256": digest,
                    "previous_preserved": True,
                    "post_replace_validation": {
                        "status": "PASS", "expected_version": version,
                        "reported_version": version, "target_sha256": digest,
                    },
                },
                "wait_for_main": {"status": "PASS"},
            }
            report = {
                "schema": "ssq-independent-updater-v2",
                "mode": "software-update", "status": "PASS",
                "github_sha": "a" * 40, "github_run_id": "12345",
                "updater_exe_sha256": updater_hash, "parent_pid_match": True,
                "service_result": service, "service_result_sha256": _sha_for_test(service),
            }
            (root / "updater-software-release-network.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            with patch.dict(os.environ, {
                "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345",
            }):
                with self.assertRaises(ValueError):
                    _verify_updater_release_network(root, updater_hash, digest)
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
                for name in (
                    "self-test", "software-self-test", "offline-failclosed", "update", "repair",
                    "software-local-install-acceptance", "software-local-rollback-acceptance",
                )
            }
            updater_checks["reproducible-build"] = {
                "status": "PASS",
                "exit_code": 0,
                "hash_matches": True,
                "primary_sha256": updater_hash,
                "rebuild_sha256": updater_hash,
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
            (root / "updater-local-main-install.json").write_text(json.dumps({
                "schema": "ssq-independent-updater-v2",
                "mode": "software-local-install-acceptance", "status": "PASS",
                "github_sha": "a" * 40, "github_run_id": "12345",
                "updater_exe_sha256": updater_hash, "parent_pid_match": True,
                "service_result": {
                    "status": "PASS",
                    "release_network_status": "PENDING",
                    "transaction": {"status": "PASS", "installed_sha256": digest},
                },
            }), encoding="utf-8")
            (root / "updater-local-main-rollback.json").write_text(json.dumps({
                "schema": "ssq-independent-updater-v2",
                "mode": "software-local-rollback-acceptance", "status": "PASS",
                "github_sha": "a" * 40, "github_run_id": "12345",
                "updater_exe_sha256": updater_hash, "parent_pid_match": True,
                "service_result": {
                    "status": "PASS",
                    "release_network_status": "PENDING",
                    "expect_rollback": True,
                    "transaction": {"status": "FAIL", "rolled_back": True},
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
            self.write_current_checkout_identity(root)
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
