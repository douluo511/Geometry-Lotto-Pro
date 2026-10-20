"""Evidence for this fault-audit component only, not full P0 or model skill."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=Path(__file__).resolve().parent

def manifest():
    pins=json.loads((PACKAGE/'frozen-science-sha256.json').read_bytes())
    assert len(pins)==49
    files={}
    for name,expected in pins.items():
        actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if actual!=expected:raise ValueError('FROZEN_SCIENCE_SOURCE_CHANGED')
        files[name]=actual
    for path in PACKAGE.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and (path.suffix in ('.py','.md','.json') or path.name=='.gitattributes'):
            files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    workflow=ROOT/'.github/workflows/ssq-dlt-asof-audit.yml'
    files[workflow.relative_to(ROOT).as_posix()]=hashlib.sha256(workflow.read_bytes()).hexdigest()
    return files

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.output.is_absolute():raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
    args.output=args.output.resolve()
    if args.output.is_relative_to(ROOT) or ROOT.is_relative_to(args.output):
        raise ValueError('OUTPUT_MUST_BE_SEPARATE_FROM_SOURCE')
    args.output.mkdir(parents=True,exist_ok=False)
    before=manifest();cmd=[sys.executable,'-m','unittest','discover','-s','research/ssq_dlt_asof_audit/tests','-v']
    errors=[];timed_out=False
    try:
        run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        log=run.stdout+run.stderr;exit_code=run.returncode
    except subprocess.TimeoutExpired as exc:
        def decoded(value):return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
        log=decoded(exc.stdout)+decoded(exc.stderr);exit_code=None;timed_out=True
        errors.append('TEST_TIMEOUT_PARTIAL_LOG_RETAINED')
    found=re.search(r'Ran (\d+) tests? in',log)
    count=int(found[1]) if found else 0;skips=len(re.findall(r'\.\.\. skipped ',log))
    try:after=manifest()
    except (ValueError,OSError) as exc:after=None;errors.append(type(exc).__name__+':SOURCE_RECHECK_FAILED')
    receipt=dict(status='PASS' if exit_code==0 and count>0 and skips==0 and before==after and not errors else 'FAIL',
        recorded_at=datetime.now(timezone.utc).isoformat(),tests_run=count,skips=skips,exit_code=exit_code,
        timed_out=timed_out,errors=errors,
        argv=cmd,source_unchanged=before==after,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        frozen_science_source_count=49,scope='ASOF_SYNTHETIC_FAULT_COMPONENT_ONLY_NOT_FULL_RUNTIME_OR_PHYSICAL_P0',
        python=sys.version,os=platform.platform(),formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0,
        official_next_legal_issue='BLOCKED',new_prediction_candidates=0,new_prediction_seeds=0,
        repository_independence='FAIL',final_gate='FAIL')
    (args.output/'tests.log').write_text(log,encoding='utf-8',newline='\n')
    (args.output/'source_manifest.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(receipt));return 0 if receipt['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
