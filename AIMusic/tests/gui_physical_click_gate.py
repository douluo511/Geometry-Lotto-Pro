from __future__ import annotations
import argparse, hashlib, json, os, subprocess, time
from pathlib import Path
from pywinauto import Desktop, mouse

TITLE="AI Music Production · Reauthored Candidate"

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path):return json.loads(p.read_text(encoding="utf-8"))
def wait_json(path:Path,timeout=60):
    end=time.time()+timeout
    while time.time()<end:
        if path.is_file():
            try:return load(path)
            except Exception:pass
        time.sleep(.25)
    raise TimeoutError(str(path))

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--exe",required=True);ap.add_argument("--root",required=True);ap.add_argument("--evidence",required=True);a=ap.parse_args()
    exe=Path(a.exe).resolve();root=Path(a.root).resolve();ev=Path(a.evidence).resolve()
    before=sha(exe);proc=subprocess.Popen([str(exe),"--root",str(root)],cwd=str(exe.parent),env=os.environ.copy())
    report={"status":"FAIL","physical_gui":"NOT VERIFIED","same_hash":"NOT VERIFIED"}
    try:
        layout=wait_json(root/"evidence"/"ui_layout.json",45)
        deadline=time.time()+30;win=None
        while time.time()<deadline:
            xs=[w for w in Desktop(backend="win32").windows(process=proc.pid,visible_only=True) if w.window_text()==TITLE]
            if xs:win=xs[0];break
            time.sleep(.25)
        if win is None:raise RuntimeError("window not found")
        receipts={
            "创作音乐":"compose.json",
            "一键更新":"update.json",
            "一键修复":"repair.json",
            "高级分析":"advanced.json",
        }
        actions={}
        for label,name in receipts.items():
            p=root/"evidence"/name
            if p.exists():p.unlink()
            pos=layout["buttons"][label]
            mouse.click(button="left",coords=(int(pos["center_x"]),int(pos["center_y"])))
            rec=wait_json(p,90)
            actions[label]=rec
        assert actions["创作音乐"]["status"]=="PASS"
        assert actions["一键更新"]["status"]=="BLOCKED"
        assert actions["一键修复"]["status"]=="PASS"
        assert actions["高级分析"]["status"]=="PASS"
        assert actions["高级分析"]["cloud_ai_provider_generation"]=="NOT VERIFIED"
        after=sha(exe)
        report={"status":"PASS" if after==before else "FAIL","physical_gui":"PASS",
                "same_hash":"PASS" if after==before else "FAIL",
                "exe_sha256_before":before,"exe_sha256_after":after,"actions":actions,
                "cloud_ai_provider_generation":"NOT VERIFIED","final_gate":"FAIL"}
        win.close()
    finally:
        if proc.poll() is None:proc.kill()
        ev.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=True))
    return 0 if report["status"]=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
