from __future__ import annotations
from pathlib import Path
import argparse,json,os,socket,subprocess,sys,time,venv,webbrowser
from updater_runtime.updater import check_and_stage,activate_pending,mark_healthy,rollback,read_current,recover_interrupted_update
ROOT=Path(__file__).resolve().parent

def data_root():
    e=os.environ.get('STOCK_AI_DATA_ROOT')
    if e:return Path(e)
    if os.name=='nt' and os.environ.get('APPDATA'):return Path(os.environ['APPDATA'])/'StockAIPro'
    return ROOT/'userdata'

def log(msg):
    d=data_root();(d/'logs').mkdir(parents=True,exist_ok=True);line=time.strftime('%Y-%m-%d %H:%M:%S')+' | '+msg;print(line,flush=True)
    with (d/'logs'/'startup.log').open('a',encoding='utf-8') as f:f.write(line+'\n')

def py_in_env(env):return env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def ensure_version_env(version):
    env=ROOT/'.venvs'/version;py=py_in_env(env);vd=ROOT/'versions'/version
    if not py.exists():
        log(f'创建版本环境 {version}...');env.parent.mkdir(parents=True,exist_ok=True);venv.EnvBuilder(with_pip=True,clear=False).create(env)
    marker=env/'.requirements.sha256';req=vd/'requirements.txt';import hashlib;digest=hashlib.sha256(req.read_bytes()).hexdigest()
    if not marker.exists() or marker.read_text().strip()!=digest:
        log(f'安装/修复版本依赖 {version}...')
        cmd=[str(py),'-m','pip','install','--disable-pip-version-check','--no-input','--retries','1','--timeout','8','-r',str(req)]
        r=subprocess.run(cmd,cwd=vd)
        if r.returncode!=0:
            # Bounded mirror fallback; never hang indefinitely. Old version remains active if both fail.
            r=subprocess.run(cmd+['-i','https://pypi.tuna.tsinghua.edu.cn/simple'],cwd=vd)
        if r.returncode!=0:raise RuntimeError(f'依赖安装失败 version={version}')
        marker.write_text(digest,encoding='utf-8')
    return py

def env_for(version):
    e=os.environ.copy();e['STOCK_AI_DATA_ROOT']=str(data_root());e['PYTHONUTF8']='1';return e

def run_health(version,py):
    vd=ROOT/'versions'/version;r=subprocess.run([str(py),str(vd/'healthcheck.py')],cwd=vd,env=env_for(version));return r.returncode==0

def load_updater_config():
    d=data_root();d.mkdir(parents=True,exist_ok=True);p=d/'updater.json'
    if not p.exists():p.write_text((ROOT/'updater_config.default.json').read_text(encoding='utf-8'),encoding='utf-8')
    try:return json.loads(p.read_text(encoding='utf-8'))
    except Exception:return {'enabled':False}

def maybe_update():
    cfg=load_updater_config()
    if not cfg.get('enabled') or not cfg.get('check_on_start',True):return None
    log('检查软件更新...')
    try:
        cand=check_and_stage(ROOT,cfg)
        if not cand:return None
        log(f'发现并验证新版 {cand}');py=ensure_version_env(cand)
        if not run_health(cand,py):raise RuntimeError('新版离线Health Check失败')
        activate_pending(ROOT,cand);log(f'新版 {cand} 已进入待启动验证状态');return cand
    except Exception as e:log('软件更新检查失败，继续使用当前版本: '+str(e));return None

def port_open(port=8501):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.5):return True
    except OSError:return False

def start_ui(version,py,pending):
    vd=ROOT/'versions'/version
    if port_open(8501):
        log('8501端口已有服务，直接打开浏览器。');webbrowser.open('http://127.0.0.1:8501');
        if pending:mark_healthy(ROOT)
        return 0
    log('启动 Web UI...');proc=subprocess.Popen([str(py),'-m','streamlit','run',str(vd/'app.py'),'--server.port','8501','--server.headless','true'],cwd=vd,env=env_for(version))
    ok=False
    for _ in range(30):
        if proc.poll() is not None:break
        if port_open(8501):ok=True;break
        time.sleep(.5)
    if ok:
        if pending:mark_healthy(ROOT);log('新版启动自检 PASS，版本切换提交。')
        webbrowser.open('http://127.0.0.1:8501');return proc.wait()
    if pending:
        log('新版 UI 启动失败，自动回滚。');proc.terminate()
        if rollback(ROOT):
            cur=read_current(ROOT);prev=cur['active_version'];ppy=ensure_version_env(prev)
            if run_health(prev,ppy):return start_ui(prev,ppy,False)
    raise RuntimeError('Streamlit 未能在15秒内启动；请查看 startup.log')

def current_version():return read_current(ROOT)['active_version']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--daily-only',action='store_true');ap.add_argument('--ui-only',action='store_true');ap.add_argument('--backtest',action='store_true');ap.add_argument('--audit',action='store_true');ap.add_argument('--rnd',action='store_true');ap.add_argument('--update-only',action='store_true');a=ap.parse_args()
    data_root().mkdir(parents=True,exist_ok=True)
    if recover_interrupted_update(ROOT): log('检测到中断更新且活动版本缺失，已自动回滚。')
    maybe_update();cur=read_current(ROOT);version=cur['active_version'];pending=bool(cur.get('pending_health'));log(f'当前程序版本 {version}；数据目录 {data_root()}')
    py=ensure_version_env(version)
    if not run_health(version,py):
        if pending and rollback(ROOT):
            log('新版离线自检失败，已回滚。');version=current_version();py=ensure_version_env(version)
            if not run_health(version,py):raise RuntimeError('回滚版本Health Check也失败')
        else:raise RuntimeError('当前版本Health Check失败')
    if a.update_only:
        if pending:mark_healthy(ROOT)
        return 0
    vd=ROOT/'versions'/version;env=env_for(version)
    if a.backtest:return subprocess.call([str(py),str(vd/'run_backtest.py')],cwd=vd,env=env)
    if a.audit:return subprocess.call([str(py),str(vd/'run_audit.py')],cwd=vd,env=env)
    if a.rnd:return subprocess.call([str(py),str(vd/'run_rnd.py')],cwd=vd,env=env)
    if not a.ui_only:
        log('更新数据、训练并生成预测...');r=subprocess.run([str(py),str(vd/'run_daily.py')],cwd=vd,env=env)
        if r.returncode!=0:log('本次数据/预测失败；最后一次有效冻结结果仍保留。')
    if a.daily_only:
        if pending:mark_healthy(ROOT)
        return r.returncode if 'r' in locals() else 0
    return start_ui(version,py,pending)
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:log('启动失败: '+repr(e));raise
