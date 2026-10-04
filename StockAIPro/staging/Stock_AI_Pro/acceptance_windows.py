from pathlib import Path
import argparse,json,os,platform,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from launcher import data_root,ensure_version_env,run_health,read_current,env_for
from updater_runtime.updater import UPDATER_VERSION

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--live',action='store_true');a=ap.parse_args();d=data_root();(d/'reports').mkdir(parents=True,exist_ok=True);checks=[]
    def run(name,fn):
        try:ok,detail=fn();checks.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
        except Exception as e:checks.append({'check':name,'status':'FAIL','detail':repr(e)})
    run('Windows',lambda:(os.name=='nt',platform.platform()));cur=read_current(ROOT);ver=cur['active_version'];run('Fresh distribution structure',lambda:((ROOT/'versions'/ver/'app.py').exists(),ver))
    py=None
    def envcheck():
        nonlocal py;py=ensure_version_env(ver);return (py.exists(),str(py))
    run('Version dependency environment',envcheck)
    run('Offline healthcheck',lambda:(run_health(ver,py),'healthcheck.py'))
    run('Three-model stack contract',lambda:(all(x in (ROOT/'versions'/ver/'stock_ai'/'model.py').read_text(encoding='utf-8') for x in ['Ridge','HistGradientBoostingRegressor','ExtraTreesRegressor']),'Ridge+HGB+ExtraTrees'))
    run('Distribution manifest',lambda:(subprocess.run([str(py),str(ROOT/'acceptance_tests'/'package_manifest_test.py')],cwd=ROOT,env=env_for(ver)).returncode==0,'PACKAGE_MANIFEST.json'))
    run('Doctor',lambda:(subprocess.run([str(py),str(ROOT/'versions'/ver/'doctor.py')],cwd=ROOT/'versions'/ver,env=env_for(ver)).returncode==0,'doctor.py'))
    run('Task Scheduler available',lambda:(shutil.which('schtasks') is not None,'schtasks'))
    run('PowerShell available',lambda:(shutil.which('powershell') is not None,'powershell'))
    if a.live:
        def live():
            r=subprocess.run([str(py),str(ROOT/'versions'/ver/'run_daily.py')],cwd=ROOT/'versions'/ver,env=env_for(ver));return (r.returncode==0,'run_daily.py exit='+str(r.returncode))
        run('Live data + prediction',live);run('Frozen prediction created',lambda:((d/'predictions'/'latest'/'manifest.json').exists(),str(d/'predictions'/'latest')))
        run('R&D shadow frozen',lambda:((d/'predictions'/'latest'/'rnd_shadow.csv').exists(),str(d/'predictions'/'latest'/'rnd_shadow.csv')))
        run('R&D report created',lambda:((d/'reports'/'rnd_report.json').exists(),str(d/'reports'/'rnd_report.json')))
        run('Prediction hash chain',lambda:((d/'state'/'prediction_chain.json').exists(),str(d/'state'/'prediction_chain.json')))
        def evidence_or_waiting():
            rp=d/'reports'/'rnd_report.json'
            try:r=json.loads(rp.read_text(encoding='utf-8'))
            except Exception:return (False,'rnd_report unreadable')
            if r.get('status')=='WAITING_FOR_REALIZED_FROZEN_SAMPLES':return (True,'waiting for realized samples is valid on first runs')
            return ((d/'reports'/'rnd_evidence.json').exists(),'rnd_evidence.json')
        run('R&D evidence or valid waiting state',evidence_or_waiting)
    report={'generated_at':time.strftime('%Y-%m-%d %H:%M:%S'),'version':ver,'live_requested':a.live,'checks':checks,'overall':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL'}
    p=d/'reports'/'windows_acceptance.json';p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
