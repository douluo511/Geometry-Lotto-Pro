"""All current-byte research suites, no paid model or live lottery claims."""
import argparse
from datetime import datetime,timezone
import hashlib,json,platform,re,subprocess,sys
from pathlib import Path

def manifest():
    root=Path(__file__).resolve().parents[2];result={}
    for name in ('ssq_dlt_d2_next','ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44'):
        for p in sorted((root/'research'/name).rglob('*')):
            if p.is_file() and not {'__pycache__','evidence'}.intersection(p.parts) and p.suffix in ('.py','.ps1','.xml','.md','.txt','.json','.yml','.yaml'):
                result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    ci=root/'.github/workflows/ssq-dlt-d2-next.yml'
    if ci.exists():result[ci.relative_to(root).as_posix()]=hashlib.sha256(ci.read_bytes()).hexdigest()
    return result

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);args=ap.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False);before=manifest();root=Path(__file__).resolve().parents[2];suites=[];logs=[]
    for name in ('ssq_dlt_d2_v44','ssq_dlt_v45','ssq_dlt_agent_v1','ssq_dlt_d2_next'):
        cmd=[sys.executable,'-m','unittest','discover','-s',str(root/'research'/name/'tests'),'-v']
        p=subprocess.run(cmd,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        text=p.stdout+p.stderr;logs.append(name+'\n'+text);count=re.search(r'Ran (\d+) tests? in',text)
        suites.append(dict(component=name,command=cmd,exit_code=p.returncode,tests_run=int(count[1]) if count else 0,skips=len(re.findall(r'\.\.\. skipped ',text))))
    after=manifest();passed=before==after and all(s['exit_code']==0 and s['tests_run']>0 and not s['skips'] for s in suites)
    report=dict(status='PASS' if passed else 'FAIL',scope='CURRENT_COMPONENT_FAULT_TESTS_NOT_PREDICTIVE_EDGE',
        recorded_at=datetime.now(timezone.utc).isoformat(),tests_run=sum(s['tests_run'] for s in suites),suites=suites,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        source_unchanged=before==after,python=sys.version,os=platform.platform(),paid_model_calls=0,
        formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0,P0_full_gate='BLOCKED',
        real_boot='NOT_RUN',physical_network_power_failure='NOT_RUN',repository_independence='FAIL',final_gate='FAIL')
    for name,value in [('acceptance.json',report),('source_manifest.json',before)]:
        (args.output/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    (args.output/'tests.log').write_text('\n'.join(logs),encoding='utf-8');print(json.dumps(report));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
