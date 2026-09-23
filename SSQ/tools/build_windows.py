from __future__ import annotations
import hashlib, json, os, subprocess, sys, time
from pathlib import Path

if os.name != 'nt':
    raise SystemExit('Native Windows build required')
if sys.version_info[:2] != (3, 11):
    raise SystemExit(f'Python 3.11 required, got {sys.version}')

root = Path(__file__).resolve().parents[1]
project = root / 'SSQ'
dist = root / 'dist'
evidence = root / 'evidence' / 'SSQ'
dist.mkdir(exist_ok=True)
evidence.mkdir(parents=True, exist_ok=True)
name = 'Geometry_Lotto_Pro_SSQ_Windows_Verified'

cmd = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', name,
    '--paths', str(project),
    '--add-data', str(project / 'resources') + ';resources',
    '--collect-all', 'certifi',
    '--hidden-import', 'glp.gui', '--hidden-import', 'glp.service', '--hidden-import', 'glp.evidence',
    '--distpath', str(dist),
    str(root / 'launcher.py'),
]
subprocess.run(cmd, cwd=root, check=True)
exe = dist / f'{name}.exe'
exe_hash = hashlib.sha256(exe.read_bytes()).hexdigest()

checks = [
    'self',
    'integrity-tamper',
    'offline-failclosed',
    'update',
    'corrupt-repair',
    'science',
    'random-world-101',
    'random-world-202',
    'random-world-303',
    'predict',
    'audit',
    'gui',
]
report = {
    'schema': 'ssq-windows-exact-exe-acceptance-v2',
    'artifact': exe.name,
    'sha256': exe_hash,
    'runner_os': os.environ.get('RUNNER_OS'),
    'runner_name': os.environ.get('RUNNER_NAME'),
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
    except Exception as exc:
        report['checks'][check] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}', 'exe_hash_matches': False}

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
    }
except Exception as exc:
    report['checks']['unicode-path-no-python-path'] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}', 'exe_hash_matches': False}

# Default user path: the exact same EXE must actually stay alive as a native GUI app.
# The dedicated 'gui' acceptance above separately validates window/control creation
# and real WM_COMMAND -> backend routing inside these exact packaged bytes.
gui_proc = None
try:
    gui_proc = subprocess.Popen([str(exe)])
    time.sleep(7)
    alive = gui_proc.poll() is None
    report['checks']['default-gui-launch'] = {
        'exit_code': 0 if alive else int(gui_proc.returncode or 1),
        'status': 'PASS' if alive else 'FAIL',
        'exe_hash_matches': (hashlib.sha256(exe.read_bytes()).hexdigest() == exe_hash),
        'detail': 'exact EXE remained alive for 7 seconds under default no-argument GUI launch' if alive else 'exact EXE exited before GUI smoke window',
    }
finally:
    if gui_proc is not None and gui_proc.poll() is None:
        subprocess.run(['taskkill', '/PID', str(gui_proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

hard_fail = [k for k,v in report['checks'].items() if v.get('status') != 'PASS' or v.get('exit_code') != 0 or not v.get('exe_hash_matches')]
report['hard_failures'] = hard_fail
report['hard_fail_count'] = len(hard_fail)
report['windows_exact_exe_acceptance'] = 'PASS' if not hard_fail else 'FAIL'
report['final_release_gate'] = 'PASS' if not hard_fail else 'FAIL'
(evidence / 'WINDOWS_EXACT_EXE_ACCEPTANCE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
(evidence / 'SHA256SUMS.txt').write_text(f'{exe_hash}  {exe.name}\n', encoding='utf-8')
if hard_fail:
    raise SystemExit('Windows exact-EXE acceptance failed: ' + ', '.join(hard_fail))
