"""Run all three current-byte suites; preserve logs without promoting P0 gates."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys


def manifest():
    root=Path(__file__).resolve().parents[2]; result={}
    for name in ('ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44'):
        for p in sorted((root/'research'/name).rglob('*')):
            if p.is_file() and not {'__pycache__','evidence'}.intersection(p.parts) and p.suffix in ('.py','.ps1','.xml','.md','.yaml','.yml','.json','.txt'):
                result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    ci=root/'.github/workflows/ssq-dlt-agent-v1.yml'
    if ci.is_file(): result[ci.relative_to(root).as_posix()]=hashlib.sha256(ci.read_bytes()).hexdigest()
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args(argv); args.output.mkdir(parents=True,exist_ok=False)
    before=manifest(); root=Path(__file__).resolve().parents[2]; outcomes=[]; logs=[]
    for component in ('ssq_dlt_d2_v44','ssq_dlt_v45','ssq_dlt_agent_v1'):
        command=[sys.executable,'-m','unittest','discover','-s',str(root/'research'/component/'tests'),'-v']
        child=subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        output=child.stdout+child.stderr; logs.append(component+'\n'+output)
        count=re.search(r'Ran (\d+) tests? in',output)
        outcomes.append(dict(component=component,command=command,exit_code=child.returncode,
            tests_run=int(count[1]) if count else 0,skipped=len(re.findall(r'\.\.\. skipped ',output)),
            failures=len(re.findall(r'^FAIL:',output,re.M)),errors=len(re.findall(r'^ERROR:',output,re.M))))
    after=manifest(); passed=before==after and all(o['exit_code']==0 and o['tests_run']>0 and o['skipped']==0 for o in outcomes)
    versions={name:importlib.metadata.version(name) for name in ('openai-agents','openai','cryptography','mcp')}
    report=dict(schema='GLP_AGENT_ACCEPTANCE_1',recorded_at=datetime.now(timezone.utc).isoformat(),
        status='PASS' if passed else 'FAIL',scope='CURRENT_COMPONENT_FAULT_TESTS_NOT_LIVE_MODEL_OR_PRODUCTION_QUALIFICATION',
        tests_run=sum(o['tests_run'] for o in outcomes),skipped=sum(o['skipped'] for o in outcomes),suites=outcomes,
        python=sys.version,os=platform.platform(),versions=versions,source_unchanged=before==after,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        SDK_live_model='BLOCKED_CREDENTIAL_MODEL_PRICES_REQUIRED',paid_api_calls=0,
        P0_full_gate='BLOCKED',scheduler_install='BLOCKED_ADMIN_REQUIRED',real_boot='NOT_RUN',elapsed_30_minute='NOT_RUN',
        physical_network_disconnect='NOT_RUN',physical_power_interruption='NOT_RUN',external_TSA_live_failure='NOT_RUN',
        formal_A=0,decision='NO_EDGE',repository_independence='FAIL',final_gate='FAIL')
    for name,value in (('source_manifest.json',before),('acceptance.json',report)):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'tests.log').write_text('\n'.join(logs),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False)); return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
