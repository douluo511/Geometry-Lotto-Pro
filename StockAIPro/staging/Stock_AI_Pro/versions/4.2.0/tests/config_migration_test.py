import sys,tempfile,json
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stock_ai.config as cfg

with tempfile.TemporaryDirectory() as td:
    data=Path(td);data.mkdir(exist_ok=True)
    old={'schema_version':5,'model':{'top_k':7},'custom_user_key':'keep-me'}
    (data/'config.json').write_text(json.dumps(old),encoding='utf-8')
    with patch.object(cfg,'ROOT',data):
        out=cfg.ensure_user_config()
    disk=json.loads((data/'config.json').read_text(encoding='utf-8'))
    assert disk['schema_version']==6 and disk['model']['top_k']==7 and disk['custom_user_key']=='keep-me'
    assert disk['integrity']['prediction_hash_chain'] is True
    assert list((data/'backups'/'config_migrations').glob('*schema_5_to_6.json'))

with tempfile.TemporaryDirectory() as td:
    data=Path(td);(data/'config.json').write_text('{broken json',encoding='utf-8')
    with patch.object(cfg,'ROOT',data):out=cfg.ensure_user_config()
    assert out['schema_version']==6
    assert list((data/'backups'/'config_migrations').glob('*corrupt.json'))

with tempfile.TemporaryDirectory() as td:
    data=Path(td);(data/'config.json').write_text(json.dumps({'schema_version':99}),encoding='utf-8')
    with patch.object(cfg,'ROOT',data):
        try:cfg.ensure_user_config();raise AssertionError('future schema accepted by older app')
        except RuntimeError:pass
print('CONFIG SCHEMA MIGRATION/ROLLBACK TEST PASS')
