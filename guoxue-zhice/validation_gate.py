from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PATTERNS={"unit":"test_core.py","contract":"test_network_contracts.py","fault":"test_network_contracts.py","integration":"test_*.py"}
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--suite",choices=sorted(PATTERNS),required=True); p.add_argument("--output",required=True); a=p.parse_args()
    cmd=[sys.executable,"-m","unittest","discover","-s","tests","-p",PATTERNS[a.suite],"-v"]
    proc=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    report={"schema":f"guoxue-{a.suite}-gate-v1","status":"PASS" if proc.returncode==0 else "FAIL","github_sha":os.environ.get("GITHUB_SHA"),"suite":a.suite,"exit_code":proc.returncode,"stdout":proc.stdout[-12000:],"stderr":proc.stderr[-12000:]}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"stdout","stderr"}},ensure_ascii=False))
    if proc.stdout: print(proc.stdout)
    if proc.stderr: print(proc.stderr,file=sys.stderr)
    return 0 if report["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
