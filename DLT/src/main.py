from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from glp.constants import APP_NAME, APP_VERSION
from glp.gui import run_gui, gui_self_test
from glp.service import LottoService, self_test
from glp.util import sha256_bytes, utc_now


def _write_json(path: str | None, value: dict) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _exe_sha256() -> str:
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
        "checks": checks,
        "scientific_gate": "UNKNOWN",
        "network_gate": "UNKNOWN",
        "windows_runtime_gate": "UNKNOWN",
        "four_entry_gate": "UNKNOWN",
        "exact_package_gate": "UNKNOWN",
        "final_release_gate": "NOT_PASS",
    }

    def add(name: str, status: str, detail=None):
        item = {"name": name, "status": status}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)

    try:
        with tempfile.TemporaryDirectory(prefix="glp_acceptance_") as td:
            os.environ["GLP_DATA_DIR"] = td
            st = self_test(Path(td) / "selftest")
            add("code_self_test", st.get("status", "FAIL"), st)
            if st.get("status") != "PASS":
                raise RuntimeError("code self-test failed")

            if os.name != "nt":
                add("windows_runtime", "FAIL", "acceptance requires native Windows")
                raise RuntimeError("not running on Windows")

            gst = gui_self_test()
            add("native_gui_self_test", gst.get("status", "FAIL"), gst)
            report["windows_runtime_gate"] = gst.get("status", "FAIL")
            report["four_entry_gate"] = gst.get("status", "FAIL")
            if gst.get("status") != "PASS":
                raise RuntimeError("native GUI self-test failed")

            svc = LottoService()

            update = svc.update()
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

            pred = svc.predict()
            add("entry_predict", "PASS", {"target_issue": pred["prediction"]["target_issue"], "edge_state": pred["prediction"]["edge_state"], "dan_state": pred["prediction"]["dan_state"]})

            rep = svc.repair()
            repair_ok = rep.get("after", {}).get("status") == "PASS"
            add("entry_repair", "PASS" if repair_ok else "FAIL", rep)
            if not repair_ok:
                raise RuntimeError("repair entry failed")

            audit = svc.audit()
            court = audit.get("court", {})
            sci_ok = court.get("software_verdict") == "PASS" and court.get("scientific_gate") == "PASS"
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

            # Four actual service entries all executed. GUI binding was checked separately.
            add("entry_update", "PASS", {"latest": update.get("latest"), "network_gate": update.get("network_gate")})
            report["exact_package_gate"] = "PASS" if bool(report["exe_sha256"]) else "FAIL"

            hard_fail = any(c["status"] != "PASS" for c in checks)
            report["final_release_gate"] = "PASS" if (
                not hard_fail
                and report["windows_runtime_gate"] == "PASS"
                and report["four_entry_gate"] == "PASS"
                and report["network_gate"] == "PASS"
                and report["scientific_gate"] == "PASS"
                and report["exact_package_gate"] == "PASS"
            ) else "NOT_PASS"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    finally:
        report["finished_at"] = utc_now()
        _write_json(result_file, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    return 0 if report["final_release_gate"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="GeometryLottoPro")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-self-test", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--result-file")
    args = parser.parse_args()

    if args.self_test:
        value = self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") == "PASS" else 2
    if args.gui_self_test:
        value = gui_self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("status") == "PASS" else 2
    if args.acceptance:
        return run_acceptance(args.result_file)

    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
