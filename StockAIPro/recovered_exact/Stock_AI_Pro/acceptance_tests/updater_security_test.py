import sys,tempfile,json,copy,zipfile,shutil
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import updater_runtime.updater as up
fx=Path(__file__).resolve().parent/'fixtures';manifest=json.loads((fx/'manifest_4.0.1.json').read_text(encoding='utf-8'));pub=(ROOT/'updater_public_key.pem').read_bytes()
assert up.verify_manifest_signature(manifest,pub)
assert up.validate_manifest(manifest)

with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions'/'4.0.0').mkdir(parents=True);(r/'staging').mkdir();(r/'acceptance_tests'/'fixtures').mkdir(parents=True)
    shutil.copy2(fx/'4.0.1.zip',r/'acceptance_tests'/'fixtures'/'4.0.1.zip')
    (r/'current.json').write_text(json.dumps({'active_version':'4.0.0','previous_version':None,'pending_health':False,'failed_release_ids':[]}))
    v=up.stage_update(r,manifest,pub);assert v=='4.0.1';assert up.read_current(r)['active_version']=='4.0.0'
    j=json.loads((r/'staging'/'update_journal.json').read_text());assert j['state']=='STAGED'
    up.activate_pending(r,v);cur=up.read_current(r);assert cur['active_version']=='4.0.1' and cur['pending_health'] and cur.get('pending_release_id')
    failed_id=cur['pending_release_id'];assert up.rollback(r);cur=up.read_current(r);assert cur['active_version']=='4.0.0' and failed_id in cur['failed_release_ids']
    # Broken release must not be silently retried forever.
    try:up.stage_update(r,manifest,pub);raise AssertionError('failed release retried')
    except RuntimeError as e:assert 'Health Check' in str(e)

# signature tamper must fail
bad=copy.deepcopy(manifest);bad['version']='9.9.9'
try:up.verify_manifest_signature(bad,pub);raise AssertionError('tampered manifest accepted')
except Exception:pass

# manifest contract: insecure transport and impossible updater version must fail before install
bad_contract=copy.deepcopy(manifest);bad_contract['package_url']='http://example.invalid/a.zip'
try:up.validate_manifest(bad_contract);raise AssertionError('http package accepted')
except ValueError:pass
bad_contract=copy.deepcopy(manifest);bad_contract['min_updater_version']='99.0.0'
try:up.validate_manifest(bad_contract);raise AssertionError('unsupported updater accepted')
except RuntimeError:pass

# zip traversal must fail
with tempfile.TemporaryDirectory() as td:
    z=Path(td)/'bad.zip'
    with zipfile.ZipFile(z,'w') as q:q.writestr('../escape.txt','bad')
    try:up.safe_extract(z,Path(td)/'out');raise AssertionError('path traversal accepted')
    except ValueError:pass

# symlink entries must be rejected
with tempfile.TemporaryDirectory() as td:
    z=Path(td)/'symlink.zip'
    with zipfile.ZipFile(z,'w') as q:
        info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(0o120777 << 16);q.writestr(info,'../escape.txt')
    try:up.safe_extract(z,Path(td)/'out');raise AssertionError('symlink archive member accepted')
    except ValueError:pass

# zip bomb guard: file count and uncompressed bytes are bounded before extract.
with tempfile.TemporaryDirectory() as td:
    z=Path(td)/'many.zip'
    with zipfile.ZipFile(z,'w',compression=zipfile.ZIP_DEFLATED) as q:
        q.writestr('a.txt','a'*2000);q.writestr('b.txt','b'*2000)
    for kwargs in ({'max_files':1},{'max_uncompressed_bytes':1000}):
        try:up.safe_extract(z,Path(td)/'out',**kwargs);raise AssertionError('archive safety limit bypassed')
        except ValueError:pass

# Manifest version and package VERSION must agree even when signature validation itself succeeds.
with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions').mkdir();(r/'staging').mkdir();(r/'current.json').write_text(json.dumps({'active_version':'4.1.0','previous_version':None,'pending_health':False}))
    z=r/'payload.zip'
    with zipfile.ZipFile(z,'w') as q:
        q.writestr('VERSION','4.2.9');q.writestr('requirements.txt','');q.writestr('app.py','');q.writestr('stock_ai/__init__.py','')
    m={'version':'4.2.0','package_url':'file://'+str(z),'size':z.stat().st_size,'sha256':up.sha256(z),'signature':'ignored'}
    with patch.object(up,'verify_manifest_signature',return_value=True):
        try:up.stage_update(r,m,pub);raise AssertionError('VERSION mismatch accepted')
        except ValueError as e:assert 'VERSION mismatch' in str(e)

# Interrupted state with missing active version must roll back without guessing health.
with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions'/'4.1.0').mkdir(parents=True);(r/'staging').mkdir()
    (r/'current.json').write_text(json.dumps({'active_version':'4.2.0','previous_version':'4.1.0','pending_health':True,'pending_release_id':'broken-42'}))
    assert up.recover_interrupted_update(r);cur=up.read_current(r);assert cur['active_version']=='4.1.0' and 'broken-42' in cur['failed_release_ids']

# Automatic downgrade/reinstall is forbidden even for a structurally valid candidate.
with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions'/'4.0.1').mkdir(parents=True);(r/'staging').mkdir();(r/'acceptance_tests'/'fixtures').mkdir(parents=True)
    shutil.copy2(fx/'4.0.1.zip',r/'acceptance_tests'/'fixtures'/'4.0.1.zip')
    (r/'current.json').write_text(json.dumps({'active_version':'4.0.1','previous_version':'4.0.0','pending_health':False}))
    try:up.stage_update(r,manifest,pub);raise AssertionError('same-version reinstall accepted')
    except RuntimeError as e:assert '降级/重复安装' in str(e)

# Schema-2 payloads must carry a valid internal file manifest; a tampered controlled file is rejected.
with tempfile.TemporaryDirectory() as td:
    r=Path(td);(r/'versions'/'4.2.0').mkdir(parents=True);(r/'staging').mkdir();(r/'current.json').write_text(json.dumps({'active_version':'4.2.0','previous_version':'4.1.0','pending_health':False}))
    src=Path(td)/'payload';(src/'stock_ai').mkdir(parents=True)
    (src/'VERSION').write_text('4.3.0');(src/'requirements.txt').write_text('');(src/'app.py').write_text('ok');(src/'stock_ai'/'__init__.py').write_text('')
    files={n:up.sha256(src/n) for n in ['VERSION','requirements.txt','app.py','stock_ai/__init__.py']}
    (src/'PACKAGE_MANIFEST.json').write_text(json.dumps({'file_count':len(files),'files':files}))
    z=Path(td)/'payload.zip'
    with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as q:
        for f in src.rglob('*'):
            if f.is_file():q.write(f,f.relative_to(src))
    m={'manifest_schema_version':2,'version':'4.3.0','package_url':'file://'+str(z),'size':z.stat().st_size,'sha256':up.sha256(z),'signature':'ignored'}
    with patch.object(up,'verify_manifest_signature',return_value=True):
        assert up.stage_update(r,m,pub)=='4.3.0'
    # Rebuild a payload whose internal manifest no longer matches app.py.
    shutil.rmtree(r/'versions'/'4.3.0');(r/'current.json').write_text(json.dumps({'active_version':'4.2.0','previous_version':'4.1.0','pending_health':False}))
    (src/'app.py').write_text('tampered')
    z2=Path(td)/'tampered.zip'
    with zipfile.ZipFile(z2,'w',zipfile.ZIP_DEFLATED) as q:
        for f in src.rglob('*'):
            if f.is_file():q.write(f,f.relative_to(src))
    m2=dict(m,package_url='file://'+str(z2),size=z2.stat().st_size,sha256=up.sha256(z2))
    with patch.object(up,'verify_manifest_signature',return_value=True):
        try:up.stage_update(r,m2,pub);raise AssertionError('internal manifest tamper accepted')
        except ValueError as e:assert 'internal manifest hash mismatch' in str(e)

# Disk-space preflight fails closed before installation.
with tempfile.TemporaryDirectory() as td:
    r=Path(td);r.mkdir(exist_ok=True)
    fake=type('DU',(),{'free':1})()
    with patch.object(up.shutil,'disk_usage',return_value=fake):
        try:up._ensure_free_space(r,100_000_000);raise AssertionError('low disk accepted')
        except RuntimeError as e:assert '磁盘空间不足' in str(e)

print('UPDATER TRANSACTION/SECURITY/ROLLBACK TEST PASS')
