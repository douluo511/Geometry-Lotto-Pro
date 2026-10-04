from pathlib import Path
import json,os,platform,socket,sys,shutil
ROOT=Path(__file__).resolve().parent

def data_root():
    if os.environ.get('STOCK_AI_DATA_ROOT'):return Path(os.environ['STOCK_AI_DATA_ROOT'])
    if os.name=='nt' and os.environ.get('APPDATA'):return Path(os.environ['APPDATA'])/'StockAIPro'
    return ROOT/'userdata'

def main():
    d=data_root();(d/'reports').mkdir(parents=True,exist_ok=True);checks=[]
    def add(name,ok,detail=''):checks.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
    add('OS',True,platform.platform());add('Python>=3.11',sys.version_info>=(3,11),sys.version.split()[0]);add('current.json',(ROOT/'current.json').exists())
    try:cur=json.loads((ROOT/'current.json').read_text(encoding='utf-8'));ver=cur['active_version'];add('active_version',(ROOT/'versions'/ver).exists(),ver)
    except Exception as e:ver='?';add('active_version',False,str(e))
    add('runtime_venv',(ROOT/'.runtime_venv').exists());add('PowerShell',shutil.which('powershell') is not None or os.name!='nt');add('schtasks',shutil.which('schtasks') is not None or os.name!='nt')
    try:
        s=socket.socket();s.bind(('127.0.0.1',8501));s.close();add('port_8501_free',True)
    except Exception as e:add('port_8501_free',False,str(e))
    try:d.mkdir(parents=True,exist_ok=True);p=d/'_write_test';p.write_text('ok');p.unlink();add('data_dir_writable',True,str(d))
    except Exception as e:add('data_dir_writable',False,str(e))
    report={'platform':platform.platform(),'active_version':ver,'data_root':str(d),'checks':checks,'overall':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL'}
    (d/'reports'/'diagnose_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (d/'reports'/'diagnose_report.txt').write_text('\n'.join(f"{x['status']:4} {x['check']}: {x['detail']}" for x in checks),encoding='utf-8')
    for x in checks:print(x['status'],x['check'],x['detail'])
    print('RESULT',report['overall']);return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
