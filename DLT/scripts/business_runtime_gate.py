from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from glp.delivery import create_backup, export_evidence, restore_backup, verify_export
from glp.storage import Store

SCHEMA = "dlt-business-runtime-gate-v1"
INDEPENDENT_REPOSITORY = "douluo511/Geometry-Lotto-Pro-DLT"
SCOPE_IDS = ("B01", "B02", "B03", "B04", "B05", "B06", "B07")
ENTRY_IDS = ("predict", "update", "repair", "audit")
GUI_IDS = (1001, 1002, 1003, 1004)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: root must be an object")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pass_or_fail(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def task(status: str, purpose: str, evidence: list[str], reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "purpose": purpose, "evidence": evidence, "reason": reason}


def operation_map(summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = summary.get("operations")
    if not isinstance(rows, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            key = int(row.get("operation_id"))
        except (TypeError, ValueError):
            continue
        if key in out:
            raise ValueError(f"duplicate GUI operation id: {key}")
        out[key] = row
    return out


def load_operation(row: dict[str, Any], expected_id: int) -> tuple[dict[str, Any], Path]:
    path = Path(str(row.get("evidence_path", ""))).resolve()
    value = load_json(path)
    if value.get("schema") != "dlt-physical-gui-backend-v1":
        raise ValueError(f"operation {expected_id}: schema mismatch")
    if value.get("status") != "PASS" or int(value.get("operation_id", -1)) != expected_id:
        raise ValueError(f"operation {expected_id}: backend is not bound PASS")
    return value, path


def maintenance_proof(source_data: Path) -> dict[str, Any]:
    if not source_data.is_dir():
        raise FileNotFoundError(f"maintenance source data missing: {source_data}")
    with tempfile.TemporaryDirectory(prefix="dlt-business-maint-") as td:
        root = Path(td)
        working = root / "working"
        shutil.copytree(source_data, working)
        before = Store(working).integrity_check()
        if before.get("status") != "PASS":
            raise ValueError("maintenance source Store integrity is not PASS")

        backup = create_backup(working, root / "backup")
        history = working / "canonical_history.json"
        history.write_bytes(history.read_bytes() + b"\nCORRUPTION_INJECTION\n")
        corrupted = Store(working).integrity_check()
        if corrupted.get("status") == "PASS":
            raise ValueError("corruption injection was not detected")

        restored = restore_backup(Path(backup["backup_dir"]), working)
        after = Store(working).integrity_check()
        if restored.get("status") != "PASS" or after.get("status") != "PASS":
            raise ValueError("backup restore did not recover PASS integrity")

        exported = export_evidence(working, root / "export")
        verified = verify_export(Path(exported["export_dir"]))
        if exported.get("status") != "PASS" or verified.get("status") != "PASS":
            raise ValueError("Evidence export/reverification did not PASS")

        manifest = exported["manifest"]
        rows = manifest.get("files") or []
        if not rows:
            raise ValueError("Evidence export manifest has no files")
        tamper_target = Path(exported["export_dir"]) / str(rows[0]["name"])
        tamper_target.write_bytes(tamper_target.read_bytes() + b"tamper")
        tamper_rejected = False
        try:
            verify_export(Path(exported["export_dir"]))
        except Exception:
            tamper_rejected = True
        if not tamper_rejected:
            raise ValueError("tampered Evidence export was not rejected")

        return {
            "status": "PASS",
            "before_integrity": before.get("status"),
            "corruption_detected": corrupted.get("status") != "PASS",
            "restore_status": restored.get("status"),
            "after_integrity": after.get("status"),
            "export_status": exported.get("status"),
            "verify_status": verified.get("status"),
            "tamper_rejected": tamper_rejected,
            "backup_file_count": len((backup.get("manifest") or {}).get("files") or []),
            "export_file_count": len(rows),
        }


def derive(evidence_dir: Path, exe: Path) -> dict[str, Any]:
    root = evidence_dir.resolve()
    exe = exe.resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"Exact EXE missing: {exe}")
    exe_hash = sha256_file(exe)
    updater_exe = exe.with_name("Geometry_Lotto_Pro_DLT_Updater.exe")
    if not updater_exe.is_file():
        raise FileNotFoundError(f"Exact Updater missing: {updater_exe}")
    updater_hash = sha256_file(updater_exe)

    github_sha = os.environ.get("GITHUB_SHA")
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    event = os.environ.get("GITHUB_EVENT_NAME")
    ref = os.environ.get("GITHUB_REF")

    approval = load_json(Path("BUSINESS_SCOPE_APPROVAL.json"))
    baseline = load_json(Path("BUSINESS_ACCEPTANCE_BASELINE.json"))
    static = load_json(root / "business_no_shell_gate.json")
    live = load_json(root / "real_network_check.json")
    fault = load_json(root / "network_fault_gate.json")
    acceptance = load_json(root / "acceptance.json")
    self_test = load_json(root / "self_test.json")
    gui_visual = load_json(root / "physical_gui_click.json")
    gui_backend = load_json(root / "physical_gui_backend.json")
    updater = load_json(root / "updater_acceptance.json")

    approval_ok = (
        approval.get("schema") == "dlt-business-scope-approval-v1"
        and approval.get("project") == "DLT"
        and approval.get("status") == "APPROVED"
        and approval.get("approved_by") == "user"
        and tuple(approval.get("scope_ids") or ()) == SCOPE_IDS
        and tuple(approval.get("entry_inventory") or ()) == ENTRY_IDS
        and approval.get("original_requirements_preserved") is True
        and approval.get("no_scope_reduction") is True
        and bool(str(approval.get("approval_reference", "")).strip())
        and baseline.get("schema") == "dlt-business-acceptance-baseline-v1"
        and tuple((baseline.get("tasks") or {}).keys()) == SCOPE_IDS
        and tuple(baseline.get("entry_inventory") or ()) == ENTRY_IDS
        and baseline.get("scope_reduction_forbidden") is True
    )

    static_ok = (
        static.get("schema") == "dlt-static-interface-precheck-v2"
        and static.get("scope") == "STATIC_INTERFACE_PRECHECK_ONLY"
        and static.get("status") == "PASS"
        and static.get("github_sha") == github_sha
        and str(static.get("github_run_id")) == str(github_run_id)
        and all(row.get("status") == "PASS" for row in (static.get("checks") or []))
    )

    ops = operation_map(gui_backend)
    gui_summary_ok = (
        gui_backend.get("schema") == "dlt-physical-gui-backend-summary-v1"
        and gui_backend.get("status") == "PASS"
        and gui_backend.get("exe_sha256") == exe_hash
        and tuple(sorted(ops)) == GUI_IDS
        and gui_visual.get("schema") == "physical-gui-click-smoke-v1"
        and gui_visual.get("status") == "PASS"
        and len(gui_visual.get("buttons") or []) == 4
        and all(row.get("status") == "PASS" and row.get("visual_changed") is True
                for row in (gui_visual.get("buttons") or []))
    )

    loaded_ops: dict[int, dict[str, Any]] = {}
    op_paths: dict[int, Path] = {}
    if gui_summary_ok:
        for op_id in GUI_IDS:
            value, path = load_operation(ops[op_id], op_id)
            loaded_ops[op_id] = value
            op_paths[op_id] = path

    update = (loaded_ops.get(1002) or {}).get("result") or {}
    predict = (loaded_ops.get(1001) or {}).get("result") or {}
    repair = (loaded_ops.get(1003) or {}).get("result") or {}
    audit = (loaded_ops.get(1004) or {}).get("result") or {}

    # Predict must be physically preceded by a real current-data Update in the same
    # process/data directory. The GUI precondition writes operation-1002.json beside
    # operation-1001.json; this prevents a stale packaged seed from passing B02.
    predict_preupdate: dict[str, Any] = {}
    if 1001 in op_paths:
        pre_path = op_paths[1001].parent / "operation-1002.json"
        if pre_path.is_file():
            predict_preupdate = load_json(pre_path)
    pre_result = predict_preupdate.get("result") or {}

    live_ok = (
        live.get("schema") == "dlt-real-network-check-v1"
        and live.get("status") == "PASS"
        and (live.get("evidence") or {}).get("freshness_gate") == "PASS"
        and live.get("crosscheck_status") == "PASS"
        and int(live.get("crosscheck_count") or 0) >= 10
        and all(row.get("status") == "PASS" and int(row.get("http_status") or 0) == 200
                and len(str(row.get("raw_sha256", ""))) == 64
                for row in ((live.get("evidence") or {}).get("source_receipts") or []))
    )
    update_ok = (
        update.get("network_gate") == "PASS"
        and update.get("freshness_gate") == "PASS"
        and update.get("crosscheck_status") == "PASS"
        and ((update.get("_updater") or {}).get("parent_pid_match") is True)
        and (update.get("_updater") or {}).get("updater_exe_sha256") == updater_hash
    )
    fault_ok = fault.get("status") == "PASS"

    pred_obj = predict.get("prediction") or {}
    trace = predict.get("effect_trace") or {}
    pre_latest = pre_result.get("latest") or {}
    prediction_ok = (
        predict_preupdate.get("schema") == "dlt-physical-gui-backend-v1"
        and predict_preupdate.get("status") == "PASS"
        and int(predict_preupdate.get("operation_id", -1)) == 1002
        and pre_result.get("network_gate") == "PASS"
        and pre_result.get("freshness_gate") == "PASS"
        and pre_result.get("crosscheck_status") == "PASS"
        and ((pre_result.get("_updater") or {}).get("parent_pid_match") is True)
        and (pre_result.get("_updater") or {}).get("updater_exe_sha256") == updater_hash
        and bool(pred_obj.get("freeze_hash"))
        and bool(pred_obj.get("target_issue"))
        and str(pred_obj.get("canonical_hash")) == str(pre_result.get("canonical_hash"))
        and str(pred_obj.get("canonical_hash")) == str(live.get("canonical_hash"))
        and int(str(pred_obj.get("target_issue"))) > int(str(pre_latest.get("issue")))
        and pred_obj.get("edge_state") in {"NO_EDGE", "EDGE_PROVEN"}
        and pred_obj.get("dan_state") in {"NULL_DAN", "CERTIFIED_DAN"}
        and (trace.get("complete_space") or {}).get("front") == 324632
        and (trace.get("complete_space") or {}).get("back") == 66
        and (
            pred_obj.get("edge_state") == "EDGE_PROVEN"
            or (
                (trace.get("production_weights") or {}).get("uniform_baseline") == 1.0
                and (trace.get("production_weights") or {}).get("research_ensemble") == 0.0
            )
        )
    )

    court = audit.get("court") or {}
    court_gates = court.get("gates") or []
    required_science = {
        "Data/Chronology", "Walk-forward", "Random Baseline", "Bootstrap/Permutation/Holm",
        "LOEO", "Ablation", "Null-world FPR", "Synthetic Null Worlds", "Leakage Sentinel",
        "Untouched Holdout", "Dual Final Confirmation", "Prospective Evidence", "Dan Firewall",
    }
    ablation = court.get("ablation") or {}
    reversal_rows: list[dict[str, Any]] = []
    for area in ("front", "back"):
        for name, row in (((ablation.get(area) or {}).get("components") or {}).items()):
            if isinstance(row, dict):
                reversal_rows.append(row)
    science_ok = (
        court.get("software_verdict") == "PASS"
        and court.get("scientific_gate") == "PASS"
        and audit.get("formal_freeze_written") is False
        and int(audit.get("freeze_before", -1)) == int(audit.get("freeze_after", -2))
        and required_science.issubset({str(row.get("name")) for row in court_gates})
        and all(row.get("status") == "PASS" for row in court_gates)
        and bool(reversal_rows)
        and all(all(k in row for k in ("remove", "shuffle", "random")) for row in reversal_rows)
        and court.get("edge_state") in {"NO_EDGE", "EDGE_PROVEN"}
        and court.get("dan_state") in {"NULL_DAN", "CERTIFIED_DAN"}
    )

    repair_ok = (
        (repair.get("after") or {}).get("status") == "PASS"
        and ((repair.get("_updater") or {}).get("parent_pid_match") is True)
        and (repair.get("_updater") or {}).get("updater_exe_sha256") == updater_hash
        and updater.get("updater_atomic_rollback") == "PASS"
        and fault_ok
    )

    updater_core_ok = (
        updater.get("schema") == "dlt-updater-exact-acceptance-v1"
        and updater.get("status") == "PASS"
        and updater.get("github_sha") == github_sha
        and str(updater.get("github_run_id")) == str(github_run_id)
        and updater.get("updater_sha256") == updater_hash
        and updater.get("updater_process") == "PASS"
        and updater.get("updater_exact_exe") == "PASS"
        and updater.get("updater_atomic_rollback") == "PASS"
        and updater.get("updater_same_hash") == "PASS"
        and updater.get("updater_data_real_network") == "PASS"
    )
    release_context_ok = (
        repository == INDEPENDENT_REPOSITORY
        and ref == "refs/heads/main"
        and event in {"push", "workflow_dispatch"}
    )
    b05_pass = updater_core_ok and updater.get("updater_real_network") == "PASS" and release_context_ok
    b05_status = "PASS" if b05_pass else ("PENDING" if updater_core_ok else "FAIL")

    no_shell_ok = (
        approval_ok and static_ok and gui_summary_ok
        and acceptance.get("exact_acceptance_gate") == "PASS"
        and acceptance.get("four_entry_gate") == "PASS"
        and acceptance.get("exe_sha256") == exe_hash
        and acceptance.get("github_sha") == github_sha
        and str(acceptance.get("github_run_id")) == str(github_run_id)
        and all(((loaded_ops.get(op_id) or {}).get("status") == "PASS") for op_id in GUI_IDS)
    )

    maintenance: dict[str, Any]
    try:
        update_data = op_paths[1002].parent / "data"
        maintenance = maintenance_proof(update_data)
    except Exception as exc:
        maintenance = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    maintenance_ok = (
        maintenance.get("status") == "PASS"
        and self_test.get("status") == "PASS"
        and self_test.get("production_store_modified") is False
        and fault_ok
    )

    tasks = {
        "B01": task(
            pass_or_fail(live_ok and update_ok and fault_ok),
            "Official-data update/source/freshness/conflict/raw-provenance integrity.",
            ["real_network_check", "physical_gui:update", "network_fault_gate"],
        ),
        "B02": task(
            pass_or_fail(prediction_ok),
            "Current-data traceable prediction with immutable Freeze and honest edge/dan state.",
            ["physical_gui:update-precondition", "physical_gui:predict", "exact_exe"],
            None if prediction_ok else "predict must use the exact current canonical hash and target an issue after the verified latest draw",
        ),
        "B03": task(
            pass_or_fail(science_ok),
            "Scientific/audit OOS, holdout, ablation/reversal, null-world, leakage and no-side-effect evidence.",
            ["physical_gui:audit", "Evidence Court"],
        ),
        "B04": task(
            pass_or_fail(repair_ok),
            "Corruption detection/repair, fault injection and atomic rollback.",
            ["physical_gui:repair", "network_fault_gate", "updater_atomic_rollback"],
        ),
        "B05": task(
            b05_status,
            "Independent Updater real software Release N→N+1 with hash/process/health/rollback proof.",
            ["updater_acceptance", "updater_real_network", "repository_independence", "release_context"],
            None if b05_status == "PASS" else "independent production Release N→N+1 proof is not closed",
        ),
        "B06": task(
            pass_or_fail(no_shell_ok),
            "All four physical GUI entries bound to the exact EXE and real backend; no shell/placeholder path.",
            ["business_no_shell_gate", "physical_gui_click", "physical_gui_backend", "exact_exe"],
        ),
        "B07": task(
            pass_or_fail(maintenance_ok),
            "Verified backup/restore, Evidence export/reverification/tamper rejection and user-data isolation.",
            ["maintenance_runtime", "self_test", "network_fault_gate"],
            None if maintenance_ok else maintenance.get("error"),
        ),
    }

    states = [tasks[x]["status"] for x in SCOPE_IDS]
    if "FAIL" in states or not approval_ok:
        business_content = "FAIL"
    elif all(x == "PASS" for x in states):
        business_content = "PASS"
    else:
        business_content = "PENDING"

    report = {
        "schema": SCHEMA,
        "status": "PASS" if approval_ok and "FAIL" not in states else "FAIL",
        "business_content": business_content,
        "no_shell": "PASS" if no_shell_ok else "FAIL",
        "tasks": tasks,
        "passed": sum(1 for x in states if x == "PASS"),
        "pending": sum(1 for x in states if x == "PENDING"),
        "failed": sum(1 for x in states if x == "FAIL"),
        "total": len(states),
        "approval_status": "PASS" if approval_ok else "FAIL",
        "approval_reference": approval.get("approval_reference"),
        "original_requirements_preserved": approval.get("original_requirements_preserved") is True,
        "maintenance": maintenance,
        "exe_sha256": exe_hash,
        "updater_sha256": updater_hash,
        "github_sha": github_sha,
        "github_run_id": github_run_id,
        "repository": repository,
        "event": event,
        "ref": ref,
        "release_authorized": business_content == "PASS" and no_shell_ok,
        "rule": "runtime evidence is required; static interface PASS alone never promotes business_content/no_shell; B05 requires real independent Release N->N+1",
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--exe", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    result = derive(Path(args.evidence_dir), Path(args.exe))
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    # Final Gate is the authority. PENDING/FAIL business states are persisted and
    # passed forward instead of terminating before final_gate.json can be produced.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
