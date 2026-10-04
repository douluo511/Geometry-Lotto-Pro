from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import math
import os
import re
import subprocess
import time

WINDOW_TITLE = "Stock AI Pro · Windows Desktop Candidate"
ALLOWED_STATES = {"PASS", "FAIL", "BLOCKED", "NOT VERIFIED"}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def mtime(path):
    return path.stat().st_mtime_ns if path.exists() else 0


def load(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise AssertionError("object evidence required: " + str(path))
    return obj


def wait_changed(path, before, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if mtime(path) > before:
            return load(path)
        time.sleep(0.25)
    raise TimeoutError("evidence file not updated: " + str(path))


def validate_identity(obj, expected):
    for key, value in expected.items():
        if obj.get(key) != value:
            raise AssertionError("current Exact EXE identity mismatch: " + key)


def validate_receipt(obj, action, expected, clicked_at):
    validate_identity(obj, expected)
    if obj.get("schema") != "stock-ai-service-invocation-v1" or obj.get("action") != action:
        raise AssertionError("service invocation schema/action mismatch")
    if not re.fullmatch(r"[0-9a-f]{32}", str(obj.get("invocation_id", ""))):
        raise AssertionError("service invocation identity missing")
    if obj.get("status") not in ALLOWED_STATES:
        raise AssertionError("unsupported service acceptance state")
    if not (clicked_at - 1 <= obj.get("started_at", 0) <= obj.get("finished_at", 0)):
        raise AssertionError("stale service invocation predates physical click")


def validate_core(last):
    if last.get("status") != "PASS":
        raise AssertionError("GUI core did not produce explicit PASS: " + repr(last))
    if not last.get("prediction_dir") or not last.get("asof"):
        raise AssertionError("GUI core prediction identity missing")


def validate_worker(obj, action, expected, invocation_id):
    validate_identity(obj, {key: expected[key] for key in
                           ("executable", "exe_sha256", "frozen", "source_commit")})
    if (obj.get("action") != action or obj.get("invocation_id") != invocation_id or
            obj.get("status") != "PASS" or obj.get("returncode") != 0):
        raise AssertionError("frozen worker result is not bound to this physical click")


def validate_advanced(audit, backtest):
    checks = audit.get("checks")
    if not isinstance(checks, list) or not checks:
        raise AssertionError("advanced audit has no executed checks")
    ids = [check.get("id") for check in checks if isinstance(check, dict)]
    if len(ids) != len(checks) or any(not item for item in ids) or len(set(ids)) != len(ids):
        raise AssertionError("advanced audit check identities are invalid")
    required = {"FUTURE_SAFE_FEATURES", "EXECUTION_LAG", "EMBARGO_SPLIT", "LABEL_SHUFFLE",
                "TIME_SHIFT", "IMMUTABLE", "PREDICTION_HASH_CHAIN", "DYNAMIC_COST",
                "VALUE_BASELINE", "RANDOM_BASELINE"}
    if not required.issubset(set(ids)):
        raise AssertionError("advanced audit denominator lost required checks")
    known = ALLOWED_STATES | {"WARN", "WARNING", "PENDING", "SKIPPED", "UNKNOWN"}
    if any(check.get("status") not in known for check in checks):
        raise AssertionError("advanced audit has missing/unknown states")
    if audit.get("trust") not in {"LOW", "MEDIUM", "HIGH"} or not audit.get("generated_at"):
        raise AssertionError("advanced audit trust/time result missing")
    if not isinstance(audit.get("five_why"), list) or not isinstance(audit.get("reverse_validation"), list) or not audit["reverse_validation"]:
        raise AssertionError("advanced 5 Why/reverse-validation evidence missing")
    if type(backtest.get("eval_points")) is not int or backtest["eval_points"] <= 0:
        raise AssertionError("backtest has no actual evaluation points")
    if backtest.get("dynamic_cost_model") is not True or backtest.get("production_model_parity") is not True:
        raise AssertionError("backtest omitted cost or production-model parity")
    if set(backtest.get("model_stack", [])) != {"ridge", "hgb", "extra_trees"}:
        raise AssertionError("backtest production model stack mismatch")
    for key in ("mean_strategy_return", "mean_random_return", "mean_market_return", "mean_momentum_return", "max_drawdown"):
        value = backtest.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise AssertionError("backtest result missing/non-finite: " + key)
    if not backtest.get("capacity_mean_net_returns") or not backtest.get("generated_at"):
        raise AssertionError("backtest capacity/time evidence missing")
    non_pass = [{"id": c["id"], "raw_status": c["status"]} for c in checks if c["status"] != "PASS"]
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else ("NOT VERIFIED" if non_pass else "PASS")
    return {"status": status, "eval_points": backtest["eval_points"], "audit_trust": audit["trust"], "non_pass_checks": non_pass}


def physical_click(win, label, data, expected, launched_at):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            layout = load(data / "evidence" / "ui_layout.json")
            if layout.get("recorded_at", 0) < launched_at:
                time.sleep(0.25)
                continue
            validate_identity(layout, expected)
            point = layout["buttons"][label]
            if (layout.get("schema") == "stock-ai-live-tk-layout-v1" and layout.get("window_title") == WINDOW_TITLE
                    and layout.get("recorded_at", 0) >= launched_at and layout.get("busy") is False and point["state"] == "normal"):
                break
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.25)
    else:
        raise TimeoutError("live enabled Tk geometry unavailable: " + label)
    wrapper = win.wrapper_object()
    if wrapper.element_info.process_id != expected["pid"]:
        raise AssertionError("layout belongs to a different window process")
    wrapper.set_focus()
    rect = wrapper.rectangle()
    x, y = int(point["x"]), int(point["y"])
    if not (rect.left < x < rect.right and rect.top < y < rect.bottom):
        raise AssertionError("button point is outside current Exact EXE window")
    clicked_at = time.time()
    # Real foreground mouse input only; geometry is a locator, never a callback.
    wrapper.click_input(button="left", coords=(x - rect.left, y - rect.top))
    return {"method": "click_input", "label": label, "x": x, "y": y, "clicked_at": clicked_at, "window_pid": expected["pid"]}


def close_blocked_dialog(pid, timeout=120):
    from pywinauto import Desktop
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for backend in ("win32", "uia"):
            for dialog in Desktop(backend=backend).windows():
                if dialog.window_text() != "Stock AI Pro" or dialog.element_info.process_id != pid:
                    continue
                descendants = dialog.descendants()
                text = " ".join([*dialog.texts(), *[child.window_text() for child in descendants]])
                if "update -> BLOCKED" not in text or "rc=3" not in text:
                    raise AssertionError("update warning did not prove BLOCKED: " + text)
                buttons = [child for child in descendants if child.friendly_class_name() == "Button"]
                if len(buttons) != 1:
                    raise AssertionError("expected one physical dialog dismissal button")
                buttons[0].click_input()
                return text
        time.sleep(0.25)
    raise TimeoutError("real BLOCKED updater warning did not appear")


def contract_test():
    # Counterexamples are source contracts; they never claim physical GUI PASS.
    import copy
    import sys
    import tempfile
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_native"))
    from service import StockAIService
    package = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro"
    checks = []
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"STOCK_AI_DATA_ROOT": directory}):
        service = StockAIService(package)
        blocked = subprocess.CompletedProcess(["updater"], 3, '{"status":"BLOCKED","reason":"production updater is disabled"}', "")
        with patch("service.subprocess.run", return_value=blocked):
            result = service.update()
        receipt = load(Path(directory) / "evidence" / "service_update.json")
        assert result.status == "BLOCKED" and result.returncode == 3
        assert receipt["status"] == "BLOCKED" and receipt["invocation_id"] == result.invocation_id
        assert receipt["argv"] and receipt["pid"] == os.getpid()
        checks.append("updater-BLOCKED-receipt")
        for output in ("", '{"status":"PASS"}', '{"status":"BLOCKED"}'):
            with patch("service.subprocess.run", return_value=subprocess.CompletedProcess([], 3, output, "")):
                assert service.update().status == "FAIL"
        checks.append("unsubstantiated-rc3-rejected")
        with patch("service.subprocess.run", side_effect=subprocess.TimeoutExpired("updater", 1)):
            assert service.update().status == "FAIL"
        assert load(Path(directory) / "evidence" / "service_update.json")["returncode"] == 124
        checks.append("timeout-failure-persisted")
    try:
        validate_core({"status": "NOT VERIFIED", "prediction_dir": "present", "asof": "2026-09-30"})
    except AssertionError:
        checks.append("non-PASS-core-rejected")
    else:
        raise AssertionError("non-PASS core admitted")
    audit = {"generated_at": "current", "trust": "HIGH", "five_why": [], "reverse_validation": ["actual"],
             "checks": [{"id": item, "status": "PASS"} for item in
                        ("FUTURE_SAFE_FEATURES", "EXECUTION_LAG", "EMBARGO_SPLIT", "LABEL_SHUFFLE", "TIME_SHIFT",
                         "IMMUTABLE", "PREDICTION_HASH_CHAIN", "DYNAMIC_COST", "VALUE_BASELINE", "RANDOM_BASELINE")]}
    backtest = {"generated_at": "current", "eval_points": 2, "dynamic_cost_model": True, "production_model_parity": True,
                "model_stack": ["ridge", "hgb", "extra_trees"], "mean_strategy_return": 0.01, "mean_random_return": 0.0,
                "mean_market_return": 0.0, "mean_momentum_return": 0.0, "max_drawdown": -0.01, "capacity_mean_net_returns": {"100000": 0.01}}
    assert validate_advanced(audit, backtest)["status"] == "PASS"
    warning = copy.deepcopy(audit)
    warning["checks"][0]["status"] = "WARN"
    assert validate_advanced(warning, backtest)["status"] == "NOT VERIFIED"
    warning["checks"][0]["status"] = "FAIL"
    assert validate_advanced(warning, backtest)["status"] == "FAIL"
    checks.append("advanced-non-PASS-not-promoted")
    for invalid in ({}, {**backtest, "eval_points": 0}, {**backtest, "mean_strategy_return": float("nan")}):
        try:
            validate_advanced(audit, invalid)
        except AssertionError:
            pass
        else:
            raise AssertionError("incomplete/non-finite advanced report admitted")
    checks.append("file-only-advanced-rejected")
    identity = {"pid": 123, "exe_sha256": "current"}
    receipt = {"schema": "stock-ai-service-invocation-v1", "action": "update", "status": "BLOCKED",
               "invocation_id": "a" * 32, "started_at": 100, "finished_at": 101, **identity}
    validate_receipt(receipt, "update", identity, 100)
    for invalid in ({**receipt, "pid": 124}, {**receipt, "started_at": 1}, {**receipt, "invocation_id": ""}):
        try:
            validate_receipt(invalid, "update", identity, 100)
        except AssertionError:
            pass
        else:
            raise AssertionError("stale/other-process invocation admitted")
    checks.append("click-process-freshness-binding")
    worker_identity = {"executable": "exact.exe", "exe_sha256": "current", "frozen": True, "source_commit": "head"}
    worker = {**worker_identity, "action": "core", "invocation_id": "a" * 32, "status": "PASS", "returncode": 0}
    validate_worker(worker, "core", worker_identity, "a" * 32)
    for invalid in ({**worker, "invocation_id": "b" * 32}, {**worker, "exe_sha256": "stale"}, {**worker, "status": "FAIL"}):
        try:
            validate_worker(invalid, "core", worker_identity, "a" * 32)
        except AssertionError:
            pass
        else:
            raise AssertionError("stale/other-invocation worker admitted")
    checks.append("frozen-worker-click-identity")
    print(json.dumps({"status": "PASS", "source_contract_checks": checks, "physical_gui": "NOT VERIFIED", "final_gate": "FAIL"}))
    return 0


def main():
    parser = ArgumentParser()
    parser.add_argument("--exe")
    parser.add_argument("--data-root")
    parser.add_argument("--evidence", default="desktop_gui_click_evidence.json")
    parser.add_argument("--contract-test", action="store_true")
    args = parser.parse_args()
    if args.contract_test:
        return contract_test()
    if not args.exe or not args.data_root:
        parser.error("--exe and --data-root required for physical acceptance")
    output = Path(args.evidence).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    exe, data = Path(args.exe).resolve(), Path(args.data_root).resolve()
    data.mkdir(parents=True, exist_ok=True)
    result = {"schema": "stock-ai-physical-gui-v2", "status": "FAIL", "exe": str(exe), "actions": {},
              "physical_gui_positive_actions": "NOT VERIFIED", "physical_gui_update_positive": "BLOCKED", "final_gate": "FAIL"}
    process, win = None, None
    try:
        from pywinauto import Desktop
        source = os.environ.get("STOCK_SOURCE_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", source):
            raise AssertionError("exact source commit binding missing")
        before_hash = sha256(exe)
        result["exe_sha256_before"] = before_hash
        env = os.environ.copy()
        env["STOCK_AI_DATA_ROOT"] = str(data)
        launched_at = time.time()
        process = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
        desktop = Desktop(backend="win32")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Exact EXE exited before GUI: " + str(process.returncode))
            matches = [w for w in desktop.windows() if w.window_text() == WINDOW_TITLE]
            if matches:
                win = desktop.window(handle=matches[0].handle)
                break
            time.sleep(0.25)
        if win is None:
            raise TimeoutError("Exact EXE window not found")
        win.wait("visible enabled", timeout=15)
        expected = {"pid": win.wrapper_object().element_info.process_id, "executable": str(exe), "exe_sha256": before_hash,
                    "frozen": True, "source_commit": source, "github_run_id": env.get("GITHUB_RUN_ID"),
                    "github_run_attempt": env.get("GITHUB_RUN_ATTEMPT")}
        result["identity"] = expected

        def invoke(label, action, timeout):
            path = data / "evidence" / ("service_" + action + ".json")
            before = mtime(path)
            worker_action = {"core_function": "core", "repair": "repair", "advanced_analysis": "advanced"}.get(action)
            worker_path = data / "evidence" / ("worker_" + str(worker_action) + ".json")
            worker_before = mtime(worker_path)
            click = physical_click(win, label, data, expected, launched_at)
            receipt = wait_changed(path, before, timeout)
            validate_receipt(receipt, action, expected, click["clicked_at"])
            if worker_action:
                worker = wait_changed(worker_path, worker_before, 30)
                validate_worker(worker, worker_action, expected, receipt["invocation_id"])
                receipt["worker_receipt"] = str(worker_path)
            return click, receipt, path

        core_file = data / "state" / "last_run.json"
        before = mtime(core_file)
        click, receipt, receipt_path = invoke("核心功能", "core_function", 3360)
        if receipt["status"] != "PASS" or receipt["returncode"] != 0:
            raise AssertionError("core invocation did not PASS: " + repr(receipt))
        last = wait_changed(core_file, before, 30)
        validate_core(last)
        result["actions"]["core"] = {"status": "PASS", "click": click, "receipt": str(receipt_path),
            "invocation_id": receipt["invocation_id"], "last_run": last, "evidence": str(core_file)}

        click, receipt, receipt_path = invoke("一键更新", "update", 180)
        if receipt["status"] != "BLOCKED" or receipt["returncode"] != 3:
            raise AssertionError("missing-release update did not produce actual BLOCKED: " + repr(receipt))
        if not receipt["argv"] or Path(receipt["argv"][0]).name != "StockAIUpdater.exe":
            raise AssertionError("update did not invoke independent Updater EXE")
        dialog = close_blocked_dialog(expected["pid"])
        result["actions"]["update"] = {"status": "BLOCKED", "negative_acceptance": "PASS", "click": click,
            "receipt": str(receipt_path), "invocation_id": receipt["invocation_id"], "dialog": dialog}
        result["physical_gui_update_negative"] = "PASS"

        repair_file = data / "evidence" / "last_repair.json"
        before = mtime(repair_file)
        click, receipt, receipt_path = invoke("一键修复", "repair", 420)
        repaired = wait_changed(repair_file, before, 30)
        if receipt["status"] != "PASS" or receipt["returncode"] != 0 or repaired.get("status") != "PASS" or repaired.get("doctor_returncode") != 0:
            raise AssertionError("repair did not produce real doctor PASS")
        result["actions"]["repair"] = {"status": "PASS", "click": click, "receipt": str(receipt_path),
            "invocation_id": receipt["invocation_id"], "doctor": repaired}

        audit_file, backtest_file = data / "reports" / "audit_report.json", data / "reports" / "backtest_summary.json"
        audit_before, backtest_before = mtime(audit_file), mtime(backtest_file)
        click, receipt, receipt_path = invoke("高级分析", "advanced_analysis", 3360)
        if receipt["status"] != "PASS" or receipt["returncode"] != 0:
            raise AssertionError("advanced invocation did not PASS: " + repr(receipt))
        audit = wait_changed(audit_file, audit_before, 30)
        backtest = wait_changed(backtest_file, backtest_before, 30)
        qualification = validate_advanced(audit, backtest)
        result["actions"]["advanced_analysis"] = {**qualification, "execution_status": "PASS", "click": click,
            "receipt": str(receipt_path), "invocation_id": receipt["invocation_id"], "audit_evidence": str(audit_file),
            "audit_sha256": sha256(audit_file), "backtest_evidence": str(backtest_file), "backtest_sha256": sha256(backtest_file)}
        result["physical_gui_entry_invocations"] = "PASS"
        result["physical_gui_positive_actions"] = qualification["status"]
        result["status"] = qualification["status"] if qualification["status"] != "PASS" else "BLOCKED"
    except Exception as exc:
        result["status"], result["error"] = "FAIL", repr(exc)
    finally:
        try:
            result["exe_sha256_after"] = sha256(exe)
            result["same_hash_after_physical_gui"] = "PASS" if result.get("exe_sha256_before") == result["exe_sha256_after"] else "FAIL"
            if result["same_hash_after_physical_gui"] != "PASS":
                result["status"] = "FAIL"
        except Exception as exc:
            result["same_hash_after_physical_gui"], result["hash_error"] = "NOT VERIFIED", repr(exc)
        try:
            if win is None:
                raise RuntimeError("Exact EXE window unavailable")
            screenshot = output.with_suffix(".png")
            win.capture_as_image().save(str(screenshot))
            result["screenshot_capture"], result["screenshot"] = "PASS", str(screenshot)
        except Exception as exc:
            result["screenshot_capture"] = "NOT VERIFIED" if win is None else "FAIL"
            result["screenshot_error"] = repr(exc)
        output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        try:
            if win is not None:
                win.close()
        except Exception:
            pass
        try:
            if process is not None and process.poll() is None:
                process.kill()
        except Exception:
            pass
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
