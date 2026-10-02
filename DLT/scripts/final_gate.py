from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from completion_boundary import completion_states

FINAL_SCHEMA = "dlt-evidence-derived-final-gate-v4"
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
    business = _load(root / "business_no_shell_gate.json")
    updater = _load(root / "updater_acceptance.json")
    repro = _load(root / "reproducible_main_build.json")
    completion = completion_states(business)

    github_sha = os.environ.get("GITHUB_SHA")
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    repository = os.environ.get("GITHUB_REPOSITORY")
    event = os.environ.get("GITHUB_EVENT_NAME")
    ref = os.environ.get("GITHUB_REF")

    updater_exe = exe.with_name("Geometry_Lotto_Pro_DLT_Updater.exe")
    updater_hash = _sha256(updater_exe) if updater_exe.is_file() else ""

    # Static source inspection is only a prerequisite.  no_shell may become PASS
    # only when this exact EXE has 4/4 physical GUI activations bound to 4/4
    # backend operation evidence.  This closes the runtime-binding gap without
    # allowing static symbols/strings to claim a complete product.
    backend_ops = gui_backend.get("operations") if isinstance(gui_backend.get("operations"), list) else []
    expected_ids = {1001, 1002, 1003, 1004}
    observed_ids = {
        row.get("operation_id") for row in backend_ops
        if isinstance(row, dict) and row.get("status") == "PASS"
    }
    runtime_no_shell_ok = (
        completion.get("no_shell") == "PENDING"
        and gui_visual.get("status") == "PASS"
        and len(gui_visual.get("buttons") or []) == 4
        and gui_backend.get("status") == "PASS"
        and gui_backend.get("exe_sha256") == exe_hash
        and len(backend_ops) == 4
        and observed_ids == expected_ids
    )
    no_shell_state = "PASS" if runtime_no_shell_ok else completion.get("no_shell", "FAIL")

    repository_ok = repository == INDEPENDENT_REPOSITORY
    release_context_ok = (
        repository_ok
        and ref == "refs/heads/main"
        and event in {"push", "workflow_dispatch"}
    )
    # Business completion is broader than static inventory.  It requires the
    # runtime-bound four entries, real official data, the independent updater
    # data-network path, and the real Release N->N+1 software-update proof from
    # the independent production main.  Until then it remains PENDING.
    business_runtime_ok = (
        completion.get("business_content") == "PENDING"
        and runtime_no_shell_ok
        and live.get("status") == "PASS"
        and updater.get("updater_data_real_network") == "PASS"
        and updater.get("updater_real_network") == "PASS"
        and repository_ok
        and release_context_ok
    )
    business_content_state = (
        "PASS" if business_runtime_ok
        else completion.get("business_content", "FAIL")
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
        "business_content": business_content_state,
        "no_shell": no_shell_state,
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
        # This specifically means real software Release N -> N+1 over HTTPS,
        # not the official lottery-data network exercised above.
        "updater_real_network": "PASS" if updater.get("updater_real_network") == "PASS" else "PENDING",
        "repository_independence": _status(repository_ok),
        "release_context": _status(release_context_ok),
    }

    hard_fail = [name for name, status in gates.items() if status != "PASS"]
    final = {
        "schema": FINAL_SCHEMA,
        "final_gate": "PASS" if not hard_fail else "FAIL",
        "hard_fail_count": len(hard_fail),
        "non_pass_gates": hard_fail,
        "gates": gates,
        "exe_sha256": exe_hash,
        "updater_sha256": updater_hash,
        "github_sha": github_sha,
        "github_run_id": github_run_id,
        "repository": repository,
        "event": event,
        "ref": ref,
        "evidence_dir": str(root),
        "rule": "all hard gates must be explicit PASS; PENDING/SKIPPED/WARNING/UNKNOWN/FAIL never count as PASS",
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
