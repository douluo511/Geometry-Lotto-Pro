"""Verify the immutable import and the complete offline recovery denominator."""
from __future__ import annotations
import argparse
import compileall
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ACCEPTANCE = ('distribution_layout_test.py', 'data_separation_test.py',
 'updater_security_test.py', 'file_uri_windows_test.py', 'launcher_rollback_test.py',
 'schema_rollback_compat_test.py', 'install_failfast_test.py',
 'deterministic_build_test.py', 'package_manifest_test.py')
ACTIVE = ('app_static_test.py', 'audit_test.py', 'backtest_test.py',
 'config_migration_test.py', 'cost_valuation_decision_test.py', 'entrypoints_test.py',
 'freshness_gate_test.py', 'integration_pipeline_test.py', 'legacy_migration_test.py',
 'lock_test.py', 'logging_lifecycle_test.py', 'maintenance_test.py', 'model_mode_test.py',
 'model_stack_test.py', 'network_config_test.py', 'package_manifest_test.py',
 'prediction_chain_test.py', 'provider_normalization_test.py', 'rnd_test.py',
 'self_test.py', 'storage_test.py', 'universe_parser_test.py')

def verify_import(repo: Path, inventory: dict) -> dict:
    entries = inventory['files']
    if len(entries) != 187 or len({x['path'] for x in entries}) != 187:
        raise ValueError('immutable import denominator must be 187 unique files')
    prefix = 'StockAIPro/recovered_exact/Stock_AI_Pro/'
    if any(not x['path'].startswith(prefix) for x in entries):
        raise ValueError('inventory path outside immutable archive subtree')
    expected = {x['path'] for x in entries}
    actual = {p.relative_to(repo).as_posix() for p in (repo / prefix).rglob('*') if p.is_file()}
    if actual != expected:
        raise ValueError(f'import file inventory mismatch: missing={expected-actual}, extra={actual-expected}')
    for entry in entries:
        path = (repo / entry['path']).resolve()
        path.relative_to((repo / prefix).resolve())
        raw = path.read_bytes()
        git_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if (len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']
                or git_blob != entry['git_blob']):
            raise ValueError(f'immutable byte mismatch: {entry["path"]}')
    return {'status': 'PASS', 'verified_files': 187, 'archive_sha256': inventory['archive_sha256']}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo-root', default='..')
    ap.add_argument('--output', default='source_recovery_evidence.json')
    args = ap.parse_args()
    repo = Path(args.repo_root).resolve()
    evidence = {'schema': 'stock-source-recovery-v1', 'status': 'FAIL',
        'scope': 'immutable import and offline staging regression only',
        'real_network': 'NOT VERIFIED', 'windows_desktop_exe': 'NOT VERIFIED',
        'physical_gui': 'NOT VERIFIED', 'same_hash': 'NOT VERIFIED', 'final_gate': 'FAIL',
        'github_run_id': os.environ.get('GITHUB_RUN_ID'),
        'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    try:
        head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip()
        expected_head = os.environ.get('STOCK_SOURCE_SHA')
        if not expected_head or head != expected_head:
            raise ValueError(f'exact checkout mismatch: expected={expected_head}, actual={head}')
        evidence['head_sha'] = head
        inventory = json.loads((repo / 'StockAIPro/recovered_exact/IMPORT_BYTE_MANIFEST.json').read_text(encoding='utf-8'))
        evidence['immutable_import'] = verify_import(repo, inventory)
        stage = repo / 'StockAIPro/staging/Stock_AI_Pro'
        tests = [stage/'acceptance_tests'/name for name in ACCEPTANCE]
        tests += [stage/'versions/4.3.0/tests'/name for name in ACTIVE]
        tests += [stage/'versions/4.3.0/healthcheck.py']
        if len(tests) != 32 or any(not p.is_file() for p in tests):
            raise ValueError('the frozen 32 offline subprocess gates must all exist')
        if {p.name for p in (stage/'versions/4.3.0/tests').glob('*.py')} != set(ACTIVE):
            raise ValueError('active offline test inventory changed without denominator review')
        if not compileall.compile_dir(str(stage), quiet=1):
            raise ValueError('staging compile failed')
        evidence['static_compile'] = 'PASS'
        result = subprocess.run([sys.executable, str(stage/'run_full_check.py'), '--offline'],
            cwd=stage, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
        log = result.stdout + '\nSTDERR\n' + result.stderr
        Path(args.output).with_suffix('.log').write_text(log, encoding='utf-8')
        count = sum(line.startswith('> ') for line in result.stdout.splitlines())
        evidence['offline_gate_count'] = count
        evidence['offline_exit_code'] = result.returncode
        if result.returncode != 0 or count != 32 or 'ALL ENGINEERING ACCEPTANCE: PASS' not in result.stdout:
            raise ValueError('offline staging suite did not execute and pass all 32 gates')
        evidence['offline_regression'] = 'PASS'
        evidence['immutable_import_after_tests'] = verify_import(repo, inventory)
        evidence['status'] = 'PASS'
    except Exception as exc:
        evidence['error'] = f'{type(exc).__name__}: {exc}'
    Path(args.output).write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence['status'] == 'PASS' else 2

if __name__ == '__main__':
    raise SystemExit(main())
