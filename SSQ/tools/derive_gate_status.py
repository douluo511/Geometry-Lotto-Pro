"""Derive only the SSQ release gates that current-run artifacts actually prove.

Unimplemented evidence contracts remain PENDING.  This deliberately prevents a
build or an EXE smoke check from manufacturing a full-system Final Gate PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from release_gate_22 import HARD_GATES

REQUIRED_EXE_CHECKS = frozenset({
    "self", "integrity-tamper", "offline-failclosed", "corrupt-repair",
    "update", "science", "random-world-101", "random-world-202",
    "random-world-303", "predict", "audit", "gui",
    "unicode-path-no-python-path", "default-gui-launch",
})


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_recent(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=24) <= stamp <= now + timedelta(minutes=5)


def _raw_status_allowed(http_status: Any, receipt_status: str) -> bool:
    # A failed source is allowed in an otherwise valid two-source fallback only
    # as a documented FAIL, never as a successful 200 receipt. The Store's
    # independent validator verifies the actual status range and raw bytes.
    return receipt_status == "FAIL" or (receipt_status == "PASS" and http_status == 200)


def _verify_gui_evidence(physical: dict[str, Any], evidence_dir: Path, exe: Path,
                         acceptance_ok: bool) -> dict[str, Any]:
    if (not acceptance_ok or not exe.is_file()
            or physical.get("schema") != "physical-gui-click-smoke-v2"
            or physical.get("status") != "PASS"
            or physical.get("coordinate_fallback") is not False
            or physical.get("visual_hash_as_proof") is not False
            or physical.get("exe") != exe.name
            or physical.get("exe_sha256") != _hash(exe)
            or physical.get("github_sha") != os.environ.get("GITHUB_SHA")
            or physical.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or not _utc_recent(physical.get("tested_at"))):
        raise ValueError("physical GUI report is not bound to the exact current-run EXE")
    buttons = physical.get("buttons")
    expected = ((101, "predict"), (102, "update"), (103, "repair"), (104, "audit"))
    if not isinstance(buttons, list) or len(buttons) != len(expected):
        raise ValueError("four exact child controls were not exercised")
    from verify_gui_effect import EVENT_KINDS, inspect_effect
    seen_dirs: set[str] = set()
    ledgers: list[dict[str, Any]] = []
    for index, (row, (control_id, operation)) in enumerate(zip(buttons, expected), 1):
        if not isinstance(row, dict):
            raise ValueError("physical GUI button row is malformed")
        before = row.get("before_output_sha256")
        after = row.get("after_output_sha256")
        leaf = row.get("data_dir")
        effect = row.get("backend_effect")
        if (row.get("button_index") != index or row.get("control_id") != control_id
                or row.get("operation") != operation or row.get("status") != "PASS"
                or row.get("control_class") != "BUTTON"
                or not isinstance(row.get("control_name"), str) or not row["control_name"]
                or not isinstance(row.get("process_id"), int) or row["process_id"] <= 0
                or any(row.get(flag) is not True for flag in (
                    "control_verified", "physical_click_verified", "output_verified",
                    "backend_effect_verified"))
                or not isinstance(before, str) or not re.fullmatch(r"[0-9a-f]{64}", before)
                or not isinstance(after, str) or not re.fullmatch(r"[0-9a-f]{64}", after)
                or before == after or not isinstance(leaf, str)
                or not re.fullmatch(r"physical-gui-run-[0-9a-f]{32}", leaf)
                or leaf in seen_dirs or not isinstance(effect, dict)):
            raise ValueError(f"physical GUI row {index} lacks exact control/output proof")
        seen_dirs.add(leaf)
        data_dir = evidence_dir / leaf
        before_path = data_dir / "gui_before.txt"
        after_path = data_dir / "gui_after.txt"
        if (row.get("before_output_artifact") != f"{leaf}/gui_before.txt"
                or row.get("after_output_artifact") != f"{leaf}/gui_after.txt"
                or not before_path.is_file() or not after_path.is_file()
                or row.get("before_output_artifact_sha256") != _hash(before_path)
                or row.get("after_output_artifact_sha256") != _hash(after_path)
                or before != _hash(before_path) or after != _hash(after_path)):
            raise ValueError(f"physical GUI row {index} lacks exact raw output artifacts")
        after_text = after_path.read_text(encoding="utf-8")
        markers = row.get("output_markers")
        if (not isinstance(markers, list) or len(markers) != 2
                or not all(isinstance(marker, str) and marker and marker in after_text
                           for marker in markers)
                or not isinstance(row.get("after_status"), str)
                or "FAIL" in row["after_status"].upper()):
            raise ValueError(f"physical GUI row {index} has no inspectable operation output")
        observed = inspect_effect(data_dir, operation, 0)
        fields = ("status", "operation", "after_id", "experiment_id", "kind",
                  "event_status", "payload_sha256", "display_token")
        if (observed.get("status") != "PASS"
                or observed.get("kind") not in EVENT_KINDS[operation]
                or not isinstance(observed.get("display_token"), str)
                or not observed["display_token"]
                or row.get("displayed_backend_token") != observed["display_token"]
                or observed["display_token"] not in after_text
                or not all(effect.get(field) == observed.get(field) for field in fields)):
            raise ValueError(f"physical GUI row {index} is not backed by a matching ledger event")
        if operation == "update":
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
            from glp.storage import Store
            source_manifest = _read(data_dir / "source_evidence.json")
            if not source_manifest or Store.validate_raw_evidence(source_manifest, data_dir) < 1:
                raise ValueError("GUI update did not preserve verified official raw responses")
        ledger_path = data_dir / "ledger.sqlite3"
        ledgers.append({"operation": operation, "experiment_id": observed["experiment_id"],
                        "ledger_sha256": _hash(ledger_path)})
    return {"ledgers": ledgers}


def _verify_live_evidence(evidence_dir: Path, exe_hash: str) -> dict[str, Any]:
    update_path = evidence_dir / "update.json"
    update = _read(update_path)
    if update is None or not update:
        raise ValueError("exact-EXE update result is missing or malformed")
    result = update.get("result")
    if (update.get("status") != "PASS" or update.get("game") != "SSQ"
            or update.get("scope") != "update" or update.get("platform") != "win32"
            or update.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or update.get("github_sha") != os.environ.get("GITHUB_SHA")
            or update.get("exe_sha256") != exe_hash or not isinstance(result, dict)
            or result.get("crosscheck_status") != "PASS"
            or not isinstance(result.get("persisted_integrity"), dict)
            or result["persisted_integrity"].get("ok") is not True):
        raise ValueError("exact-EXE live update or strict persistence integrity did not PASS")
    preservation = result.get("preserved_live_evidence")
    manifest_path = evidence_dir / "update-source-evidence.json"
    canonical_path = evidence_dir / "update-canonical-history.json"
    if (not isinstance(preservation, dict) or preservation.get("status") != "PASS"
            or preservation.get("manifest") != manifest_path.name
            or preservation.get("manifest_sha256") != _hash(manifest_path)):
        raise ValueError("live response preservation proof is missing or hash-mismatched")
    if (preservation.get("canonical") != canonical_path.name
            or preservation.get("canonical_sha256") != _hash(canonical_path)):
        raise ValueError("canonical history preservation proof is missing or hash-mismatched")
    manifest = _read(manifest_path)
    if (manifest is None or manifest.get("schema") != "official-source-evidence-v8.5"
            or manifest.get("raw_response_status") != "PASS"
            or manifest.get("crosscheck_status") != "PASS"
            or manifest.get("canonical_hash") != result.get("canonical_hash")
            or manifest.get("source_receipts") != result.get("source_receipts")):
        raise ValueError("live source manifest is not bound to the exact-EXE result")
    canonical = _read(canonical_path)
    draws = canonical.get("draws") if canonical is not None else None
    if (not isinstance(draws, list) or not draws
            or canonical.get("game") != "SSQ"
            or canonical.get("canonical_hash") != result.get("canonical_hash")
            or len(draws) != result.get("draw_count")
            or draws[-1] != manifest.get("latest")
            or draws[-1].get("issue") != result.get("latest_issue")
            or hashlib.sha256(json.dumps(draws, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
               != canonical.get("canonical_hash")):
        raise ValueError("preserved canonical history is not bound to live evidence")
    records = manifest.get("raw_responses")
    if (not isinstance(records, list) or not records
            or preservation.get("raw_response_count") != len(records)):
        raise ValueError("raw response set is incomplete")
    # Re-run the Store's full receipt/page/quorum validator against the copied
    # acceptance artifacts, not the temporary data directory the EXE used.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
    from glp.storage import Store
    verified_count = Store.validate_raw_evidence(manifest, evidence_dir)
    if verified_count != len(records):
        raise ValueError("validated raw response count differs from manifest")
    lineage = manifest.get("baseline_lineage")
    baseline_records = lineage.get("raw_responses", []) if isinstance(lineage, dict) else []
    if preservation.get("baseline_raw_response_count") != len(baseline_records):
        raise ValueError("preserved fallback lineage artifact count differs from manifest")
    Store._check_baseline_prefix(manifest, draws)
    receipts = manifest.get("source_receipts")
    if (not isinstance(receipts, list) or len(receipts) != 3
            or sum(isinstance(item, dict) and item.get("status") == "PASS" for item in receipts) < 2):
        raise ValueError("official source quorum is unproven")
    receipt_status = {item["source"]: item["status"] for item in receipts}
    if (len(receipt_status) != 3
            or any(status not in {"PASS", "FAIL"} for status in receipt_status.values())):
        raise ValueError("official source receipt state is incomplete")
    official_hosts = {
        "official_cwl_L0": "www.cwl.gov.cn",
        "official_shanghai_L1": "www.swlc.net.cn",
        "official_hebei_L2": "www.yzfcw.com",
    }
    from urllib.parse import urlsplit
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("raw response record is malformed")
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("raw response hash is invalid")
        url = urlsplit(str(record.get("url", "")))
        source = record.get("source")
        if (source not in official_hosts
                or url.scheme != "https" or url.hostname != official_hosts[source]
                or not _raw_status_allowed(record.get("http_status"), receipt_status[source])
                or not _utc_recent(record.get("fetched_at"))
                or record.get("artifact") != f"raw_responses/{digest}.bin"):
            raise ValueError("raw response source, freshness or provenance is invalid")
        artifact = evidence_dir / "raw_responses" / f"{digest}.bin"
        if (not artifact.is_file() or artifact.stat().st_size != record.get("bytes")
                or _hash(artifact) != digest):
            raise ValueError("raw response bytes are missing or hash-mismatched")
    return {
        "result": str(update_path), "result_sha256": _hash(update_path),
        "manifest": str(manifest_path), "manifest_sha256": _hash(manifest_path),
        "canonical": str(canonical_path), "canonical_sha256": _hash(canonical_path),
        "raw_response_count": len(records),
    }


def derive(evidence: Path, exe: Path) -> dict[str, Any]:
    gates = {name: "PENDING" for name in HARD_GATES}
    proofs: dict[str, Any] = {}
    acceptance_path = evidence / "WINDOWS_EXACT_EXE_ACCEPTANCE.json"
    acceptance = _read(acceptance_path)
    acceptance_ok = False
    if acceptance is not None:
        checks = acceptance.get("checks")
        if not isinstance(checks, dict):
            checks = {}
        declared_hash = acceptance.get("sha256")
        actual_hash = _hash(exe) if exe.is_file() else None
        current_sha = os.environ.get("GITHUB_SHA")
        current_run = os.environ.get("GITHUB_RUN_ID")
        acceptance_ok = (
            acceptance.get("runner_os") == "Windows"
            and isinstance(current_sha, str) and bool(re.fullmatch(r"[0-9a-f]{40}", current_sha))
            and isinstance(current_run, str) and bool(re.fullmatch(r"\d+", current_run))
            and acceptance.get("github_sha") == current_sha
            and acceptance.get("github_run_id") == current_run
            and acceptance.get("artifact") == exe.name
            and bool(actual_hash)
            and actual_hash == declared_hash
            and acceptance.get("windows_exact_exe_acceptance") == "PASS"
            and acceptance.get("final_release_gate") == "PENDING"
            and acceptance.get("hard_fail_count") == 0
            and REQUIRED_EXE_CHECKS.issubset(checks)
            and all(
                isinstance(check, dict)
                and check.get("status") == "PASS"
                and check.get("exit_code") == 0
                and check.get("exe_hash_matches") is True
                for check in checks.values()
            )
        )
        gates["windows_build"] = "PASS" if acceptance_ok else "FAIL"
        gates["exact_exe"] = "PASS" if acceptance_ok else "FAIL"
        # Build/CLI checks prove only a narrow exact-EXE hash. The cross-stage
        # Same Hash gate also needs the physical GUI and live-network evidence.
        gates["same_hash"] = "PENDING" if acceptance_ok else "FAIL"
        proofs["exact_exe"] = {
            "report": str(acceptance_path),
            "report_sha256": _hash(acceptance_path),
            "actual_sha256": actual_hash,
            "declared_sha256": declared_hash,
        }
        self_check = checks.get("self")
        gates["self_test"] = (
            "PASS" if acceptance_ok and isinstance(self_check, dict)
            and self_check.get("status") == "PASS"
            and self_check.get("exe_hash_matches") is True else "FAIL"
        )
        live_check = checks.get("update")
        if not acceptance_ok or not isinstance(live_check, dict) or live_check.get("status") != "PASS":
            gates["real_network"] = "FAIL"
        else:
            # The EXE result alone is insufficient: independently read and hash
            # every preserved raw response from this exact candidate run.
            try:
                proofs["real_network"] = _verify_live_evidence(evidence, actual_hash)
                # Raw hashes, receipts and quorum are necessary but not yet a
                # sufficient independent RAW -> CANONICAL proof. Until every
                # saved body is reparsed and compared to the exact canonical
                # dataset, this hard gate must remain unpassed.
                proofs["real_network"]["canonical_reparse"] = "PENDING"
                gates["real_network"] = "PENDING"
            except (OSError, TypeError, ValueError, KeyError) as exc:
                gates["real_network"] = "FAIL"
                proofs["real_network"] = {"error": f"{type(exc).__name__}: {exc}"}
    physical_path = evidence / "physical_gui_click.json"
    physical = _read(physical_path)
    if physical is not None:
        try:
            gui_proof = _verify_gui_evidence(physical, evidence, exe, acceptance_ok)
            gates["gui_smoke"] = "PASS"
            proofs["gui_smoke"] = {"report": str(physical_path),
                                   "report_sha256": _hash(physical_path), **gui_proof}
        except (OSError, TypeError, ValueError, KeyError) as exc:
            gates["gui_smoke"] = "FAIL"
            proofs["gui_smoke"] = {"error": f"{type(exc).__name__}: {exc}"}
            gates["same_hash"] = "FAIL"
    if (acceptance_ok and gates["gui_smoke"] == "PASS"
            and gates["real_network"] == "PASS"):
        gates["same_hash"] = "PASS"
    return {
        "schema": "ssq-current-run-gate-evidence-v1",
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "gates": gates,
        "proofs": proofs,
        "rule": "Only a directly verified current-run artifact can set PASS; all other gates remain PENDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = derive(args.evidence_dir, args.exe)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
