from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import ImageGrab
from pywinauto import Application, Desktop, mouse


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_actions(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wait_action(path: Path, action: str, timeout: float=120.0) -> dict:
    end=time.time()+timeout
    while time.time()<end:
        items=read_actions(path)
        for item in reversed(items):
            if item.get("action")==action:
                return item
        time.sleep(.5)
    raise TimeoutError(f"GUI audit timeout for {action}")


def wait_layout(app: Application, path: Path, timeout: float=40.0) -> dict:
    end=time.time()+timeout
    while time.time()<end:
        if path.is_file():
            obj=json.loads(path.read_text(encoding="utf-8"))
            if obj.get("status")=="PASS" and int(obj.get("pid",-1))==int(app.process):
                return obj
        if not app.is_process_running():
            raise RuntimeError("Exact EXE exited before publishing GUI layout evidence")
        time.sleep(.25)
    windows=Desktop(backend="win32").windows(process=app.process,visible_only=True)
    raise TimeoutError(f"GUI layout timeout; pid={app.process}; visible_windows={len(windows)}")


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--exe",required=True)
    ap.add_argument("--root",required=True)
    ap.add_argument("--evidence",required=True)
    args=ap.parse_args()
    exe=Path(args.exe).resolve()
    root=Path(args.root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    before=digest(exe)
    app=Application(backend="win32").start(f'"{exe}" --root "{root}"')
    layout_path=root/"evidence"/"ui_layout.json"
    audit=root/"evidence"/"gui_actions.jsonl"
    layout=wait_layout(app,layout_path)
    windows=Desktop(backend="win32").windows(process=app.process,visible_only=True)
    if not windows:
        raise RuntimeError(f"no visible process-bound top-level window for pid={app.process}")
    win=windows[0]
    win.set_focus()
    time.sleep(.5)

    expected=("核心研习","一键更新","一键修复","高级分析")
    if set(layout.get("buttons",{}))!=set(expected):
        raise AssertionError(f"frozen GUI entry inventory mismatch: {layout.get('buttons')}")
    results={}
    try:
        for action in expected:
            pos=layout["buttons"][action]
            x=int(pos["center_x"]); y=int(pos["center_y"])
            if int(pos["width"])<=0 or int(pos["height"])<=0:
                raise AssertionError(f"invalid visible button geometry for {action}")
            mouse.click(button="left",coords=(x,y))
            item=wait_action(audit,action,180 if action=="核心研习" else 90)
            results[action]=item
        rect=win.rectangle()
        ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom)).save(str(Path(args.evidence).with_suffix(".png")))
    finally:
        try:
            win.close()
        except Exception:
            pass
    after=digest(exe)
    assert before==after
    assert results["核心研习"]["status"]=="PASS"
    assert results["一键更新"]["status"]=="BLOCKED"
    assert results["一键修复"]["status"]=="PASS"
    assert results["高级分析"]["status"]=="PASS"
    update_payload=results["一键更新"].get("payload",{})
    assert update_payload.get("independent_process_returncode")==3
    assert "Updater" in str(update_payload.get("independent_updater_path",""))
    report={
        "status":"PASS",
        "physical_gui":"PASS",
        "click_method":"OS physical mouse coordinates from exact process-published screen geometry",
        "process_id":app.process,
        "layout":layout,
        "same_hash":"PASS",
        "exe_sha256_before":before,
        "exe_sha256_after":after,
        "actions":results,
        "positive_production_update":"BLOCKED",
    }
    Path(args.evidence).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
