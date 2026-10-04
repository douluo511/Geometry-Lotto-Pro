import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
m=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
for rel,expected in m['files'].items():
    p=ROOT/rel;assert p.exists(),rel;assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,rel
# Release must never ship signing private keys or runtime state.
all_files=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()]
assert not any('private_key' in x.lower() or x.lower().endswith('.key') for x in all_files), 'private signing key leaked'
assert not any(x.startswith(('.venvs/','.runtime_venv/','userdata/','staging/')) for x in m['files']), 'runtime state included in manifest'
# Reverse completeness: every immutable shipped file except the manifest itself must be controlled.
ignored_prefixes=('.venvs/','.runtime_venv/','userdata/','staging/','_acceptance_userdata/')
expected_files={x for x in all_files if x!='PACKAGE_MANIFEST.json' and not x.startswith(ignored_prefixes) and '/__pycache__/' not in '/'+x and not x.endswith(('.pyc','.pyo'))}
uncontrolled=sorted(expected_files-set(m['files']))
assert not uncontrolled, 'uncontrolled release files: '+repr(uncontrolled[:20])
assert int(m.get('file_count',-1))==len(m['files'])
print('DISTRIBUTION PACKAGE MANIFEST BIDIRECTIONAL TEST PASS',len(m['files']))
