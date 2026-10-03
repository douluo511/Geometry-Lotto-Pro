from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True)
    parser.add_argument('--final-exe', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    exe, final_exe = Path(args.exe).resolve(), Path(args.final_exe).resolve()
    before = sha256(exe)
    proof = {'status': 'NOT VERIFIED'}
    child_pid = None
    exit_code = None
    try:
        with tempfile.TemporaryDirectory(prefix='psychology-updater-exact-') as td:
            evidence = Path(td) / 'self_test.json'
            proc = subprocess.Popen([str(exe), '--self-test', '--evidence-file', str(evidence)],
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
            child_pid = proc.pid
            try:
                exit_code = proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise RuntimeError('independent Updater self-test timed out')
            proof = json.loads(evidence.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        proof = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'}
    after, final_hash = sha256(exe), sha256(final_exe)
    windows = os.name == 'nt'
    process_ok = (exit_code == 0 and proof.get('status') == 'PASS'
                  and isinstance(proof.get('process_id'), int) and proof['process_id'] > 0
                  and proof['process_id'] != os.getpid() and child_pid != os.getpid())
    gates = {
        'updater_process': 'PASS' if process_ok else 'FAIL',
        'updater_exact_exe': 'PASS' if windows and before and process_ok else 'FAIL',
        'updater_same_hash': 'PASS' if before and before == after == final_hash else 'FAIL',
    }
    report = {'schema': 'psychology-updater-exact-candidate-v1', 'status': 'PASS' if all(v == 'PASS' for v in gates.values()) else 'FAIL',
              'github_sha': os.environ.get('PSYCHOLOGY_SOURCE_SHA') or os.environ.get('GITHUB_SHA'),
              'exe_sha256': before, 'exe_sha256_after': after, 'final_exe_sha256': final_hash,
              'independent_child_pid': child_pid, 'exit_code': exit_code, 'self_test': proof, 'gates': gates}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
