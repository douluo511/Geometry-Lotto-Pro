"""Current-byte suites. Passing tests never establishes lottery skill."""
import argparse
from datetime import datetime,timezone
import hashlib,json,platform,re,subprocess,sys
from pathlib import Path

NAMES=('ssq_dlt_d2_v44','ssq_dlt_v45','ssq_dlt_agent_v1','ssq_dlt_d2_next','ssq_dlt_d2_forensics')

def manifest():
    root=Path(__file__).resolve().parents[2];result={}
    for name in NAMES:
        for path in sorted((root/'research'/name).rglob('*')):
            if path.is_file() and not {'__pycache__','evidence'}.intersection(path.parts) and path.suffix in ('.py','.ps1','.xml','.md','.txt','.json','.yml','.yaml'):
                result[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    workflow=root/'.github/workflows/ssq-dlt-d2-forensics.yml'
    result[workflow.relative_to(root).as_posix()]=hashlib.sha256(workflow.read_bytes()).hexdigest()
    return result

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False);before=manifest();root=Path(__file__).resolve().parents[2];suites=[];logs=[]
    for name in NAMES:
        command=[sys.executable,'-m','unittest','discover','-s',str(root/'research'/name/'tests'),'-v']
        result=subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        log=result.stdout+result.stderr;logs.append(name+'\n'+log);count=re.search(r'Ran (\d+) tests? in',log)
        suites.append(dict(component=name,command=command,exit_code=result.returncode,tests_run=int(count[1]) if count else 0,skips=len(re.findall(r'\.\.\. skipped ',log))))
    after=manifest();passed=before==after and all(x['exit_code']==0 and x['tests_run']>0 and x['skips']==0 for x in suites)
    receipt=dict(status='PASS' if passed else 'FAIL',recorded_at=datetime.now(timezone.utc).isoformat(),
        tests_run=sum(x['tests_run'] for x in suites),suites=suites,source_unchanged=before==after,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        python=sys.version,os=platform.platform(),scope='CURRENT_COMPONENT_TESTS_NOT_LOTTERY_EDGE',
        formal_A=0,decision='NO_EDGE',prospective_samples=0,full_P0_gate='BLOCKED',
        physical_boot_power_network='NOT_RUN',repository_independence='FAIL',final_gate='FAIL')
    for name,value in [('acceptance.json',receipt),('source_manifest.json',before)]:
        (args.output/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    (args.output/'tests.log').write_text('\n'.join(logs),encoding='utf-8');print(json.dumps(receipt));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
