"""Current-byte tests of the new audit component, not inherited 497 tests."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,platform,re,subprocess,sys
from .protocol import ROOT,BOUNDARY

def manifest():
    files={}
    for name in ('ssq_dlt_d2_negative_audit','ssq_dlt_d2_next','ssq_dlt_d2_forensics','ssq_dlt_v45','ssq_dlt_d2_v44'):
        for path in sorted((ROOT/'research'/name).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and (path.suffix in ('.py','.md') or path.name=='.gitattributes'):
                files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    path=ROOT/'.github/workflows/ssq-dlt-negative-replay.yml'
    files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return files

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False);before=manifest()
    cmd=[sys.executable,'-m','unittest','discover','-s','research/ssq_dlt_d2_negative_audit/tests','-v']
    run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    log=run.stdout+run.stderr;match=re.search(r'Ran (\d+) tests? in',log);count=int(match[1]) if match else 0
    skipped=len(re.findall(r'\.\.\. skipped ',log));after=manifest()
    receipt=dict(status='PASS' if run.returncode==0 and count>0 and skipped==0 and before==after else 'FAIL',recorded_at=datetime.now(timezone.utc).isoformat(),
        tests_run=count,skips=skipped,exit_code=run.returncode,command=cmd,source_unchanged=before==after,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        scope='NEW_NEGATIVE_REPLAY_COMPONENT_TESTS_ONLY_NOT_INHERITED_497_OR_FULL_2880_REPLAY',python=sys.version,os=platform.platform(),**BOUNDARY)
    (args.output/'tests.log').write_text(log,encoding='utf-8',newline='\n')
    (args.output/'source_manifest.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(receipt));return 0 if receipt['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
