from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

FINAL_SCHEMA = "dlt-evidence-derived-final-gate-v6"
INDEPENDENT_REPOSITORY = "douluo511/Geometry-Lotto-Pro-DLT"
NON_PASS = {"FAIL", "PENDING", "SKIPPED", "WARNING", "UNKNOWN", "UNAVAILABLE", "BLOCKED", "NOT_PASS", None, ""}


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "MISSING", "_missing": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"status": "INVALID", "_error": f"{type(exc).__name__}: {exc}"}
    return value if isinstance(value, dict) else {"status": "INVALID", "_error": "root is not an object"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def derive(evidence_dir: str | Path, exact_exe: str | Path) -> dict[str, Any]:
    root = Path(evidence_dir).resolve()
    exe = Path(exact_exe).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"exact EXE missing: {exe}")
    exe_hash = _sha256(exe)

    contract = _load(root / "network_contract_gate.json")
    fault = _load(root / "network_fault_gate.json")
    live = _load(root / "real_network_check.json")
    accept = _load(root / "acceptance.json")
    gui_visual = _load(root / "physical_gui_click.json")
    gui_backend = _load(root / "physical_gui_backend.json")
    gui_failure = _load(root / "physical_gui_failure.json")
    gui_repair_failure = _load(root / "physical_gui_repair_failure.json")
    business_static = _load(root / "business_no_shell_gate.json")
    business_runtime = _load(root / "business_runtime_gate.json")
    updater = _load(root / "updater_acceptance.json")
    repro = _load(root / "reproducible_main_build.json")

    github_sha = os.environ.get("GITHUB_SHA")
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    event = os.environ.get("GITHUB_EVENT_NAME")
    ref = os.environ.get("GITHUB_REF")

    updater_exe = exe.with_name("Geometry_Lotto_Pro_DLT_Updater.exe")
    updater_hash = _sha256(updater_exe) if updater_exe.is_file() else ""

    static_valid = (
        business_static.get("schema") == "dlt-static-interface-precheck-v2"
        and business_static.get("scope") == "STATIC_INTERFACE_PRECHECK_ONLY"
        and business_static.get("status") == "PASS"
        and business_static.get("github_sha") == github_sha
        and str(business_static.get("github_run_id")) == str(github_run_id)
    )
    runtime_valid = (
        business_runtime.get("schema") == "dlt-business-runtime-gate-v1"
        and business_runtime.get("github_sha") == github_sha
        and str(business_runtime.get("github_run_id")) == str(github_run_id)
        and business_runtime.get("exe_sha256") == exe_hash
        and business_runtime.get("updater_sha256") == updater_hash
        and business_runtime.get("approval_status") in {"PASS", "PENDING"}
        and business_runtime.get("original_requirements_preserved") is True
        and static_valid
    )
    business_content = (
        str(business_runtime.get("business_content"))
        if runtime_valid and business_runtime.get("business_content") in {"PASS", "PENDING", "FAIL"}
        else "FAIL"
    )
    no_shell = (
        "PASS"
        if runtime_valid and business_runtime.get("no_shell") == "PASS"
        else "FAIL"
    )

    gates: dict[str, str] = {
        "contract_test": _status(contract.get("status") == "PASS"),
        "fault_injection": _status(fault.get("status") == "PASS"),
        "real_network": _status(live.get("status") == "PASS"),
        "windows_build": _status(accept.get("windows_runtime_gate") == "PASS"),
        "exact_exe": _status(
            accept.get("exact_acceptance_gate") == "PASS"
            and accept.get("final_release_gate") == "PENDING"
            and accept.get("exe_sha256") == exe_hash
            and accept.get("github_sha") == github_sha
            and str(accept.get("github_run_id")) == str(github_run_id)
        ),
        "same_hash": _status(
            repro.get("status") == "PASS"
            and repro.get("same_hash") is True
            and repro.get("primary_sha256") == exe_hash
            and repro.get("rebuild_sha256") == exe_hash
            and repro.get("github_sha") == github_sha
            and str(repro.get("github_run_id")) == str(github_run_id)
        ),
        "physical_gui_visual": _status(
            gui_visual.get("status") == "PASS"
            and len(gui_visual.get("buttons") or []) == 4
        ),
        "physical_gui_backend": _status(
            gui_backend.get("status") == "PASS"
            and gui_backend.get("exe_sha256") == exe_hash
            and len(gui_backend.get("operations") or []) == 4
        ),
        "physical_gui_failure": _status(
            gui_failure.get("schema") == "dlt-physical-gui-failure-v1"
            and gui_failure.get("status") == "PASS"
            and gui_failure.get("operation") == "update"
            and gui_failure.get("exe_sha256") == exe_hash
            and gui_failure.get("updater_sha256") == updater_hash
            and gui_failure.get("github_sha") == github_sha
            and str(gui_failure.get("github_run_id")) == str(github_run_id)
            and gui_failure.get("backend_status") == "FAIL"
            and gui_failure.get("ui_fail_closed") is True
            and gui_failure.get("updater_failure_exact_hash") is True
            and gui_failure.get("updater_failure_parent_bound") is True
            and int(gui_failure.get("updater_failure_count") or 0) >= 1
            and gui_failure.get("canonical_unchanged") is True
            and gui_failure.get("evidence_unchanged") is True
            and int(gui_failure.get("official_update_pass_increment", -1)) == 0
            and int(gui_failure.get("official_update_fail_increment", 0)) >= 1
        ),
        "physical_gui_repair_failure": _status(
            gui_repair_failure.get("schema") == "dlt-physical-gui-failure-v1"
            and gui_repair_failure.get("status") == "PASS"
            and gui_repair_failure.get("operation") == "repair"
            and gui_repair_failure.get("exe_sha256") == exe_hash
            and gui_repair_failure.get("updater_sha256") == updater_hash
            and gui_repair_failure.get("github_sha") == github_sha
            and str(gui_repair_failure.get("github_run_id")) == str(github_run_id)
            and gui_repair_failure.get("backend_status") == "FAIL"
            and gui_repair_failure.get("ui_fail_closed") is True
            and gui_repair_failure.get("updater_failure_exact_hash") is True
            and gui_repair_failure.get("updater_failure_parent_bound") is True
            and int(gui_repair_failure.get("updater_failure_count") or 0) >= 1
            and gui_repair_failure.get("corruption_injected") is True
            and gui_repair_failure.get("canonical_unchanged") is True
            and gui_repair_failure.get("evidence_unchanged") is True
            and int(gui_repair_failure.get("official_update_pass_increment", -1)) == 0
            and int(gui_repair_failure.get("repair_pass_increment", -1)) == 0
            and int(gui_repair_failure.get("repair_fail_increment", 0)) >= 1
        ),
        "business_content": business_content,
        "no_shell": no_shell,
        "updater_process": _status(
            updater.get("schema") == "dlt-updater-exact-acceptance-v1"
            and updater.get("github_sha") == github_sha
            and str(updater.get("github_run_id")) == str(github_run_id)
            and updater.get("updater_process") == "PASS"
            and updater.get("updater_sha256") == updater_hash
        ),
        "updater_exact_exe": _status(
            updater.get("updater_exact_exe") == "PASS"
            and updater.get("updater_sha256") == updater_hash
        ),
        "updater_atomic_rollback": _status(updater.get("updater_atomic_rollback") == "PASS"),
        "updater_data_real_network": _status(updater.get("updater_data_real_network") == "PASS"),
        "updater_same_hash": _status(updater.get("updater_same_hash") == "PASS"),
        "updater_real_network": "PASS" if updater.get("updater_real_network") == "PASS" else "PENDING",
        "repository_independence": _status(repository == INDEPENDENT_REPOSITORY),
        "release_context": _status(
            repository == INDEPENDENT_REPOSITORY
            and ref == "refs/heads/main"
            and event in {"push", "workflow_dispatch"}
        ),
    }

    hard_fail = [name for name, status in gates.items() if status != "PASS"]
    final = {
        "schema": FINAL_SCHEMA,
        "final_gate": "PASS" if not hard_fail else "FAIL",
        "hard_fail_count": len(hard_fail),
        "non_pass_gates": hard_fail,
        "gates": gates,
        "business_runtime_schema": business_runtime.get("schema"),
        "business_runtime_status": business_runtime.get("status"),
        "business_tasks": business_runtime.get("tasks"),
        "business_runtime_valid": runtime_valid,
        "exe_sha256": exe_hash,
        "updater_sha256": updater_hash,
        "github_sha": github_sha,
        "github_run_id": github_run_id,
        "repository": repository,
        "event": event,
        "ref": ref,
        "evidence_dir": str(root),
        "rule": "all hard gates must be explicit PASS; PENDING/SKIPPED/WARNING/UNKNOWN/FAIL never count as PASS; business/no-shell require current-run runtime evidence, never static source inspection alone",
    }
    return final


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--exe", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    result = derive(args.evidence_dir, args.exe)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if result["final_gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
