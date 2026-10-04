from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
launcher=(ROOT/'launcher.py').read_text(encoding='utf-8')
bootstrap=(ROOT/'BOOTSTRAP.ps1').read_text(encoding='utf-8')
import json
v=json.loads((ROOT/'current.json').read_text(encoding='utf-8'))['active_version']
vbootstrap=(ROOT/'versions'/v/'BOOTSTRAP.ps1').read_text(encoding='utf-8')
for text,name in [(launcher,'launcher.py'),(bootstrap,'BOOTSTRAP.ps1'),(vbootstrap,'version BOOTSTRAP.ps1')]:
    assert '--retries' in text, name
    assert '--timeout' in text, name
    assert '--no-input' in text, name
print('INSTALL FAIL-FAST CONTRACT TEST PASS')
