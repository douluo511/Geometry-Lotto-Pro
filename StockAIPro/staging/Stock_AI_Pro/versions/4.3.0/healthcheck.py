import sys,compileall,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REQ=['pandas','numpy','sklearn','joblib','requests','cryptography']
def main():
    ok=compileall.compile_dir(str(ROOT/'stock_ai'),quiet=1)
    for m in REQ:
        try:importlib.import_module(m)
        except Exception as e:print('[FAIL]',m,e);ok=False
    for f in ['app.py','run_daily.py','run_rnd.py','config.default.json','requirements.txt','stock_ai/pipeline.py','stock_ai/rnd.py','stock_ai/storage.py','stock_ai/config.py']:
        if not (ROOT/f).exists():print('[FAIL] missing',f);ok=False
    try:
        import json
        c=json.loads((ROOT/'config.default.json').read_text(encoding='utf-8'));assert int(c.get('schema_version',0))>=6;assert c.get('integrity',{}).get('prediction_hash_chain') is True
    except Exception as e:print('[FAIL] config integrity schema',e);ok=False
    print('HEALTHCHECK:', 'PASS' if ok else 'FAIL');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
