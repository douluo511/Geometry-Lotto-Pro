from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from pywinauto import Desktop, mouse


BUTTON_ORDER = {
    "update": "一键更新",
    "predict": "预测下一期",
    "repair": "一键修复",
    "advanced": "高级分析",
}


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_sha256(path: Path) -> str:
    return file_sha256(path)


def wait_json(path: Path, *, timeout: float, predicate) -> dict:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                if predicate(value):
                    return value
                last_error = f"predicate not satisfied: {value!r}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    raise RuntimeError(f"timed out waiting for {path}; last={last_error}")


def find_window(timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            candidates = Desktop(backend="uia").windows(
                title_re=".*Geometry Lotto Pro.*快乐8.*",
                visible_only=True,
            )
            if candidates:
                window = candidates[0]
                window.set_focus()
                return window
        except Exception as exc:
            last = exc
        time.sleep(0.75)
    raise RuntimeError(f"Happy8 window not found; last={last!r}")


def click_named(window, label: str, fallback_index: int) -> dict:
    method = None
    try:
        control = window.child_window(title=label, control_type="Button")
        control.wait("visible enabled ready", timeout=15)
        control.click_input()
        method = "uia_click_input"
    except Exception:
        rect = window.rectangle()
        width = rect.width()
        # Four equal-width action columns below the header.
        x = rect.left + int(width * ((fallback_index + 0.5) / 4.0))
        y = rect.top + 122
        mouse.click(button="left", coords=(x, y))
        method = "physical_coordinate_fallback"
    return {"label": label, "method": method}


def wait_buttons_ready(window, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            states = []
            for label in BUTTON_ORDER.values():
                control = window.child_window(title=label, control_type="Button")
                states.append(bool(control.is_enabled()))
            if states and all(states):
                return
        except Exception:
            # Coordinate fallback cannot reliably inspect ttk button state; a
            # short UI pump delay after evidence is the fail-safe path.
            time.sleep(1.5)
            return
        time.sleep(0.5)
    raise RuntimeError("GUI buttons did not re-enable after operation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-evidence", type=Path, required=True)
    args = parser.parse_args()

    exe = args.exe.resolve()
    root = args.data_root.resolve()
    evidence = root / "evidence"
    results = root / "results"
    root.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    build_evidence = json.loads(args.build_evidence.read_text(encoding="utf-8-sig"))
    expected_hash = str(build_evidence.get("exe_sha256") or "").lower()
    if len(expected_hash) != 64:
        raise RuntimeError("build evidence does not contain a valid Exact EXE SHA-256")
    before_hash = file_sha256(exe)
    if before_hash != expected_hash:
        raise RuntimeError(
            f"physical GUI target is not the Exact EXE: expected={expected_hash} actual={before_hash}"
        )
    started = time.time()
    process = subprocess.Popen([str(exe), "--data-root", str(root)])
    clicks = []
    operation_evidence = {}
    window = None
    error = None
    try:
        window = find_window()
        title = window.window_text()

        # One-Click Update must exercise the real UI and official network data
        # refresh. With no production software release context it must remain
        # explicitly BLOCKED rather than masquerading as a software update PASS.
        clicks.append(click_named(window, BUTTON_ORDER["update"], 1))
        update_path = evidence / "last_one_click_update.json"
        update = wait_json(
            update_path,
            timeout=900,
            predicate=lambda x: (
                x.get("status") == "BLOCKED"
                and x.get("data_update", {}).get("status") == "PASS"
                and x.get("software_update", {}).get("status") == "BLOCKED"
            ),
        )
        operation_evidence["update"] = {
            "status": "PASS_NEGATIVE_PRODUCTION_BOUNDARY",
            "path": str(update_path),
            "sha256": json_sha256(update_path),
            "reported": update,
        }
        wait_buttons_ready(window)

        clicks.append(click_named(window, BUTTON_ORDER["predict"], 0))
        prediction_path = evidence / "last_prediction.json"
        prediction = wait_json(
            prediction_path,
            timeout=900,
            predicate=lambda x: (
                x.get("status") == "PASS"
                and x.get("edge_state") in {"NO_EDGE", "VALIDATED_EDGE"}
                and bool(x.get("freeze_hash"))
            ),
        )
        operation_evidence["predict"] = {
            "status": "PASS",
            "path": str(prediction_path),
            "sha256": json_sha256(prediction_path),
            "target_issue": prediction.get("target_issue"),
            "edge_state": prediction.get("edge_state"),
            "dan_state": prediction.get("dan_state"),
        }
        wait_buttons_ready(window)

        clicks.append(click_named(window, BUTTON_ORDER["repair"], 2))
        repair_path = evidence / "last_repair.json"
        repair = wait_json(
            repair_path,
            timeout=120,
            predicate=lambda x: x.get("status") == "PASS",
        )
        operation_evidence["repair"] = {
            "status": "PASS",
            "path": str(repair_path),
            "sha256": json_sha256(repair_path),
            "action": repair.get("action"),
        }
        wait_buttons_ready(window)

        clicks.append(click_named(window, BUTTON_ORDER["advanced"], 3))
        advanced_path = evidence / "last_advanced_analysis.json"
        advanced = wait_json(
            advanced_path,
            timeout=1200,
            predicate=lambda x: (
                x.get("status") == "PASS"
                and x.get("report", {}).get("software_verdict") == "PASS"
            ),
        )
        operation_evidence["advanced"] = {
            "status": "PASS",
            "path": str(advanced_path),
            "sha256": json_sha256(advanced_path),
            "edge_state": advanced.get("report", {}).get("edge_state"),
            "method_gates": {
                name: advanced.get("report", {}).get("gates", {}).get(name)
                for name in (
                    "candidate_pool_independent_validation",
                    "multi_window_multi_seed",
                    "reality_check_max_model_null",
                    "holm_multiple_testing",
                    "leave_one_period_out",
                    "leakage_future_mutation",
                    "false_gain_elimination",
                )
            },
        }
        wait_buttons_ready(window)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if window is not None:
                window.close()
        except Exception:
            pass
        try:
            process.wait(timeout=20)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()

    after_hash = file_sha256(exe)
    method_pass = (
        error is None
        and len(clicks) == 4
        and before_hash == expected_hash
        and after_hash == expected_hash
        and all(
            operation_evidence.get(name, {}).get("status", "").startswith("PASS")
            for name in ("update", "predict", "repair", "advanced")
        )
    )
    report = {
        "schema": "happy8-physical-gui-gate-v1",
        "status": "PASS" if method_pass else "FAIL",
        "exe": str(exe),
        "build_exact_exe_sha256": expected_hash,
        "exe_sha256_before": before_hash,
        "exe_sha256_after": after_hash,
        "same_hash_after_physical_gui": before_hash == after_hash,
        "window_title": title if "title" in locals() else None,
        "clicks": clicks,
        "operations": operation_evidence,
        "error": error,
        "elapsed_seconds": round(time.time() - started, 3),
        "physical_gui_click": "PASS" if method_pass else "FAIL",
        "positive_production_software_update": "BLOCKED",
        "final_gate": "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
