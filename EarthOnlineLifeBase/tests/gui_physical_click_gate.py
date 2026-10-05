from pathlib import Path
import argparse, hashlib, json, os, subprocess, time

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def wait_receipt(path:Path,expected:set[str],timeout=45):
    deadline=time.time()+timeout
    while time.time()<deadline:
        if path.is_file():
            try:
                data=load(path)
                if data.get("status") in expected: return data
            except Exception: pass
        time.sleep(.25)
    raise RuntimeError("receipt unavailable: "+str(path))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--exe",required=True); ap.add_argument("--output",required=True); a=ap.parse_args()
    from pywinauto import Desktop
    exe=Path(a.exe).resolve(); out=Path(a.output).resolve()
    data=Path(os.environ["EARTH_ONLINE_DATA_ROOT"]).resolve(); before=sha(exe); proc=None
    report={"status":"FAIL","physical_gui":"NOT VERIFIED","same_hash":"NOT VERIFIED","final_gate":"FAIL"}
    try:
        proc=subprocess.Popen([str(exe)],cwd=str(exe.parent),env=os.environ.copy())
        deadline=time.time()+45; win=None
        while time.time()<deadline:
            xs=[w for w in Desktop(backend="win32").windows() if w.window_text()=="Earth Online · Life Base · Reauthored Candidate"]
            if xs: win=Desktop(backend="win32").window(handle=xs[0].handle); break
            time.sleep(.25)
        if win is None: raise RuntimeError("window not found")
        layout_path=data/"evidence"/"ui_layout.json"
        plan=[
            ("决策训练","service_core.json",{"PASS"}),
            ("一键更新","service_update.json",{"BLOCKED"}),
            ("一键修复","service_repair.json",{"PASS"}),
            ("高级分析","service_advanced.json",{"PASS"}),
        ]
        actions={}
        receipts={}
        for label,receipt_name,expected in plan:
            deadline=time.time()+30
            while time.time()<deadline:
                if layout_path.is_file():
                    layout=load(layout_path); pt=layout.get("buttons",{}).get(label)
                    if pt and pt.get("state")=="normal": break
                time.sleep(.25)
            else: raise RuntimeError("layout unavailable "+label)
            receipt=data/"evidence"/receipt_name
            if receipt.exists(): receipt.unlink()
            rect=win.rectangle(); win.set_focus()
            win.click_input(coords=(int(pt["x"])-rect.left,int(pt["y"])-rect.top))
            receipts[label]=wait_receipt(receipt,expected)
            actions[label]="CLICKED_AND_VERIFIED"
        if receipts["高级分析"].get("business_content_import")!="PASS":
            raise RuntimeError("advanced analysis did not verify full software content import")
        after=sha(exe)
        report.update({"status":"BLOCKED","physical_gui":"PASS","actions":actions,"receipts":receipts,
                       "exe_sha256_before":before,"exe_sha256_after":after,
                       "same_hash":"PASS" if before==after else "FAIL",
                       "business_content_import":"PASS","repository_independence":"BLOCKED",
                       "positive_production_update":"BLOCKED"})
        if before!=after: report["status"]="FAIL"
        win.close()
    except Exception as exc:
        report["error"]=repr(exc)
    finally:
        if proc and proc.poll() is None: proc.kill()
        out.write_text(json.dumps(report,ensure_ascii=True,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report))
    return 1 if report["status"]=="FAIL" else 0
if __name__=="__main__": raise SystemExit(main())
