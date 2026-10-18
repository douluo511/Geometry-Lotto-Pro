"""Current-byte acceptance. Never promotes missing real-world P0 gates."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys


def manifest():
    base=Path(__file__).resolve().parent
    roots=[base,base.parent/'ssq_dlt_d2_v44']
    return {str(p.relative_to(base.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
            for root in roots for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and 'evidence' not in p.parts
            and p.suffix in ('.py','.ps1','.xml','.md','.yaml','.json','.txt')}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False)
    before=manifest()
    root=Path(__file__).resolve().parents[2]
    outcomes=[]
    logs=[]
    for component in ('ssq_dlt_d2_v44','ssq_dlt_v45'):
        tests=root/'research'/component/'tests'
        command=[sys.executable,'-m','unittest','discover','-s',str(tests),'-v']
        child=subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
        output=child.stdout+child.stderr
        logs.append(component+'\n'+output)
        count=re.search(r'Ran (\d+) tests? in',output)
        skipped=len(re.findall(r'\.\.\. skipped ',output))
        outcomes.append(dict(component=component,command=command,exit_code=child.returncode,tests_run=int(count[1]) if count else 0,
                             failures=len(re.findall(r'^FAIL:',output,re.M)),errors=len(re.findall(r'^ERROR:',output,re.M)),skipped=skipped))
    after=manifest()
    passed=all(o['exit_code']==0 and o['tests_run']>0 and not o['skipped'] for o in outcomes) and before==after
    report=dict(recorded_at=datetime.now(timezone.utc).isoformat(),scope='CURRENT_COMPONENT_FAULT_TESTS_NOT_PRODUCTION_QUALIFICATION',
                command='python -m research.ssq_dlt_v45.acceptance --output NEW_DIRECTORY',
                status='PASS' if passed else 'FAIL',tests_run=sum(o['tests_run'] for o in outcomes),failures=sum(o['failures'] for o in outcomes),errors=sum(o['errors'] for o in outcomes),skipped=sum(o['skipped'] for o in outcomes),suites=outcomes,
                python=sys.version,os=platform.platform(),source_unchanged=before==after,
                source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                P0_full_gate='BLOCKED',scheduler_install='BLOCKED',real_boot='NOT_RUN',elapsed_30_minute='NOT_RUN',
                physical_network_disconnect='NOT_RUN',physical_power_interruption='NOT_RUN',
                external_TSA_live_failure='NOT_RUN',formal_A=0,decision='NO_EDGE',repository_independence='FAIL',final_gate='FAIL')
    (args.output/'tests.log').write_text('\n'.join(logs),encoding='utf-8')
    (args.output/'source_manifest.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    (args.output/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
