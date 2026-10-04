from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

from pywinauto import Application, Desktop, mouse


TITLE="Real-Money Finance System · Reauthored Candidate"


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def wait_changed(path: Path, before: int, timeout: int) -> None:
    deadline=time.time()+timeout
    while time.time()<deadline:
        if path.exists() and path.stat().st_mtime_ns>before:
            return
        time.sleep(0.5)
    raise TimeoutError(f"evidence not updated: {path}")


def wait_button_enabled(button, timeout: int) -> None:
    deadline=time.time()+timeout
    while time.time()<deadline:
        try:
            if button.is_enabled():
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("button did not re-enable")


def physical_click(win_spec, label: str, slot: str) -> str:
    root = win_spec.wrapper_object()
    try:
        for ctrl in root.descendants():
            try:
                if ctrl.window_text() == label:
                    ctrl.click_input()
                    return "semantic-descendant"
            except Exception:
                continue
    except Exception:
        pass

    rect = root.rectangle()
    slots = {
        "top_left": (0.26, 0.25),
        "top_right": (0.74, 0.25),
        "bottom_left": (0.26, 0.35),
        "bottom_right": (0.74, 0.35),
    }
    if slot not in slots:
        raise ValueError("unknown click slot: " + slot)
    fx, fy = slots[slot]
    x = int(rect.left + rect.width() * fx)
    y = int(rect.top + rect.height() * fy)
    mouse.click(button="left", coords=(x, y))
    return f"coordinate:{x},{y}"


def close_warning(timeout=60):
    deadline=time.time()+timeout
    desktop=Desktop(backend="uia")
    while time.time()<deadline:
        for win in desktop.windows():
            try:
                if win.window_text()=="Real-Money Finance":
                    texts=" ".join(win.texts())
                    if "signed production release endpoint" not in texts and "BLOCKED" not in texts:
                        raise AssertionError("unexpected update dialog: "+texts)
                    try:
                        win.child_window(title="OK", control_type="Button").click_input()
                    except Exception:
                        win.type_keys("{ENTER}")
                    return texts
            except Exception:
                continue
        time.sleep(0.5)
    raise TimeoutError("expected BLOCKED update warning not shown")


def main() -> int:
    ap=ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--evidence", default="gui_click_evidence.json")
    args=ap.parse_args()

    exe=Path(args.exe).resolve()
    root=Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    env=os.environ.copy()
    env["REAL_MONEY_FINANCE_ROOT"]=str(root)
    before_hash=sha256(exe)

    p=subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
    desktop=Desktop(backend="uia")
    deadline=time.time()+45
    win=None
    seen_titles=[]
    while time.time()<deadline:
        if p.poll() is not None:
            raise RuntimeError(f"Exact EXE exited before GUI appeared: rc={p.returncode}")
        try:
            windows=desktop.windows()
            seen_titles=[w.window_text() for w in windows if w.window_text()]
            matches=[w for w in windows if w.window_text()==TITLE]
            if matches:
                win=desktop.window(title=TITLE)
                break
        except Exception:
            pass
        time.sleep(0.5)
    if win is None:
        raise TimeoutError(f"GUI title not found; expected={TITLE!r}; seen_titles={seen_titles[-40:]!r}")
    win.wait("visible enabled", timeout=15)

    evidence={"status":"FAIL","exe_sha256_before":before_hash,"actions":{}}
    try:
        refresh=root/"evidence"/"refresh.json"
        capital=root/"evidence"/"capital_change.json"
        refresh_before=mtime(refresh)
        capital_before=mtime(capital)
        core_click=physical_click(win, "资金变化", "top_left")
        wait_changed(refresh, refresh_before, 240)
        wait_changed(capital, capital_before, 60)
        time.sleep(1)
        evidence["actions"]["capital_change"]={"status":"PASS","refresh":str(refresh),"capital":str(capital),"click":core_click}

        update_click=physical_click(win, "一键更新", "top_right")
        dialog=close_warning()
        time.sleep(1)
        evidence["actions"]["software_update"]={"status":"BLOCKED","dialog":dialog,"click":update_click}

        repair=root/"evidence"/"repair.json"
        repair_before=mtime(repair)
        repair_click=physical_click(win, "一键修复", "bottom_left")
        wait_changed(repair, repair_before, 60)
        time.sleep(1)
        robj=json.loads(repair.read_text(encoding="utf-8"))
        if robj.get("status")!="PASS":
            raise AssertionError("repair evidence not PASS")
        evidence["actions"]["repair"]={"status":"PASS","evidence":str(repair),"click":repair_click}

        advanced=root/"evidence"/"advanced_analysis.json"
        adv_before=mtime(advanced)
        advanced_click=physical_click(win, "高级分析", "bottom_right")
        wait_changed(advanced, adv_before, 60)
        time.sleep(1)
        evidence["actions"]["advanced_analysis"]={"status":"PASS","evidence":str(advanced),"click":advanced_click}

        after_hash=sha256(exe)
        evidence["exe_sha256_after"]=after_hash
        evidence["same_hash_after_gui"]="PASS" if before_hash==after_hash else "FAIL"
        if before_hash!=after_hash:
            raise AssertionError("EXE hash changed after physical GUI use")
        evidence["physical_gui_core_repair_advanced"]="PASS"
        evidence["physical_gui_update_positive"]="BLOCKED"
        evidence["status"]="PASS_WITH_EXTERNAL_UPDATE_BLOCKER"
        try:
            win.capture_as_image().save(str(Path(args.evidence).with_suffix(".png")))
        except Exception as exc:
            evidence["screenshot_capture"]="FAIL: "+repr(exc)
        Path(args.evidence).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    finally:
        try:
            win.close()
        except Exception:
            pass
        try:
            p.kill()
        except Exception:
            pass


if __name__=="__main__":
    raise SystemExit(main())
