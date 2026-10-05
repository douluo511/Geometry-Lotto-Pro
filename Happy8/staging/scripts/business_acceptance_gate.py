from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from happy8.science import DRAW_SIZE, PICK_SIZE, RANDOM_EXPECTATION, UNIVERSE

VALID_STATES = {"PASS", "FAIL", "NOT VERIFIED", "BLOCKED"}


def load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def valid_draws(rows: object) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        numbers = row.get("numbers")
        if (
            not isinstance(numbers, list)
            or len(numbers) != DRAW_SIZE
            or len(set(numbers)) != DRAW_SIZE
            or any(not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > UNIVERSE for n in numbers)
        ):
            return False
    return True


def item(status: str, evidence: dict, detail: str = "") -> dict:
    if status not in VALID_STATES:
        raise ValueError(f"invalid acceptance state {status}")
    return {"status": status, "detail": detail, "evidence": evidence}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True)
    parser.add_argument("--science", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--ui", required=True)
    parser.add_argument("--windows")
    parser.add_argument("--physical-gui")
    parser.add_argument("--real-release")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    baseline = load_json(PROJECT_ROOT / "BUSINESS_ACCEPTANCE_BASELINE.json")
    baseline_items = baseline.get("items")
    if not isinstance(baseline_items, list) or {x.get("id") for x in baseline_items} != {
        "B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08"
    }:
        raise RuntimeError("business baseline denominator drift")

    network = load_json(Path(args.network))
    science = load_json(Path(args.science))
    service = load_json(Path(args.service))
    ui = load_json(Path(args.ui))
    windows = load_json(Path(args.windows)) if args.windows else {}
    physical = load_json(Path(args.physical_gui)) if args.physical_gui else {}
    release = load_json(Path(args.real_release)) if args.real_release else {}

    checks = service.get("checks") if isinstance(service.get("checks"), dict) else {}
    protocol = science.get("protocol_gates") if isinstance(science.get("protocol_gates"), dict) else {}
    receipts = network.get("source_receipts") if isinstance(network.get("source_receipts"), list) else []
    canonical_hash = str(network.get("canonical_hash") or "")

    results: dict[str, dict] = {}

    b01_ok = (
        UNIVERSE == 80
        and DRAW_SIZE == 20
        and PICK_SIZE == 10
        and RANDOM_EXPECTATION == 2.5
        and valid_draws(network.get("draws"))
    )
    results["B01"] = item(
        "PASS" if b01_ok else "FAIL",
        {"universe": UNIVERSE, "draw_size": DRAW_SIZE, "pick_size": PICK_SIZE, "random_expected_hits": RANDOM_EXPECTATION},
    )

    b02_ok = (
        network.get("status") == "PASS"
        and network.get("storage_integrity", {}).get("status") == "PASS"
        and network.get("crosscheck_status") == "PASS"
        and len(receipts) >= 2
        and all(x.get("status") == "PASS" for x in receipts)
        and bool(re.fullmatch(r"[0-9a-f]{64}", canonical_hash))
    )
    results["B02"] = item(
        "PASS" if b02_ok else "FAIL",
        {
            "network_status": network.get("status"),
            "storage_integrity": network.get("storage_integrity", {}).get("status"),
            "crosscheck_status": network.get("crosscheck_status"),
            "source_receipt_count": len(receipts),
            "canonical_hash": canonical_hash,
        },
    )

    prediction_contract = checks.get("prediction_no_false_edge", {}).get("status") == "PASS"
    freeze_contract = checks.get("prediction_freeze_idempotent", {}).get("status") == "PASS"
    results["B03"] = item(
        "PASS" if prediction_contract and freeze_contract else "FAIL",
        {
            "prediction_full_ranking_contract": checks.get("prediction_no_false_edge", {}).get("status"),
            "freeze_idempotent": checks.get("prediction_freeze_idempotent", {}).get("status"),
        },
    )

    required_protocol = {
        "candidate_pool_independent_validation",
        "multi_window_perturbation",
        "multi_seed_perturbation",
        "reality_check_executed",
        "holm_correction_executed",
        "leave_one_period_out_executed",
        "leakage_challenge",
        "canonical_hash_bound",
    }
    oos = science.get("oos") if isinstance(science.get("oos"), dict) else {}
    ablations = science.get("ablations") if isinstance(science.get("ablations"), list) else []
    candidate_pool = science.get("candidate_pool") if isinstance(science.get("candidate_pool"), list) else []
    science_baseline = science.get("baseline") if isinstance(science.get("baseline"), dict) else {}
    b04_ok = (
        science.get("status") == "PASS"
        and science.get("software_verdict") == "PASS"
        and set(protocol) == required_protocol
        and all(value == "PASS" for value in protocol.values())
        and science.get("canonical_hash") == canonical_hash
        and len(candidate_pool) >= 7
        and len(ablations) >= 5
        and oos.get("bootstrap_95_lower") is not None
        and isinstance(oos.get("signflip_p"), (int, float))
        and 0.0 <= float(oos.get("signflip_p")) <= 1.0
        and science_baseline.get("baseline_model") == "uniform_random_without_replacement"
        and science_baseline.get("single_number_probability") == 0.25
        and science_baseline.get("pick10_expected_hits") == 2.5
    )
    results["B04"] = item(
        "PASS" if b04_ok else "FAIL",
        {
            "science_status": science.get("status"),
            "software_verdict": science.get("software_verdict"),
            "protocol_gates": protocol,
            "candidate_pool_count": len(candidate_pool),
            "ablation_count": len(ablations),
            "bootstrap_executed": oos.get("bootstrap_95_lower") is not None,
            "signflip_p": oos.get("signflip_p"),
            "baseline_model": science_baseline.get("baseline_model"),
        },
    )

    edge_state = science.get("edge_state")
    b05_ok = (
        (edge_state == "NO_EDGE"
         and science.get("dan_state") == "NULL_DAN"
         and not science.get("formal_dan")
         and science.get("production_model") == "uniform_baseline")
        or
        (edge_state == "VALIDATED_EDGE" and science.get("dan_state") == "VALIDATED_DAN")
    )
    results["B05"] = item(
        "PASS" if b05_ok else "FAIL",
        {
            "edge_state": edge_state,
            "dan_state": science.get("dan_state"),
            "production_model": science.get("production_model"),
            "formal_dan_count": len(science.get("formal_dan") or []),
        },
    )

    b06_ok = checks.get("advanced_analysis", {}).get("status") == "PASS" and b04_ok and b05_ok
    results["B06"] = item(
        "PASS" if b06_ok else "FAIL",
        {"advanced_analysis_contract": checks.get("advanced_analysis", {}).get("status"), "science_bound": b04_ok},
    )

    repair_checks = [
        "repair_clean_full_contract",
        "repair_corrupt_index_pointer",
        "repair_missing_required_pointer",
        "repair_external_config_blocked_not_pass",
        "repair_version_mismatch_fail_closed",
        "repair_missing_generation_file_fail_closed",
        "repair_unrecoverable_data_corruption_fail_closed",
    ]
    update_repair_contract_ok = (
        checks.get("software_update_handoff", {}).get("status") == "PASS"
        and checks.get("software_update_fail_closed", {}).get("status") == "PASS"
        and all(checks.get(name, {}).get("status") == "PASS" for name in repair_checks)
    )
    real_release_ok = release.get("status") == "PASS"
    if not update_repair_contract_ok:
        b07_status = "FAIL"
        b07_detail = "update/repair contract evidence failed"
    elif not real_release_ok:
        b07_status = "BLOCKED"
        b07_detail = "real independent production Release N→N+1 evidence is unavailable"
    else:
        b07_status = "PASS"
        b07_detail = "real release and repair contract both PASS"
    results["B07"] = item(
        b07_status,
        {
            "update_repair_contract": "PASS" if update_repair_contract_ok else "FAIL",
            "real_release_status": release.get("status", "MISSING"),
        },
        b07_detail,
    )

    ui_source_ok = ui.get("status") == "PASS" and ui.get("truth_boundary_match") is True
    if not windows or not physical:
        b08_status = "NOT VERIFIED"
        b08_detail = "exact Windows EXE / physical GUI evidence not supplied"
    else:
        expected_labels = {"预测下一期", "一键更新", "一键修复", "高级分析"}
        operation_labels = {
            str(x.get("label"))
            for x in (physical.get("operations") or [])
            if isinstance(x, dict)
        }
        physical_ok = (
            physical.get("status") == "PASS"
            and physical.get("same_hash") is True
            and expected_labels.issubset(operation_labels)
        )
        windows_ok = windows.get("status") == "PASS" and windows.get("same_hash") is True
        if ui_source_ok and physical_ok and windows_ok:
            b08_status = "PASS"
            b08_detail = "source UI, exact EXE and four physical entries are bound"
        else:
            b08_status = "FAIL"
            b08_detail = "UI/Exact-EXE/physical evidence mismatch"
    results["B08"] = item(
        b08_status,
        {
            "source_ui": ui.get("status"),
            "truth_boundary_match": ui.get("truth_boundary_match"),
            "windows": windows.get("status", "MISSING"),
            "physical_gui": physical.get("status", "MISSING"),
        },
        b08_detail,
    )

    weights = {x["id"]: float(x.get("weight") or 0) for x in baseline_items}
    denominator = sum(weights.values())
    passed_weight = sum(weights[k] for k, v in results.items() if v["status"] == "PASS")
    completion = 100.0 * passed_weight / denominator if denominator else 0.0
    all_pass = all(v["status"] == "PASS" for v in results.values())

    report = {
        "schema": "happy8-business-acceptance-v1",
        "status": "PASS" if all_pass else "FAIL",
        "completion_percent": round(completion, 4),
        "passed_weight": passed_weight,
        "required_weight": denominator,
        "items": results,
        "final_business_gate": "PASS" if all_pass else "FAIL",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
