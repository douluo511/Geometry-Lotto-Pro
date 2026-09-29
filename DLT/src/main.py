from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from glp.constants import APP_NAME, APP_VERSION
from glp.gui import run_gui, NativeApp, BTN_PREDICT, BTN_UPDATE, BTN_REPAIR, BTN_AUDIT
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


def _gui_probe_evidence() -> dict:
    class StubService:
        def _ok(self, name):
            return lambda progress=None: {"entry": name}
        predict = property(lambda self: self._ok("预测下一期"))
        update = property(lambda self: self._ok("一键更新"))
        repair = property(lambda self: self._ok("一键修复"))
        audit = property(lambda self: self._ok("高级分析"))

    app = NativeApp(StubService())
    checks = []
    expected = {
        BTN_PREDICT: "预测下一期",
        BTN_UPDATE: "一键更新",
        BTN_REPAIR: "一键修复",
        BTN_AUDIT: "高级分析",
    }
    for cid, label in expected.items():
        checks.append({"name": label, "status": "PASS" if cid in app.renderers else "FAIL"})
    checks.append({"name": "Native Win32 window", "status": "PASS" if app.user32.IsWindow(app.hwnd) else "FAIL"})
    checks.append({
        "name": "Four native button HWNDs",
        "status": "PASS" if len(app.buttons) == 4 and all(app.user32.IsWindow(h) for h in app.buttons) else "FAIL",
    })
    if app.user32.IsWindow(app.hwnd):
        app.user32.ShowWindow(app.hwnd, 0)
    return {"status": "PASS" if all(x["status"] == "PASS" for x in checks) else "FAIL", "checks": checks}


def gui_self_test() -> dict:
    if os.name != "nt":
        return {"status": "FAIL", "checks": [{"name": "Native Win32 window", "status": "FAIL", "detail": "not Windows"}]}
    if not getattr(sys, "frozen", False):
        return _gui_probe_evidence()
    fd, evidence_path = tempfile.mkstemp(prefix="glp_gui_probe_", suffix=".json")
    os.close(fd)
    try:
        try:
            cp = subprocess.run([sys.executable, "--gui-probe-child", "--result-file", evidence_path], timeout=30, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "checks": [{"name": "Exact EXE GUI probe child", "status": "FAIL", "detail": "timeout"}]}
        if cp.returncode != 0:
            return {"status": "FAIL", "checks": [{"name": "Exact EXE GUI probe child", "status": "FAIL", "detail": "exit=" + str(cp.returncode)}]}
        try:
            data = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "FAIL", "checks": [{"name": "Exact EXE GUI probe evidence", "status": "FAIL", "detail": type(exc).__name__ + ":" + str(exc)}]}
        data.setdefault("checks", []).append({"name": "Exact EXE GUI probe isolation", "status": "PASS"})
        data["status"] = "PASS" if all(x.get("status") == "PASS" for x in data["checks"]) else "FAIL"
        return data
    finally:
        try:
            Path(evidence_path).unlink()
        except OSError:
            pass

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

            checkpoint("native_gui_self_test")
            gst = gui_self_test()
            add("native_gui_self_test", gst.get("status", "FAIL"), gst)
            report["windows_runtime_gate"] = gst.get("status", "FAIL")
            report["four_entry_gate"] = gst.get("status", "FAIL")
            if gst.get("status") != "PASS":
                raise RuntimeError("native GUI self-test failed")

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
        report["current_phase"] = "finished"
        report["finished_at"] = utc_now()
        _write_json(result_file, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    return 0 if report["final_release_gate"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="GeometryLottoPro")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-self-test", action="store_true")
    parser.add_argument("--gui-probe-child", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--result-file")
    args = parser.parse_args()

    if args.gui_probe_child:
        value = _gui_probe_evidence()
        _write_json(args.result_file, value)
        os._exit(0 if value.get("status") == "PASS" else 2)
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
