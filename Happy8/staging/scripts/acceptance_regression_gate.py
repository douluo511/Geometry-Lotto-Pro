from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent
STAGING = SCRIPTS.parent
REPO = STAGING.parents[1]
WORKFLOW = REPO / '.github/workflows/happy8-staging-recovery.yml'


def workflow_powershell_blocks(workflow_path: Path) -> list[dict]:
    workflow = yaml.safe_load(workflow_path.read_text(encoding='utf-8-sig'))
    workflow_shell = workflow.get('defaults', {}).get('run', {}).get('shell')
    blocks = []
    for job_name, job in workflow['jobs'].items():
        job_shell = job.get('defaults', {}).get('run', {}).get('shell', workflow_shell)
        runner = str(job.get('runs-on') or '')
        for step_no, step in enumerate(job.get('steps', []), 1):
            if 'run' not in step:
                continue
            shell = step.get('shell', job_shell)
            if shell is None and 'windows' in runner.lower():
                shell = 'pwsh'
            if shell not in ('pwsh', 'powershell'):
                raise RuntimeError(f'unverified workflow shell: {job_name}/{step_no}: {shell}')
            # Actions interpolates contexts before launching PowerShell. Replace
            # only those template spans, then parse the entire resulting block.
            code = re.sub(r'\$\{\{.*?\}\}', 'context_value', str(step['run']), flags=re.DOTALL)
            blocks.append({'label': f'workflow:{job_name}:{step_no}:{step.get("id", step.get("name", "run"))}', 'code': code})
    if not blocks:
        raise RuntimeError('workflow has no PowerShell run blocks')
    return blocks


def run_cp1252_validator(temp_dir: Path) -> dict:
    output = temp_dir / 'real-release-blocked.json'
    environment = dict(os.environ)
    environment['PYTHONIOENCODING'] = 'cp1252:strict'
    environment['PYTHONUTF8'] = '0'
    command = [
        sys.executable, str(SCRIPTS / 'real_release_evidence.py'),
        '--repository', 'douluo511/Geometry-Lotto-Pro',
        '--source-sha', 'a' * 40, '--run-id', 'regression', '--run-attempt', '1',
        '--output', str(output),
    ]
    completed = subprocess.run(command, cwd=STAGING, env=environment, capture_output=True, timeout=30)
    file_report = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
    try:
        console_report = json.loads(completed.stdout.decode('cp1252'))
    except (UnicodeError, ValueError):
        console_report = {}
    ok = (
        completed.returncode == 0 and not completed.stderr
        and file_report.get('status') == 'BLOCKED' and console_report == file_report
        and 'N\u2192N+1' in file_report.get('detail', '')
        and '\u2192' in output.read_text(encoding='utf-8')
    )
    return {
        'status': 'PASS' if ok else 'FAIL', 'exit_code': completed.returncode,
        'declared_release_status': file_report.get('status'),
        'stdout': completed.stdout.decode('cp1252', errors='replace'),
        'stderr': completed.stderr.decode('cp1252', errors='replace'),
        'utf8_output_preserves_arrow': '\u2192' in output.read_text(encoding='utf-8') if output.exists() else False,
    }


def official_release_producer_fixture(temp_dir: Path) -> dict:
    repository = 'fixture-owner/Happy8'
    source_sha = 'a' * 40
    api_root = f'https://api.github.com/repos/{repository}'
    tag = 'v0.2.1'
    responses = []
    assets = []
    hashes = {}
    for index, (key, filename) in enumerate((('main', 'Geometry_Lotto_Pro_Happy8.exe'), ('updater', 'Geometry_Lotto_Pro_Happy8_Updater.exe')), 1):
        body = key + '-official-release-offline-contract-fixture'
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        url = f'https://github.com/{repository}/releases/download/{tag}/{filename}'
        hashes[key] = digest
        assets.append({'id': 1010 + index, 'name': filename, 'size': len(body.encode('utf-8')), 'state': 'uploaded',
                       'digest': 'sha256:' + digest, 'url': f'{api_root}/releases/assets/{1010 + index}', 'browser_download_url': url})
        responses.append({'url': url, 'body': body})
    page = f'https://github.com/{repository}/releases/tag/{tag}'
    release_url = api_root + '/releases/101'
    metadata = {'id': 101, 'url': release_url, 'html_url': page, 'tag_name': tag, 'draft': False,
                'prerelease': False, 'published_at': '2026-10-03T11:00:00Z', 'assets': assets}
    responses.append({'url': release_url, 'body': json.dumps(metadata)})
    responses.append({'url': api_root + '/commits/' + tag,
                      'body': json.dumps({'sha': source_sha, 'html_url': f'https://github.com/{repository}/commit/{source_sha}'})})
    return {'repository': repository, 'source_sha': source_sha, 'main_sha256': hashes['main'], 'updater_sha256': hashes['updater'],
            'release_url': page, 'capture_dir': str(temp_dir / 'official-producer-contract'), 'responses': responses}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--powershell', default='pwsh')
    args = parser.parse_args()
    checks = {}
    try:
        powershell = shutil.which(args.powershell)
        if not powershell:
            raise RuntimeError(f'PowerShell is unavailable: {args.powershell}')
        blocks = workflow_powershell_blocks(WORKFLOW)
        release_script = (SCRIPTS / 'real_release_update_acceptance.ps1').read_text(encoding='utf-8-sig')
        for script in sorted(SCRIPTS.glob('*.ps1')):
            blocks.append({'label': 'script:' + script.name, 'code': script.read_text(encoding='utf-8-sig')})
        with tempfile.TemporaryDirectory(prefix='happy8-acceptance-regression-') as td:
            temp_dir = Path(td)
            payload = temp_dir / 'powershell-payload.json'
            payload.write_text(json.dumps({'blocks': blocks, 'release_script': release_script,
                'official_release_fixture': official_release_producer_fixture(temp_dir)}, ensure_ascii=False), encoding='utf-8')
            completed = subprocess.run(
                [powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                 str(SCRIPTS / 'powershell_acceptance_probe.ps1'), '-PayloadPath', str(payload)],
                capture_output=True, timeout=60,
            )
            stdout = completed.stdout.decode('utf-8-sig', errors='replace')
            stderr = completed.stderr.decode('utf-8-sig', errors='replace')
            try:
                probe = json.loads(stdout)
            except ValueError:
                probe = {'status': 'FAIL', 'stdout': stdout}
            checks['native_powershell_parse_and_execution'] = {
                'status': 'PASS' if completed.returncode == 0 and probe.get('status') == 'PASS' else 'FAIL',
                'exit_code': completed.returncode, 'workflow_and_script_block_count': len(blocks),
                'probe': probe, 'stderr': stderr,
            }
            checks['real_release_cli_cp1252'] = run_cp1252_validator(temp_dir)
    except Exception as exc:
        checks['regression_execution'] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'}
    status = 'PASS' if checks and all(check['status'] == 'PASS' for check in checks.values()) else 'FAIL'
    report = {'schema': 'happy8-acceptance-regression-v1', 'status': status, 'checks': checks}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if status == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
