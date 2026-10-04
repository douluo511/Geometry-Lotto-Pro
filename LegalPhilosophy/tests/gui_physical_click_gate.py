from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
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
            pid=int(obj.get("pid",-1))
            if obj.get("status")=="PASS" and pid>0:
                return obj
        time.sleep(.25)
    starter_running=app.is_process_running()
    starter_windows=Desktop(backend="win32").windows(process=app.process,visible_only=True) if starter_running else []
    raise TimeoutError(
        f"GUI layout timeout; starter_pid={app.process}; "
        f"starter_running={starter_running}; starter_visible_windows={len(starter_windows)}"
    )


def process_image_path(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION=0x1000
    kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
    handle=kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size=wintypes.DWORD(32768)
        buf=ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


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
    gui_pid=int(layout["pid"])
    image_path=Path(process_image_path(gui_pid)).resolve()
    if os.path.normcase(str(image_path)) != os.path.normcase(str(exe)):
        raise RuntimeError(f"GUI process image mismatch: {image_path} != {exe}")
    windows=Desktop(backend="win32").windows(process=gui_pid,visible_only=True)
    if not windows:
        raise RuntimeError(f"no visible exact-EXE top-level window for gui_pid={gui_pid}")
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
        "starter_process_id":app.process,
        "gui_process_id":gui_pid,
        "gui_process_image":str(image_path),
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
