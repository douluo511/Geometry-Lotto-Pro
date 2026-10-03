from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1];cur=json.loads((ROOT/'current.json').read_text(encoding='utf-8'));v=cur['active_version'];vd=ROOT/'versions'/v
for p in ['launcher.py','updater_runtime/updater.py','ONE_CLICK_START.bat','BOOTSTRAP.ps1','WINDOWS_FIRST_RUN_ACCEPTANCE.bat','updater_public_key.pem',f'versions/{v}/app.py',f'versions/{v}/stock_ai/pipeline.py',f'versions/{v}/stock_ai/rnd.py',f'versions/{v}/RUN_RND.bat','release_tools/build_deterministic_zip.py']:assert (ROOT/p).exists(),p
assert not (ROOT/'Stock_AI_Pro_RELEASE_SIGNING_PRIVATE_KEY.pem').exists()
text=(ROOT/'ONE_CLICK_START.bat').read_text(encoding='utf-8');assert 'ENSURE_RUNTIME.bat' in text and 'launcher.py' in text
print('DISTRIBUTION LAYOUT TEST PASS')
