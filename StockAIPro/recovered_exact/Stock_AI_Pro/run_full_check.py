from pathlib import Path
import argparse,subprocess,sys,os
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from launcher import ensure_version_env,read_current,env_for

def run(cmd,cwd=None,env=None,timeout=90):
    print('>', ' '.join(map(str,cmd)),flush=True)
    try:
        r=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,timeout=timeout)
        return r.returncode==0
    except subprocess.TimeoutExpired:
        print('[FAIL] timeout:', ' '.join(map(str,cmd)),flush=True)
        return False

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--offline',action='store_true',help='Run engineering/security tests with current Python without installing network dependencies.')
    a=ap.parse_args()
    ok=True
    for t in ['distribution_layout_test.py','data_separation_test.py','updater_security_test.py','launcher_rollback_test.py','schema_rollback_compat_test.py','install_failfast_test.py','deterministic_build_test.py','package_manifest_test.py']:
        p=ROOT/'acceptance_tests'/t
        if p.exists(): ok=run([sys.executable,p],ROOT,timeout=45) and ok
    cur=read_current(ROOT);v=cur['active_version'];vd=ROOT/'versions'/v
    if a.offline:
        py=Path(sys.executable);venv_env=os.environ.copy();venv_env['STOCK_AI_DATA_ROOT']=str(ROOT/'_acceptance_userdata');venv_env['PYTHONUTF8']='1'
    else:
        py=ensure_version_env(v);venv_env=env_for(v)
    tests=sorted((vd/'tests').glob('*.py'))
    for t in tests: ok=run([py,t],vd,venv_env,timeout=90) and ok
    ok=run([py,vd/'healthcheck.py'],vd,venv_env,timeout=45) and ok
    print('ALL ENGINEERING ACCEPTANCE:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(main())
