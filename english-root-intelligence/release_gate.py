from __future__ import annotations
import argparse,json
import os
from pathlib import Path
from gate_common import current_report, run_identity
HARD_GATES=[
    "purpose_model","five_why","risk_boundary","domain_model","architecture",
    "function_contract","interface_contract","data_source","netclient","storage",
    "engine","evidence","service","ui","self_test","unit_test","contract_test",
    "integration_test","fault_injection","real_network","business_validation",
    "counterexample_validation","reversal_validation","windows_build","exact_exe",
    "gui_smoke","same_hash","business_content","updater_process","updater_exact_exe",
    "updater_atomic_rollback","updater_real_network","updater_same_hash","repository_independence",
    "static_compile","final_artifact"
]
BUSINESS_GATES = {"business_content", "business_validation", "counterexample_validation", "reversal_validation"}


def validate_mother(data, source_sha):
    gates = {key: data.get("gates", {}).get(key, "NOT VERIFIED") for key in HARD_GATES}
    failures = {key: value for key, value in gates.items() if value != "PASS"}
    engineering = 100 * sum(value == "PASS" for key, value in gates.items() if key not in BUSINESS_GATES) / (len(HARD_GATES) - len(BUSINESS_GATES))
    business = 100 * sum(gates[key] == "PASS" for key in BUSINESS_GATES) / len(BUSINESS_GATES)
    if (not current_report(data, source_sha) or data.get("schema") != "english-root-mother-gate-input-v1"
            or data.get("status") != ("PASS" if not failures else "FAIL")
            or data.get("hard_fail_count") != len(failures)
            or data.get("engineering_completion") != engineering or data.get("business_completion") != business
            or data.get("combined_completion") != min(engineering, business)):
        failures["mother_evidence_binding"] = "FAIL"
    return {"schema": "english-root-final-gate-v2", "status": "PASS" if not failures else "FAIL",
            "final_gate": "PASS" if not failures else "FAIL", "github_sha": source_sha, **run_identity(),
            "engineering_completion": engineering, "business_completion": business,
            "combined_completion": min(engineering, business), "hard_fail_count": len(failures),
            "gates": gates, "failures": failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    result = validate_mother(data, os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA"))
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["final_gate"] == "PASS" else 2
if __name__=="__main__": raise SystemExit(main())
