from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from glp.constants import APP_NAME, APP_VERSION
from glp.gui import gui_self_test, run_gui
from glp.service import LottoService, self_test
from glp.util import sha256_bytes, utc_now


def _write_json(path: str | None, value: dict) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _exe_sha256() -> str:
    if not getattr(sys, "frozen", False):
        return ""
    try:
        return sha256_bytes(Path(sys.executable).read_bytes())
    except Exception:
        return ""


def run_acceptance(result_file: str | None = None) -> int:
    checks: list[dict] = []
    report = {
        "schema": 1,
        "app": APP_NAME,
        "version": APP_VERSION,
        "started_at": utc_now(),
        "exe_sha256": _exe_sha256(),
        "platform": sys.platform,
        "python": sys.version,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "checks": checks,
        "scientific_gate": "UNKNOWN",
        "network_gate": "UNKNOWN",
        "windows_runtime_gate": "UNKNOWN",
        "four_entry_gate": "UNKNOWN",
        "exact_package_gate": "UNKNOWN",
        "final_release_gate": "NOT_PASS",
        "exact_acceptance_gate": "FAIL",
        "validation_scope": "EXACT_EXE_SERVICE_CHECKS_ONLY",
    }
    previous_data_dir = os.environ.get("GLP_DATA_DIR")

    def checkpoint(phase: str, detail=None) -> None:
        report["current_phase"] = phase
        report["last_progress_at"] = utc_now()
        if detail is not None:
            report["progress_detail"] = detail
        _write_json(result_file, report)

    def add(name: str, status: str, detail=None):
        item = {"name": name, "status": status}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)
        checkpoint(name, detail)

    try:
        if not result_file or not report["exe_sha256"]:
            raise RuntimeError("persisted result file and frozen EXE are required")
        with tempfile.TemporaryDirectory(prefix="glp_acceptance_") as td:
            os.environ["GLP_DATA_DIR"] = td
            checkpoint("code_self_test")
            st = self_test(Path(td) / "selftest")
            add("code_self_test", st.get("status", "FAIL"), st)
            if st.get("status") != "PASS":
                raise RuntimeError("code self-test failed")

            if os.name != "nt":
                add("windows_runtime", "FAIL", "acceptance requires native Windows")
                raise RuntimeError("not running on Windows")
            add("windows_runtime", "PASS", {"os_name": os.name, "platform": sys.platform})
            report["windows_runtime_gate"] = "PASS"

            # Native GUI creation/clicking is intentionally a separate, stronger
            # post-package hard gate in the workflow. Exact-package acceptance
            # verifies the same EXE's service contract, network, science and hash.
            svc = LottoService()

            checkpoint("real_network_dual_source")
            update = svc.update(lambda msg: checkpoint("real_network_dual_source", msg))
            network_ok = update.get("network_gate") == "PASS" and update.get("crosscheck_status") == "PASS"
            add("real_network_dual_source", "PASS" if network_ok else "FAIL", {
                "latest": update.get("latest"),
                "crosscheck_count": update.get("crosscheck_count"),
                "crosscheck_status": update.get("crosscheck_status"),
                "source_receipts": update.get("source_receipts"),
                "canonical_hash": update.get("canonical_hash"),
            })
            report["network_gate"] = "PASS" if network_ok else "FAIL"
            if not network_ok:
                raise RuntimeError("real network dual-source check failed")
            from glp.acceptance_evidence import preserve_live_evidence
            report["preserved_live_evidence"] = preserve_live_evidence(
                svc.store, result_file, report["exe_sha256"]
            )

            checkpoint("entry_predict")
            pred = svc.predict(lambda msg: checkpoint("entry_predict", msg))
            add("entry_predict", "PASS", {"target_issue": pred["prediction"]["target_issue"], "edge_state": pred["prediction"]["edge_state"], "dan_state": pred["prediction"]["dan_state"]})

            checkpoint("entry_repair")
            rep = svc.repair(lambda msg: checkpoint("entry_repair", msg))
            repair_ok = rep.get("after", {}).get("status") == "PASS"
            add("entry_repair", "PASS" if repair_ok else "FAIL", rep)
            if not repair_ok:
                raise RuntimeError("repair entry failed")

            checkpoint("entry_audit_scientific")
            audit = svc.audit(lambda msg: checkpoint("entry_audit_scientific", msg))
            court = audit.get("court", {})
            sci_ok = court.get("software_verdict") == "PASS" and court.get("scientific_gate") == "PASS"
            sci_ok = sci_ok and audit.get("formal_freeze_written") is False and audit.get("freeze_before") == audit.get("freeze_after")
            add("entry_audit_scientific", "PASS" if sci_ok else "FAIL", {
                "software_verdict": court.get("software_verdict"),
                "scientific_gate": court.get("scientific_gate"),
                "edge_state": court.get("edge_state"),
                "dan_state": court.get("dan_state"),
                "court_hash": court.get("court_hash"),
            })
            report["scientific_gate"] = "PASS" if sci_ok else "FAIL"
            if not sci_ok:
                raise RuntimeError("scientific protocol failed")

            # Four actual service entries all executed. Native button creation and
            # physical clicks are verified later against these exact EXE bytes.
            add("entry_update", "PASS", {"latest": update.get("latest"), "network_gate": update.get("network_gate")})
            add("four_entry_service_contract", "PASS", {
                "entries": ["预测下一期", "一键更新", "一键修复", "高级分析"]
            })
            report["four_entry_gate"] = "PASS"
            report["exact_package_gate"] = "PASS" if bool(report["exe_sha256"]) else "FAIL"

            hard_fail = any(c["status"] != "PASS" for c in checks)
            report["exact_acceptance_gate"] = "PASS" if (
                not hard_fail
                and report["windows_runtime_gate"] == "PASS"
                and report["four_entry_gate"] == "PASS"
                and report["network_gate"] == "PASS"
                and report["scientific_gate"] == "PASS"
                and report["exact_package_gate"] == "PASS"
            ) else "NOT_PASS"
            # The executable cannot certify its own full release. GUI effects,
            # updater, no-shell, business and independent repo gates run outside it.
            report["final_release_gate"] = "PENDING"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    finally:
        if previous_data_dir is None:
            os.environ.pop("GLP_DATA_DIR", None)
        else:
            os.environ["GLP_DATA_DIR"] = previous_data_dir
        report["current_phase"] = "finished"
        report["finished_at"] = utc_now()
        _write_json(result_file, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    return 0 if report["exact_acceptance_gate"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="GeometryLottoPro")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--gui-self-test", action="store_true")
    parser.add_argument("--result-file")
    args = parser.parse_args()

    if args.self_test:
        value = self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") == "PASS" else 2
    if args.acceptance:
        return run_acceptance(args.result_file)
    if args.gui_self_test:
        value = gui_self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") == "PASS" else 2

    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
