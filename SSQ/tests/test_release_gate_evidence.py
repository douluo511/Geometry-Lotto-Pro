from __future__ import annotations

import copy
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
    REQUIRED_SCIENCE_CHECKS,
    _raw_status_allowed, _reparse_manifest, _verify_gui_evidence,
    _verify_gui_update_source, _verify_reversal_contract, _verify_science_contract,
    _verify_counterexample_contract, derive,
)
from release_gate_22 import HARD_GATES  # noqa: E402
from glp.constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL  # noqa: E402
from glp.sources import PARSER_VERSION  # noqa: E402


def rehash_synthetic_court(report: dict) -> None:
    """Rehash test-only mutations so semantic tests do not merely test SHA mismatch."""
    court = report["result"]
    court.pop("court_hash", None)
    court["court_hash"] = hashlib.sha256(json.dumps(
        court, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def synthetic_science_contract() -> tuple[dict, list[dict]]:
    """Contract-only data; this does not execute science, a candidate EXE or network."""
    from glp.constants import PROMOTION_POLICY
    from glp.engine import model_identity
    identity = model_identity()
    report = {"result": {
        "schema": "evidence-court-v8", "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_hash": identity["model_hash"], "selector_hash": identity["selector_hash"],
        "pre_registered_policy": copy.deepcopy(PROMOTION_POLICY),
        "software_verdict": "PASS", "edge_state": "NO_EDGE", "dan_state": "NULL_DAN",
        "decision": "REJECT_EDGE", "leakage_violations": 0,
        "production_weights": {"uniform_baseline": 1.0, "research_ensemble": 0.0},
        "lifecycle": {"Champion": "uniform_baseline", "Challenger": "research_ensemble",
                      "Shadow": "research_ensemble"},
        "final_validation": {"status": "PASS", "hard_fail_count": 0,
                             "edge_proven": False, "dan_certified": False},
        "walk_forward": {"development_oos_n": 1200, "untouched_holdout_n": 240,
                         "total_oos_n": 1440, "leakage_violations": 0},
        "gates": [{"name": name, "status": "PASS"} for name in sorted(REQUIRED_SCIENCE_CHECKS)],
        "five_why": {f"why{i}": f"Synthetic contract question {i}" for i in range(1, 6)},
        "reverse_validation": {"remove": True, "shuffle": True, "random_replace": True},
        "null_world": {"worlds": 300, "false_promotions": 0,
                       "false_positive_rate": 0.0, "observed_percentile": 0.8},
    }}
    rehash_synthetic_court(report)
    random_worlds = [{"status": "PASS", "scope": f"random-world-{seed}", "result": {
        "seed": seed, "edge_state": "NO_EDGE", "dan_state": "NULL_DAN",
        "software_verdict": "PASS", "leakage_violations": 0,
        "court_hash": hashlib.sha256(f"synthetic-{seed}".encode()).hexdigest(),
    }} for seed in (101, 202, 303)]
    return report, random_worlds


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


class ReleaseGateEvidenceTests(unittest.TestCase):
    def test_consistent_rehashed_positive_promotion_is_not_independent_proof(self) -> None:
        report, _ = synthetic_science_contract()
        court = report["result"]
        court.update(edge_state="EDGE_PROVEN", dan_state="CERTIFIED_DAN", decision="ACCEPT_EDGE")
        court["final_validation"].update(edge_proven=True, dan_certified=True)
        court["production_weights"] = {"uniform_baseline": 0.0, "research_ensemble": 1.0}
        court["lifecycle"]["Champion"] = "research_ensemble"
        rehash_synthetic_court(report)
        with self.assertRaisesRegex(ValueError, "independent statistical proof"):
            _verify_science_contract(report)

    def test_no_edge_cannot_hide_research_model_in_production(self) -> None:
        for mutation in ("weights", "champion", "boolean_weight", "missing_weights"):
            with self.subTest(mutation=mutation):
                report, _ = synthetic_science_contract()
                court = report["result"]
                if mutation == "weights":
                    court["production_weights"] = {"uniform_baseline": 0.0, "research_ensemble": 1.0}
                elif mutation == "champion":
                    court["lifecycle"]["Champion"] = "research_ensemble"
                elif mutation == "boolean_weight":
                    court["production_weights"]["uniform_baseline"] = True
                else:
                    del court["production_weights"]
                rehash_synthetic_court(report)
                with self.assertRaisesRegex(ValueError, "entered production"):
                    _verify_science_contract(report)

    def test_complete_synthetic_science_contract_preserves_no_edge(self) -> None:
        report, worlds = synthetic_science_contract()
        self.assertEqual(_verify_science_contract(report)["edge_state"], "NO_EDGE")
        self.assertEqual(_verify_counterexample_contract(report, worlds)["exact_random_world_checks"], 3)

    def test_science_requires_each_named_check_once(self) -> None:
        for missing in REQUIRED_SCIENCE_CHECKS:
            for replacement in (None, {"name": "unrelated", "status": "PASS"}):
                with self.subTest(missing=missing, replacement=replacement):
                    report, _ = synthetic_science_contract()
                    gates = report["result"]["gates"]
                    gates[:] = [row for row in gates if row["name"] != missing]
                    if replacement is not None:
                        gates.append(replacement)
                    rehash_synthetic_court(report)
                    with self.assertRaises(ValueError):
                        _verify_science_contract(report)
        report, _ = synthetic_science_contract()
        report["result"]["gates"][-1] = dict(report["result"]["gates"][0])
        rehash_synthetic_court(report)
        with self.assertRaises(ValueError):
            _verify_science_contract(report)

    def test_science_rejects_hash_identity_and_stale_evidence(self) -> None:
        for field, bad in (("court_hash", None), ("court_hash", "0" * 64),
                           ("model_hash", "0" * 64), ("selector_hash", None),
                           ("schema", "unrecognized"), ("created_at", "2000-01-01T00:00:00Z")):
            with self.subTest(field=field, bad=bad):
                report, _ = synthetic_science_contract()
                report["result"][field] = bad
                if field != "court_hash":
                    rehash_synthetic_court(report)
                with self.assertRaises(ValueError):
                    _verify_science_contract(report)
        report, _ = synthetic_science_contract()
        report["result"]["five_why"]["why1"] = "changed without recomputing court hash"
        with self.assertRaises(ValueError):
            _verify_science_contract(report)

    def test_science_policy_is_complete_frozen_and_finite(self) -> None:
        for field, bad in (("alpha", float("nan")), ("alpha", float("inf")),
                           ("alpha", -0.01), ("alpha", True), ("alpha", "0.01"),
                           ("null_worlds", 0), ("bootstrap_rounds", 1),
                           ("max_null_world_fpr", 1.0), ("seeds", [17])):
            with self.subTest(field=field, bad=bad):
                report, _ = synthetic_science_contract()
                report["result"]["pre_registered_policy"][field] = bad
                rehash_synthetic_court(report)
                with self.assertRaises(ValueError):
                    _verify_science_contract(report)
        report, _ = synthetic_science_contract()
        report["result"]["pre_registered_policy"].pop("ablation_modes")
        rehash_synthetic_court(report)
        with self.assertRaises(ValueError):
            _verify_science_contract(report)

    def test_science_counts_and_flags_cannot_be_coerced(self) -> None:
        for section, field, bad in (
            ("final_validation", "hard_fail_count", False),
            ("final_validation", "hard_fail_count", "0"),
            ("final_validation", "edge_proven", 0),
            ("final_validation", "dan_certified", None),
            ("walk_forward", "development_oos_n", "1200"),
            ("walk_forward", "untouched_holdout_n", 240.0),
            ("walk_forward", "leakage_violations", False),
            ("walk_forward", "total_oos_n", 1439),
            ("five_why", "why1", ""),
        ):
            with self.subTest(section=section, field=field, bad=bad):
                report, _ = synthetic_science_contract()
                report["result"][section][field] = bad
                rehash_synthetic_court(report)
                with self.assertRaises(ValueError):
                    _verify_science_contract(report)

    def test_science_rejects_missing_and_contradictory_edge_states(self) -> None:
        for field, bad in (("edge_state", None), ("edge_state", "EDGE_PROVEN"),
                           ("dan_state", "CERTIFIED_DAN"), ("dan_state", "UNKNOWN"),
                           ("decision", "ACCEPT_EDGE"), ("leakage_violations", False)):
            with self.subTest(field=field, bad=bad):
                report, _ = synthetic_science_contract()
                report["result"][field] = bad
                rehash_synthetic_court(report)
                with self.assertRaises(ValueError):
                    _verify_science_contract(report)

    def test_counterexample_rejects_false_edge_or_incomplete_inner_results(self) -> None:
        for field, bad in (("seed", 999), ("seed", "101"), ("seed", True),
                           ("edge_state", "EDGE_PROVEN"), ("dan_state", "CERTIFIED_DAN"),
                           ("software_verdict", "FAIL"), ("leakage_violations", 9),
                           ("leakage_violations", False), ("court_hash", None),
                           ("court_hash", "not-a-hash")):
            for index in range(3):
                with self.subTest(index=index, field=field, bad=bad):
                    report, worlds = synthetic_science_contract()
                    worlds[index]["result"][field] = bad
                    with self.assertRaises(ValueError):
                        _verify_counterexample_contract(report, worlds)
        report, worlds = synthetic_science_contract()
        worlds[0]["result"] = {}
        with self.assertRaises(ValueError):
            _verify_counterexample_contract(report, worlds)

    def test_counterexample_requires_three_unique_bound_scopes(self) -> None:
        for kind in ("duplicated", "missing", "wrong_scope", "failed_outer"):
            with self.subTest(kind=kind):
                report, worlds = synthetic_science_contract()
                if kind == "duplicated":
                    worlds[1] = copy.deepcopy(worlds[0])
                elif kind == "missing":
                    worlds.pop()
                elif kind == "wrong_scope":
                    worlds[0]["scope"] = "random-world-999"
                else:
                    worlds[0]["status"] = "FAIL"
                with self.assertRaises(ValueError):
                    _verify_counterexample_contract(report, worlds)

    def test_counterexample_rejects_nonfinite_or_inconsistent_null_statistics(self) -> None:
        for field, bad in (("worlds", True), ("worlds", "300"), ("worlds", 299),
                           ("false_promotions", False), ("false_promotions", -1),
                           ("false_promotions", 1), ("false_promotions", 301),
                           ("false_positive_rate", float("nan")),
                           ("false_positive_rate", float("inf")),
                           ("false_positive_rate", -0.01), ("false_positive_rate", 0.1),
                           ("false_positive_rate", False), ("false_positive_rate", "0"),
                           ("observed_percentile", float("nan")),
                           ("observed_percentile", 1.1)):
            with self.subTest(field=field, bad=bad):
                report, worlds = synthetic_science_contract()
                report["result"]["null_world"][field] = bad
                with self.assertRaises(ValueError):
                    _verify_counterexample_contract(report, worlds)

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
