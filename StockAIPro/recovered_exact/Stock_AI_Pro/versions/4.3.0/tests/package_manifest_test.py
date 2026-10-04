import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
m=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
assert 'config.json' not in m['files'], 'editable config.json must not be release-hash locked'
assert 'config.default.json' in m['files']
for rel,expected in m['files'].items():
    p=ROOT/rel;assert p.exists(),rel;assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,rel
actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p.name!='PACKAGE_MANIFEST.json' and p.relative_to(ROOT).as_posix()!='config.json' and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
uncontrolled=sorted(actual-set(m['files']))
assert not uncontrolled,'uncontrolled version files: '+repr(uncontrolled[:20])
assert int(m.get('file_count',-1))==len(m['files'])
print('PACKAGE MANIFEST BIDIRECTIONAL TEST PASS',len(m['files']))
