import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
m=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
assert 'config.json' not in m['files'], 'editable config.json must not be release-hash locked'
assert 'config.default.json' in m['files']
for rel,expected in m['files'].items():
    p=ROOT/rel
    assert p.exists(), rel
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    assert got==expected, rel
print('PACKAGE MANIFEST TEST PASS',len(m['files']))
