"""Run complete relevant research suites with captured commands and exit codes."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from . import audit

def main():
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    suites=[
      ("strict",["-m","unittest","research.strict_audit_20261113.test_audit","-v"]),
      ("mother",["-m","unittest","research.mother_v1.test_mother","research.mother_v1.test_source_identity","research.mother_v1.test_rolling_audit","-v"]),
      ("harness",["-m","unittest","discover","-s","research/harness_v46/tests","-v"]),
      ("supercompute",["-m","unittest","discover","-s","research/supercompute/tests","-v"]),
    ]
    results=[]
    for name,cmd in suites:
        log=args.out/(name+".log")
        with log.open("w",encoding="utf-8",newline="\n") as stream:
            result=subprocess.run([sys.executable,*cmd],cwd=audit.ROOT,stdout=stream,stderr=subprocess.STDOUT,
                                  env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        count=re.search(r"Ran (\d+) tests?",log.read_text(encoding="utf-8"))
        if not count or int(count[1])==0:
            result.returncode=result.returncode or 1
        entry={"suite":name,"command":[sys.executable,*cmd],"exit_code":result.returncode,
               "status":"PASS" if result.returncode==0 else "FAIL",
               "tests":int(count[1]) if count else None,"log_sha256":audit.digest(log.read_bytes())}
        results.append(entry);print(json.dumps(entry),flush=True)
    receipt={"results":results,"created_utc_untrusted":datetime.now(timezone.utc).isoformat(),
             "github_sha":os.environ.get("GITHUB_SHA"),"github_run_id":os.environ.get("GITHUB_RUN_ID")}
    (args.out/"verification.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    if any(x["exit_code"] for x in results): raise SystemExit(1)
    audit.run(args.out/"analysis")
if __name__=="__main__":main()
