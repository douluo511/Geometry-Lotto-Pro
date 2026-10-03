from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

HARD_GATES = [
    "purpose_model",
    "five_why",
    "risk_boundary",
    "domain_model",
    "architecture",
    "function_contract",
    "interface_contract",
    "data_source",
    "netclient",
    "storage",
    "engine",
    "evidence",
    "service",
    "ui",
    "self_test",
    "unit_test",
    "contract_test",
    "integration_test",
    "fault_injection",
    "real_network",
    "business_validation",
    "counterexample_validation",
    "reversal_validation",
    "windows_build",
    "exact_exe",
    "gui_smoke",
    "same_hash",
    "business_content",
    "updater_process",
    "updater_exact_exe",
    "updater_atomic_rollback",
    "updater_real_network",
    "updater_same_hash",
    "repository_independence",
]


def evaluate(report: dict) -> dict:
    statuses = report.get("gates", {})
    allowed = {"PASS", "FAIL", "NOT VERIFIED", "BLOCKED"}
    normalized = {k: str(statuses.get(k, "NOT VERIFIED")).upper() for k in HARD_GATES}
    normalized = {k: (v if v in allowed else "FAIL") for k, v in normalized.items()}
    bad = {k: v for k, v in normalized.items() if v != "PASS"}
    return {
        "final_gate": "PASS" if not bad else "FAIL",
        "hard_fail_count": len(bad),
        "gates": normalized,
        "failures": bad,
        "exe_sha256": report.get("exe_sha256"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "github_sha": report.get("github_sha"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    result = evaluate(json.loads(Path(a.input).read_text(encoding="utf-8-sig")))
    Path(a.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["final_gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
