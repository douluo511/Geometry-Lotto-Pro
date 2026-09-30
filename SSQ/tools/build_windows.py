from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

if os.name != 'nt':
    raise SystemExit('Native Windows build required')
if sys.version_info[:2] != (3, 11):
    raise SystemExit(f'Python 3.11 required, got {sys.version}')

root = Path(__file__).resolve().parents[1]
project = root / 'SSQ'
dist = root / 'dist'
evidence = root / 'evidence' / 'SSQ'
bundle = root / 'updater_bundle'
dist.mkdir(exist_ok=True)
evidence.mkdir(parents=True, exist_ok=True)
name = 'Geometry_Lotto_Pro_SSQ_Windows_Verified'
updater_name = 'Geometry_Lotto_Pro_SSQ_Updater'


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


# 1) Build the independent updater first. It owns Update/Repair execution but
# reuses the same audited Service/NetClient/Storage path; it has no network bypass.
updater_cmd = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', updater_name,
    '--paths', str(project),
    '--add-data', str(project / 'resources') + ';resources',
    '--collect-all', 'certifi',
    '--hidden-import', 'glp.service', '--hidden-import', 'glp.storage', '--hidden-import', 'glp.sources',
    '--distpath', str(dist),
    str(root / 'updater.py'),
]
subprocess.run(updater_cmd, cwd=root, check=True)
updater_exe = dist / f'{updater_name}.exe'
updater_hash = file_sha256(updater_exe)

if bundle.exists():
    shutil.rmtree(bundle)
bundle.mkdir(parents=True)
bundled_updater = bundle / updater_exe.name
bundled_updater.write_bytes(updater_exe.read_bytes())
updater_manifest = {
    'schema': 'ssq-updater-bundle-v1',
    'filename': updater_exe.name,
    'sha256': updater_hash,
    'bytes': updater_exe.stat().st_size,
    'github_sha': os.environ.get('GITHUB_SHA'),
    'github_run_id': os.environ.get('GITHUB_RUN_ID'),
}
(bundle / 'updater_manifest.json').write_text(
    json.dumps(updater_manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
)

updater_acceptance = {
    'schema': 'ssq-updater-exact-exe-acceptance-v1',
    'artifact': updater_exe.name,
    'sha256': updater_hash,
    'checks': {},
}


def run_updater(mode: str, data_root: Path, result_path: Path, timeout: int = 1800) -> dict:
    env = os.environ.copy()
    env['GLP_DATA_DIR'] = str(data_root.resolve())
    env['GLP_UPDATER_PARENT_PID'] = str(os.getpid())
    result_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(updater_exe), '--mode', mode, '--result-file', str(result_path)],
        env=env, timeout=timeout,
    )
    content = json.loads(result_path.read_text(encoding='utf-8-sig')) if result_path.exists() else {}
    ok = bool(
        proc.returncode == 0
        and content.get('status') == 'PASS'
        and content.get('mode') == mode
        and content.get('updater_exe_sha256') == updater_hash
        and content.get('parent_pid_match') is True
        and int(content.get('pid') or 0) != os.getpid()
        and int(content.get('parent_pid') or 0) == os.getpid()
    )
    updater_acceptance['checks'][mode] = {
        'status': 'PASS' if ok else 'FAIL',
        'exit_code': proc.returncode,
        'hash_matches': content.get('updater_exe_sha256') == updater_hash,
        'separate_process': int(content.get('pid') or 0) != os.getpid(),
        'parent_pid_match': content.get('parent_pid_match') is True,
        'result_file': str(result_path),
    }
    print('UPDATER_EXACT_CHECK=' + mode + ' ' + json.dumps(content, ensure_ascii=True), flush=True)
    if not ok:
        raise RuntimeError(f'Updater exact check failed: {mode}')
    return content


# Exact updater self-test.
run_updater(
    'self-test',
    evidence / 'updater-self-data',
    evidence / 'updater-self-test.json',
    timeout=900,
)

# Exact updater software-artifact transaction self-test. This proves the updater
# binary itself can stage, replace, preserve previous bytes and roll back an
# injected post-replace validation failure. It is not a substitute for a real
# release-host network update.
software_self = run_updater(
    'software-self-test',
    evidence / 'updater-software-self-data',
    evidence / 'updater-software-self-test.json',
    timeout=900,
)
software_checks = (software_self.get('service_result') or {}).get('checks') or {}
if not software_checks or not all(bool(v) for v in software_checks.values()):
    updater_acceptance['checks']['software-self-test']['status'] = 'FAIL'
    raise RuntimeError('Updater software atomic/rollback self-test did not fully PASS')

# Failure injection must be fail-closed and preserve canonical bytes.
offline = run_updater(
    'offline-failclosed',
    evidence / 'updater-offline-data',
    evidence / 'updater-offline-failclosed.json',
    timeout=900,
)
offline_result = offline.get('service_result') or {}
if not (offline_result.get('update_rejected') is True and offline_result.get('history_unchanged') is True):
    updater_acceptance['checks']['offline-failclosed']['status'] = 'FAIL'
    raise RuntimeError('Updater offline rollback evidence is incomplete')

# Real official network through the exact updater EXE.
live_root = evidence / 'updater-live-data'
live = run_updater('update', live_root, evidence / 'updater-real-network.json', timeout=1800)
live_result = live.get('service_result') or {}
if not (
    live_result.get('crosscheck_status') == 'PASS'
    and isinstance(live_result.get('persisted_integrity'), dict)
    and live_result['persisted_integrity'].get('ok') is True
):
    updater_acceptance['checks']['update']['status'] = 'FAIL'
    raise RuntimeError('Updater real-network persisted integrity did not PASS')

# Exact updater Repair must recover a deliberately corrupted accepted dataset.
repair_root = evidence / 'updater-repair-data'
if repair_root.exists():
    shutil.rmtree(repair_root)
shutil.copytree(live_root, repair_root)
history = repair_root / 'canonical_history.json'
if not history.is_file():
    raise RuntimeError('Updater repair fixture has no canonical history')
raw = history.read_bytes()
if len(raw) < 32:
    raise RuntimeError('Updater repair fixture too small')
history.write_bytes(raw[:-1] + (b'0' if raw[-1:] != b'0' else b'1'))
repair = run_updater('repair', repair_root, evidence / 'updater-corrupt-repair.json', timeout=1800)
repair_result = repair.get('service_result') or {}
repair_integrity = repair_result.get('after') if repair_result.get('repaired') else repair_result.get('integrity')
if not (
    repair_result.get('status') == 'PASS'
    and isinstance(repair_integrity, dict)
    and repair_integrity.get('ok') is True
):
    updater_acceptance['checks']['repair']['status'] = 'FAIL'
    raise RuntimeError('Updater corrupt repair did not restore integrity')

updater_hard_fail = [
    key for key, value in updater_acceptance['checks'].items()
    if value.get('status') != 'PASS'
]
updater_acceptance['hard_failures'] = updater_hard_fail
updater_acceptance['hard_fail_count'] = len(updater_hard_fail)
updater_acceptance['updater_exact_exe'] = 'PASS' if not updater_hard_fail else 'FAIL'
# A shared migration repository has no accepted independent release host/artifact.
# Keep this non-PASS until the updater performs a real HTTPS manifest+artifact
# transaction against the product's independent repository and binds the exact
# installed main-EXE hash to that run.
updater_acceptance['software_release_network'] = 'PENDING'
updater_acceptance['software_release_reason'] = 'independent release repository/artifact not yet available'
updater_acceptance['updater_release_gate'] = 'PENDING'
(evidence / 'UPDATER_EXACT_EXE_ACCEPTANCE.json').write_text(
    json.dumps(updater_acceptance, ensure_ascii=False, indent=2), encoding='utf-8'
)
(evidence / 'UPDATER_SHA256SUMS.txt').write_text(
    f'{updater_hash}  {updater_exe.name}\n', encoding='utf-8'
)
if updater_hard_fail:
    raise SystemExit('Updater exact-EXE acceptance failed: ' + ', '.join(updater_hard_fail))

# 2) Build the single distributable main EXE with the already accepted updater
# bytes + hash manifest embedded as data.
cmd = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', name,
    '--paths', str(project),
    '--add-data', str(project / 'resources') + ';resources',
    '--add-data', str(bundle) + ';updater_bundle',
    '--collect-all', 'certifi',
    '--hidden-import', 'glp.gui', '--hidden-import', 'glp.service', '--hidden-import', 'glp.evidence',
    '--hidden-import', 'glp.updater_client',
    '--distpath', str(dist),
    str(root / 'launcher.py'),
]
subprocess.run(cmd, cwd=root, check=True)
exe = dist / f'{name}.exe'
exe_hash = file_sha256(exe)

checks = [
    'self',
    'integrity-tamper',
    'offline-failclosed',
    'corrupt-repair',
    'update',
    'science',
    'random-world-101',
    'random-world-202',
    'random-world-303',
    'predict',
    'audit',
    'gui',
]
report = {
    'schema': 'ssq-windows-exact-exe-acceptance-v3',
    'artifact': exe.name,
    'sha256': exe_hash,
    'updater': {
        'artifact': updater_exe.name,
        'sha256': updater_hash,
        'manifest': updater_manifest,
        'acceptance_report': 'UPDATER_EXACT_EXE_ACCEPTANCE.json',
        'status': updater_acceptance['updater_exact_exe'],
        'software_release_network': updater_acceptance['software_release_network'],
        'release_gate': updater_acceptance['updater_release_gate'],
    },
    'runner_os': os.environ.get('RUNNER_OS'),
    'runner_name': os.environ.get('RUNNER_NAME'),
    'github_sha': os.environ.get('GITHUB_SHA'),
    'github_run_id': os.environ.get('GITHUB_RUN_ID'),
    'python': sys.version,
    'checks': {},
    'final_release_gate': 'PENDING',
}

for check in checks:
    result_path = evidence / f'{check}.json'
    timeout = 2400 if check in {'science','random-world-101','random-world-202','random-world-303','predict','audit'} else 900
    try:
        proc = subprocess.run([str(exe), '--check', check, '--result-file', str(result_path)], timeout=timeout)
        content = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
        report['checks'][check] = {
            'exit_code': proc.returncode,
            'status': content.get('status', 'UNAVAILABLE'),
            'exe_hash_matches': content.get('exe_sha256') == exe_hash,
            'game': content.get('game'),
            'version': content.get('version'),
        }
        if check == 'self':
            bundle_check = (content.get('result') or {}).get('updater_bundle') or {}
            report['checks'][check]['updater_bundle_integrity'] = bundle_check.get('status') == 'PASS'
            report['checks'][check]['embedded_updater_sha256'] = bundle_check.get('sha256')
        print('EXACT_EXE_CHECK=' + check + ' ' + json.dumps(content, ensure_ascii=True), flush=True)
    except Exception as exc:
        report['checks'][check] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}', 'exe_hash_matches': False}
        print('EXACT_EXE_CHECK=' + check + ' WRAPPER_ERROR=' + f'{type(exc).__name__}: {exc}', flush=True)

# Run exact same EXE from a Chinese path with a deliberately restricted PATH.
unicode_dir = root / 'evidence' / 'SSQ' / '中文路径验收'
unicode_dir.mkdir(parents=True, exist_ok=True)
unicode_exe = unicode_dir / exe.name
unicode_exe.write_bytes(exe.read_bytes())
unicode_result = unicode_dir / 'self.json'
env = os.environ.copy()
env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
try:
    proc = subprocess.run([str(unicode_exe), '--check', 'self', '--result-file', str(unicode_result)], env=env, timeout=900)
    content = json.loads(unicode_result.read_text(encoding='utf-8')) if unicode_result.exists() else {}
    report['checks']['unicode-path-no-python-path'] = {
        'exit_code': proc.returncode,
        'status': content.get('status', 'UNAVAILABLE'),
        'exe_hash_matches': content.get('exe_sha256') == exe_hash,
        'updater_bundle_integrity': ((content.get('result') or {}).get('updater_bundle') or {}).get('status') == 'PASS',
    }
except Exception as exc:
    report['checks']['unicode-path-no-python-path'] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}', 'exe_hash_matches': False}

# Default user path: exact main EXE must stay alive as native GUI.
gui_proc = None
try:
    gui_proc = subprocess.Popen([str(exe)])
    time.sleep(7)
    alive = gui_proc.poll() is None
    report['checks']['default-gui-launch'] = {
        'exit_code': 0 if alive else int(gui_proc.returncode or 1),
        'status': 'PASS' if alive else 'FAIL',
        'exe_hash_matches': (file_sha256(exe) == exe_hash),
        'detail': 'exact EXE remained alive for 7 seconds under default no-argument GUI launch' if alive else 'exact EXE exited before GUI smoke window',
    }
finally:
    if gui_proc is not None and gui_proc.poll() is None:
        subprocess.run(['taskkill', '/PID', str(gui_proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

hard_fail = []
for key, value in report['checks'].items():
    if value.get('status') != 'PASS' or value.get('exit_code') != 0 or not value.get('exe_hash_matches'):
        hard_fail.append(key)
    if key in {'self', 'unicode-path-no-python-path'} and value.get('updater_bundle_integrity') is not True:
        hard_fail.append(key + ':updater_bundle')
if updater_acceptance['updater_exact_exe'] != 'PASS':
    hard_fail.append('updater_exact_exe')

report['hard_failures'] = sorted(set(hard_fail))
report['hard_fail_count'] = len(report['hard_failures'])
report['windows_exact_exe_acceptance'] = 'PASS' if not report['hard_failures'] else 'FAIL'
report['final_release_gate'] = 'PENDING' if not report['hard_failures'] else 'FAIL'
(evidence / 'WINDOWS_EXACT_EXE_ACCEPTANCE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
(evidence / 'SHA256SUMS.txt').write_text(f'{exe_hash}  {exe.name}\n', encoding='utf-8')
if report['hard_failures']:
    raise SystemExit('Windows exact-EXE acceptance failed: ' + ', '.join(report['hard_failures']))
