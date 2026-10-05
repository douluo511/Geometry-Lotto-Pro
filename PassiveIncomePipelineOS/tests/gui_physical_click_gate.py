from __future__ import annotations
import argparse,ctypes,hashlib,json,os,time
from ctypes import wintypes
from pathlib import Path
from PIL import ImageGrab
from pywinauto import Application,Desktop,mouse
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def records(p):
    p=Path(p);return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []
def wait_action(p,a,timeout=120):
    end=time.time()+timeout
    while time.time()<end:
        for x in reversed(records(p)):
            if x.get("action")==a:return x
        time.sleep(.5)
    raise TimeoutError(a)
def wait_layout(p,timeout=40):
    p=Path(p);end=time.time()+timeout
    while time.time()<end:
        if p.is_file():
            x=json.loads(p.read_text(encoding="utf-8"))
            if x.get("status")=="PASS" and int(x.get("pid",-1))>0:return x
        time.sleep(.25)
    raise TimeoutError("layout")
def process_image(pid):
    k=ctypes.WinDLL("kernel32",use_last_error=True);h=k.OpenProcess(0x1000,False,int(pid))
    if not h:raise ctypes.WinError(ctypes.get_last_error())
    try:
        n=wintypes.DWORD(32768);b=ctypes.create_unicode_buffer(n.value)
        if not k.QueryFullProcessImageNameW(h,0,b,ctypes.byref(n)):raise ctypes.WinError(ctypes.get_last_error())
        return b.value
    finally:k.CloseHandle(h)
def main():
    p=argparse.ArgumentParser();p.add_argument("--exe",required=True);p.add_argument("--root",required=True);p.add_argument("--evidence",required=True);a=p.parse_args()
    exe=Path(a.exe).resolve();root=Path(a.root).resolve();root.mkdir(parents=True,exist_ok=True);before=digest(exe)
    app=Application(backend="win32").start(f'"{exe}" --root "{root}"');layout=wait_layout(root/"evidence"/"ui_layout.json");pid=int(layout["pid"])
    if os.path.normcase(str(Path(process_image(pid)).resolve()))!=os.path.normcase(str(exe)):raise RuntimeError("GUI process image mismatch")
    wins=Desktop(backend="win32").windows(process=pid,visible_only=True)
    if not wins:raise RuntimeError("no visible exact EXE window")
    win=wins[0];win.set_focus();time.sleep(.5);expected=("收益总览","一键更新","一键修复","高级分析");assert set(layout["buttons"])==set(expected);out={}
    try:
        for label in expected:
            pt=layout["buttons"][label];mouse.click(button="left",coords=(int(pt["center_x"]),int(pt["center_y"])));out[label]=wait_action(root/"evidence"/"gui_actions.jsonl",label,180)
        r=win.rectangle();ImageGrab.grab(bbox=(r.left,r.top,r.right,r.bottom)).save(str(Path(a.evidence).with_suffix(".png")))
    finally:
        try:win.close()
        except Exception:pass
    after=digest(exe);assert before==after
    assert out["收益总览"]["status"]=="PASS" and out["收益总览"]["payload"]["production_income_verified"] is False
    assert out["一键更新"]["status"]=="BLOCKED" and out["一键更新"]["payload"]["independent_process_returncode"]==3
    assert out["一键修复"]["status"]=="PASS" and out["高级分析"]["status"]=="PASS"
    report={"status":"PASS","physical_gui":"PASS","same_hash":"PASS","exe_sha256_before":before,"exe_sha256_after":after,"actions":out,"positive_production_update":"BLOCKED","click_method":"OS physical mouse coordinates from exact process-published screen geometry"}
    Path(a.evidence).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report,ensure_ascii=True));return 0
if __name__=="__main__":raise SystemExit(main())
