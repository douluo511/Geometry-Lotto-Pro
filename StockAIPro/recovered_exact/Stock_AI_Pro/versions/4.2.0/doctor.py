import sys,importlib
from stock_ai.config import ROOT,CODE_ROOT,ensure_dirs,load_config
from stock_ai.features import FEATURES
CRITICAL_AK_INTERFACES=['stock_zh_a_spot_em','stock_zh_a_spot','stock_zh_a_hist','stock_zh_a_hist_tx','stock_info_a_code_name','stock_info_sz_delist','stock_info_sh_delist','stock_zh_index_daily_em','stock_zh_index_daily_tx','stock_zh_valuation_baidu','stock_value_em']
def main():
    ensure_dirs();ok=True;print('Stock AI Pro 4.2 Doctor');print('Python:',sys.version.split()[0]);print('Code:',CODE_ROOT);print('Data:',ROOT)
    if sys.version_info<(3,11):print('[FAIL] 需要 Python 3.11+');ok=False
    else:print('[OK] Python >= 3.11')
    mods={}
    for m in ['pandas','numpy','sklearn','streamlit','akshare','joblib','requests']:
        try:mod=importlib.import_module(m);mods[m]=mod;print('[OK]',m,getattr(mod,'__version__',''))
        except Exception as e:print('[FAIL]',m,e);ok=False
    ak=mods.get('akshare')
    if ak is not None:
        missing=[x for x in CRITICAL_AK_INTERFACES if not hasattr(ak,x)]
        if missing:print('[FAIL] AKShare关键接口缺失:',','.join(missing));ok=False
        else:print('[OK] AKShare关键接口完整:',len(CRITICAL_AK_INTERFACES))
    try:
        cfg=load_config();total=sum(float(v) for v in cfg['weights'].values());assert abs(total-1)<1e-8;assert int(cfg.get('schema_version',0))>=6;assert bool(cfg.get('integrity',{}).get('prediction_hash_chain',False));assert bool(cfg.get('integrity',{}).get('rnd_evidence_registry',False));assert cfg.get('model',{}).get('ensemble_mode') in {'validation_dynamic','ridge_only','hgb_only','equal','equal_ensemble'};assert not bool(cfg.get('rnd',{}).get('auto_promote',False));print('[OK] config schema/weights/R&D safety')
    except Exception as e:print('[FAIL] config',e);ok=False
    try:t=ROOT/'cache'/'_write_test.txt';t.write_text('ok',encoding='utf-8');t.unlink();print('[OK] 用户数据目录可写')
    except Exception as e:print('[FAIL] 用户数据目录不可写',e);ok=False
    print('[OK] feature count',len(FEATURES));print('RESULT:','PASS' if ok else 'FAIL');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
