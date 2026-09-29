from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def self_test(exe: Path) -> dict:
    try:
        p = subprocess.run([str(exe), "--self-test"], timeout=120)
        return {"status": "PASS" if p.returncode == 0 else "FAIL", "exit_code": p.returncode}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}

def gui_smoke(exe: Path) -> dict:
    proc = None
    try:
        proc = subprocess.Popen([str(exe)])
        time.sleep(6)
        if proc.poll() is not None:
            return {"status": "FAIL", "error": f"GUI exited early code={proc.returncode}"}
        return {"status": "PASS", "pid": proc.pid}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    exe = Path(a.exe).resolve()
    exists = exe.exists() and exe.is_file()
    digest = sha256(exe) if exists else None
    st = self_test(exe) if exists else {"status": "FAIL", "error": "EXE missing"}
    gui = gui_smoke(exe) if exists else {"status": "FAIL", "error": "EXE missing"}
    windows = os.name == "nt" and os.environ.get("RUNNER_OS", "").lower() == "windows"
    report = {
        "schema": "english-root-exact-candidate-v1",
        "status": "PASS" if exists and windows and st["status"] == "PASS" and gui["status"] == "PASS" else "FAIL",
        "github_sha": os.environ.get("GITHUB_SHA"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "exe": exe.name,
        "exe_sha256": digest,
        "windows_build": "PASS" if exists and windows else "FAIL",
        "exact_exe": "PASS" if exists and windows and st["status"] == "PASS" else "FAIL",
        "self_test": st,
        "gui_smoke": gui,
    }
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
