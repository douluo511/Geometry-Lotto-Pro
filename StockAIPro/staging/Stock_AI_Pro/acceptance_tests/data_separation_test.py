import os,sys,tempfile,subprocess
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1];v=json.loads((ROOT/'current.json').read_text(encoding='utf-8'))['active_version'];vd=ROOT/'versions'/v
with tempfile.TemporaryDirectory() as td:
    env=os.environ.copy();env['STOCK_AI_DATA_ROOT']=td
    code='from stock_ai.config import ROOT,CODE_ROOT; print(ROOT); print(CODE_ROOT); assert str(ROOT)!=str(CODE_ROOT)'
    r=subprocess.run([sys.executable,'-c',code],cwd=vd,env=env,capture_output=True,text=True);assert r.returncode==0,r.stderr
print('DATA SEPARATION TEST PASS')
