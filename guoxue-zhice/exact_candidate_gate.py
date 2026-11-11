from __future__ import annotations
import argparse, hashlib, json, os, subprocess, time
from pathlib import Path
def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--exe",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    exe=Path(a.exe).resolve(); exists=exe.exists() and exe.is_file(); digest=sha256(exe) if exists else None
    st={"status":"FAIL"}
    gui={"status":"FAIL"}
    if exists:
        try:
            q=subprocess.run([str(exe),"--self-test"],timeout=120)
            st={"status":"PASS" if q.returncode==0 else "FAIL","exit_code":q.returncode}
        except Exception as exc: st={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
        proc=None
        try:
            proc=subprocess.Popen([str(exe)]); time.sleep(6)
            gui={"status":"PASS","pid":proc.pid} if proc.poll() is None else {"status":"FAIL","exit_code":proc.returncode}
        except Exception as exc: gui={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except Exception: proc.kill()
    windows=os.name=="nt" and os.environ.get("RUNNER_OS","").lower()=="windows"
    status="PASS" if exists and windows and st["status"]=="PASS" and gui["status"]=="PASS" else "FAIL"
    report={"schema":"guoxue-exact-candidate-v1","status":status,"github_sha":(os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),"runner_os":os.environ.get("RUNNER_OS"),"exe_sha256":digest,"windows_build":"PASS" if exists and windows else "FAIL","exact_exe":"PASS" if exists and windows and st["status"]=="PASS" else "FAIL","self_test":st,"gui_smoke":gui}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
