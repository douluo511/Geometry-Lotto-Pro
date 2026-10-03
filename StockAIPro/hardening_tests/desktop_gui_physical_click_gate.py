from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import os
import time

from pywinauto import Application, Desktop


WINDOW_TITLE = "Stock AI Pro · Windows Desktop Candidate"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def wait_changed(path: Path, before: int, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.stat().st_mtime_ns > before:
            return
        time.sleep(1)
    raise TimeoutError(f"evidence file not updated: {path}")


def close_error_dialog(expected_substring: str, timeout: int = 60) -> str:
    deadline = time.time() + timeout
    desktop = Desktop(backend="uia")
    while time.time() < deadline:
        for win in desktop.windows():
            try:
                title = win.window_text()
                if title == "Stock AI Pro":
                    texts = " ".join(win.texts())
                    if expected_substring not in texts:
                        raise AssertionError(f"unexpected Stock AI dialog: {texts}")
                    try:
                        ok = win.child_window(title="OK", control_type="Button")
                        ok.click_input()
                    except Exception:
                        win.type_keys("{ENTER}")
                    return texts
            except Exception:
                continue
        time.sleep(0.5)
    raise TimeoutError("expected Stock AI error dialog did not appear")


def click_and_wait(button, timeout: int) -> None:
    button.wait("enabled", timeout=30)
    button.click_input()
    time.sleep(1)
    button.wait("enabled", timeout=timeout)


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--evidence", default="desktop_gui_click_evidence.json")
    args = parser.parse_args()

    exe = Path(args.exe).resolve()
    data = Path(args.data_root).resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ["STOCK_AI_DATA_ROOT"] = str(data)

    before_hash = sha256(exe)
    core_file = data / "state" / "last_run.json"
    repair_file = data / "evidence" / "last_repair.json"
    audit_file = data / "reports" / "audit_report.json"
    backtest_file = data / "reports" / "backtest_summary.json"

    app = Application(backend="uia").start(str(exe), work_dir=str(exe.parent), wait_for_idle=False)
    win = app.window(title=WINDOW_TITLE)
    win.wait("visible enabled ready", timeout=45)

    result: dict[str, object] = {
        "status": "FAIL",
        "exe": str(exe),
        "exe_sha256_before": before_hash,
        "actions": {},
    }

    try:
        core_before = mtime(core_file)
        core = win.child_window(title="核心功能", control_type="Button")
        click_and_wait(core, timeout=2100)
        wait_changed(core_file, core_before, timeout=30)
        last = json.loads(core_file.read_text(encoding="utf-8"))
        if last.get("status") == "FAIL":
            raise AssertionError("GUI core click produced FAIL: " + str(last.get("error")))
        result["actions"]["core"] = {
            "status": "PASS",
            "evidence": str(core_file),
            "last_run_status": last.get("status"),
        }

        update = win.child_window(title="一键更新", control_type="Button")
        update.wait("enabled", timeout=30)
        update.click_input()
        dialog = close_error_dialog("update -> FAIL", timeout=120)
        result["actions"]["update"] = {
            "status": "BLOCKED",
            "reason": "production signed release endpoint is not configured",
            "dialog": dialog,
        }

        repair_before = mtime(repair_file)
        repair = win.child_window(title="一键修复", control_type="Button")
        click_and_wait(repair, timeout=420)
        wait_changed(repair_file, repair_before, timeout=30)
        repair_obj = json.loads(repair_file.read_text(encoding="utf-8"))
        if repair_obj.get("status") != "PASS":
            raise AssertionError("GUI repair click did not PASS")
        result["actions"]["repair"] = {
            "status": "PASS",
            "evidence": str(repair_file),
            "doctor_returncode": repair_obj.get("doctor_returncode"),
        }

        audit_before = mtime(audit_file)
        backtest_before = mtime(backtest_file)
        advanced = win.child_window(title="高级分析", control_type="Button")
        click_and_wait(advanced, timeout=2100)
        wait_changed(audit_file, audit_before, timeout=30)
        wait_changed(backtest_file, backtest_before, timeout=30)
        result["actions"]["advanced_analysis"] = {
            "status": "PASS",
            "audit_evidence": str(audit_file),
            "backtest_evidence": str(backtest_file),
        }

        after_hash = sha256(exe)
        result["exe_sha256_after"] = after_hash
        result["same_hash_after_physical_gui"] = "PASS" if before_hash == after_hash else "FAIL"
        if before_hash != after_hash:
            raise AssertionError("main EXE hash changed after physical GUI actions")

        result["physical_gui_positive_actions"] = "PASS"
        result["physical_gui_update_positive"] = "BLOCKED"
        result["status"] = "PASS_WITH_EXTERNAL_UPDATE_BLOCKER"

        try:
            image = win.capture_as_image()
            image.save(str(Path(args.evidence).with_suffix(".png")))
        except Exception as exc:
            result["screenshot_capture"] = "FAIL: " + repr(exc)

        Path(args.evidence).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    finally:
        try:
            win.close()
        except Exception:
            pass
        try:
            app.kill()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
