from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from glp import background
from test_background_103_compat import FakeService


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 100:
            raise AssertionError('worker failed to reach a deadline')
        self.now += seconds / 2 if seconds > 0.001 else seconds


class WorkerContinuityTests(unittest.TestCase):
    def run_worker(self, fail_first=False):
        clock = Clock()
        svc = FakeService()
        update = svc.update
        starts = []

        def fresh_update():
            starts.append(clock.now)
            clock.now += 1
            if fail_first and len(starts) == 1:
                raise RuntimeError('first fresh official update failed')
            result = update()
            result['source_receipts'] = [{'fetched_at': f'fresh-call-{len(starts)}'}]
            return result

        svc.update = fresh_update
        with tempfile.TemporaryDirectory() as tmp:
            svc.store.root = Path(tmp)
            with patch.object(background, 'LottoService', return_value=svc), patch.object(background.time, 'monotonic', clock.monotonic), patch.object(background.time, 'sleep', clock.sleep):
                code = background.run_background_worker(interval_seconds=1800, max_cycles=2)
            state = json.loads((Path(tmp) / 'background_status.json').read_text(encoding='utf-8'))
        return code, state, starts, svc

    def test_early_waking_sleep_cannot_shorten_completion_to_next_start(self):
        code, state, starts, svc = self.run_worker()
        self.assertGreaterEqual(starts[1] - (starts[0] + 1), 1800)
        self.assertEqual(code, 0)
        self.assertEqual(state['cycle_count'], 2)
        self.assertEqual([c['sequence'] for c in state['cycles']], [1, 2])
        self.assertEqual(state['clock_origin'], 'worker_monotonic_start')
        self.assertEqual(state['cycles'][0]['result']['freeze_hash'], state['cycles'][1]['result']['freeze_hash'])
        self.assertEqual(state['cycles'][0]['result']['source_receipts'], [{'fetched_at': 'fresh-call-1'}])
        self.assertEqual(state['cycles'][1]['result']['source_receipts'], [{'fetched_at': 'fresh-call-2'}])
        self.assertEqual(svc.predict_calls, 1)
        self.assertEqual(svc.update_calls, 2)

    def test_first_failed_cycle_remains_failed_after_success(self):
        code, state, starts, svc = self.run_worker(fail_first=True)
        self.assertEqual(code, 2)
        self.assertEqual(state['status'], 'FAIL')
        self.assertEqual([c['status'] for c in state['cycles']], ['FAIL', 'PASS'])
        self.assertIn('first fresh official update failed', state['cycles'][0]['error']['message'])


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fixture():
    # Literal, independently hand-timed worker and observer clocks have different origins.
    identity = dict(launch_session='session-new', acceptance_nonce='nonce-new', github_sha='a' * 40,
                    github_run_id='123', github_run_attempt='2', exe_sha256='b' * 64,
                    exe_path='C:\\dist\\app.exe')
    request = dict(schema='dlt-background-acceptance-request-v2', **identity)
    result = dict(status='PASS', network_gate='PASS', crosscheck_status='PASS', prediction_id='freeze-one',
                  freeze_hash='f' * 64, target_issue='26114', research_dan_front=[1, 2], research_dan_back=[1],
                  production_edge_state='NO_EDGE', production_dan_state='NULL_DAN', source_receipts=[])
    cycles = []
    for sequence, start, end in [(1, 0.5, 5.0), (2, 1805.0, 1810.0)]:
        cycles.append(dict(sequence=sequence, launch_session='session-new', acceptance_nonce='nonce-new',
                           started_offset_seconds=start, finished_offset_seconds=end, status='PASS',
                           result=result.copy(), error=None, result_sha256=digest(result)))
    launch = dict(schema='dlt-background-launch-v2', status='PASS', child_pid=30, parent_pid=20, shell=False, interval_seconds=1800,
                  production_poll_seconds=1800, max_cycles=2, wait_parent_exit=True, **identity)
    worker = dict(schema='dlt-background-worker-v2', failed_cycle_count=0, first_error=None, status='PASS', pid=31, cycle_count=2, worker_exit='MAX_CYCLES_REACHED', cycles=cycles,
                  clock_origin='worker_monotonic_start', interval_seconds=1800, production_poll_seconds=1800,
                  parent_pid=20, parent_exit_observed=True, startup_mode='manual_app_launch_required_after_login',
                  autostart_registered=False, **identity)
    def proc(pid, parent, creation):
        return dict(pid=pid, parent_pid=parent, creation_time=creation, exe_path=identity['exe_path'], exe_sha256=identity['exe_sha256'])
    processes = [proc(10, 1, '2026-10-27T00:00:00.100Z'), proc(20, 10, '2026-10-27T00:00:00.200Z'),
                 proc(30, 20, '2026-10-27T00:00:00.300Z'), proc(31, 30, '2026-10-27T00:00:00.400Z')]
    samples = [dict(offset_seconds=1.0, processes=copy.deepcopy(processes)),
               dict(offset_seconds=2.0, processes=copy.deepcopy(processes[2:])),
               dict(offset_seconds=1802.0, processes=copy.deepcopy(processes[2:]))]
    # Bounded sample gaps prove continuous observations, rather than two uncorrelated sightings.
    for second in range(3, 1802):
        samples.insert(-1, dict(offset_seconds=float(second), processes=copy.deepcopy(processes[2:])))
    observer = dict(clock_origin='observer_stopwatch_start', launcher_pid=10, launcher_exit_code=0,
                    launcher_exit_offset_seconds=1.5, launch_started_at='2026-10-27T00:00:00Z',
                    elapsed_seconds=1804.0, max_sample_gap_seconds=2.0, samples=samples,
                    final_status_observed_offset_seconds=1803.0)
    report = dict(schema='dlt-background-acceptance-v2', status='PASS', **identity, launch=launch,
                  worker_status=worker, observer=observer, exe_sha256_before='b' * 64, exe_sha256_after='b' * 64,
                  errors=[])
    return request, report


class AcceptanceVerifierCLITests(unittest.TestCase):
    def verify(self, request, report, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'request.json').write_text(json.dumps(request), encoding='utf-8')
            (root / 'report.json').write_text(json.dumps(report), encoding='utf-8')
            expected = dict(sha='a' * 40, run_id='123', run_attempt='2', exe_sha256='b' * 64, exe_path='C:\\dist\\app.exe')
            expected.update(overrides)
            cmd = [sys.executable, str(ROOT / 'scripts' / 'verify_background_acceptance.py'), '--report', str(root / 'report.json'), '--request', str(root / 'request.json')]
            for key, value in expected.items():
                cmd += ['--' + key.replace('_', '-'), value]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        return run

    def test_accepts_two_fresh_successes_with_native_bootloader_payload_separation(self):
        run = self.verify(*fixture())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'PASS')

    def test_rejects_launcher_or_parent_payload_observed_after_claimed_exit(self):
        # A stale claimed exit must not survive contradictory external liveness,
        # even if the detached worker's independent full1800 span remains valid.
        for pid in (10, 20):
            for offset in (2.0, 1802.0):
                with self.subTest(pid=pid, offset=offset):
                    request, report = fixture()
                    observer = report['observer']
                    process = next(p for p in observer['samples'][0]['processes'] if p['pid'] == pid)
                    sample = next(s for s in observer['samples'] if s['offset_seconds'] == offset)
                    sample['processes'].append(copy.deepcopy(process))
                    run = self.verify(request, report)
                    print('LAUNCHER_EXIT_TRACE ' + json.dumps(dict(pid=pid, offset=offset,
                          claimed_exit=observer['launcher_exit_offset_seconds'], exit=run.returncode,
                          stdout=run.stdout.strip(), stderr=run.stderr.strip())))
                    self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                    verdict = json.loads(run.stdout)
                    self.assertEqual(verdict['status'], 'FAIL')
                    self.assertIn('launcher lineage observed after exit', verdict['errors'])

    def test_rejects_adversarial_evidence_with_structured_errors(self):
        cases = [
            ('historical 38-second v1', lambda q, r: r.update(schema='dlt-background-acceptance-v1')),
            ('boolean-only pass', lambda q, r: r.clear() or r.update(status='PASS', checks={'all': True})),
            ('1799.999 wait', lambda q, r: r['worker_status']['cycles'][1].update(started_offset_seconds=1804.999)),
            ('short external span', lambda q, r: r['observer']['samples'].__setitem__(-1, dict(offset_seconds=1801.999, processes=r['observer']['samples'][-1]['processes']))),
            ('first failed then success', lambda q, r: r['worker_status']['cycles'][0].update(status='FAIL', error={'message': 'network failed'})),
            ('nonfinite worker time', lambda q, r: r['worker_status']['cycles'][0].update(finished_offset_seconds=float('nan'))),
            ('regressing worker time', lambda q, r: r['worker_status']['cycles'][0].update(finished_offset_seconds=0.1)),
            ('nonce replay', lambda q, r: r.update(acceptance_nonce='old-nonce')),
            ('same-attempt old report', lambda q, r: q.update(acceptance_nonce='newer-nonce', launch_session='newer-session')),
            ('empty expected nonce', lambda q, r: q.update(acceptance_nonce='')),
            ('cycle nonce replay', lambda q, r: r['worker_status']['cycles'][0].update(acceptance_nonce='old-nonce')),
            ('sequence replay', lambda q, r: r['worker_status']['cycles'][1].update(sequence=1)),
            ('wrong sha', lambda q, r: r.update(github_sha='c' * 40)),
            ('wrong run', lambda q, r: r.update(github_run_id='122')),
            ('wrong attempt', lambda q, r: r.update(github_run_attempt='1')),
            ('changed exe', lambda q, r: r.update(exe_sha256_after='c' * 64)),
            ('pid reuse', lambda q, r: r['observer']['samples'][-1]['processes'][-1].update(creation_time='2026-10-27T00:25:00Z')),
            ('replacement worker', lambda q, r: r['observer']['samples'][-1]['processes'][-1].update(pid=32)),
            ('missing lineage', lambda q, r: r['observer']['samples'][0]['processes'][2].update(parent_pid=99)),
            ('stale creation', lambda q, r: r['observer']['samples'][0]['processes'][0].update(creation_time='2026-10-26T00:00:00Z')),
            ('wrong digest', lambda q, r: r['worker_status']['cycles'][0].update(result_sha256='0' * 64)),
            ('nonfinite observer', lambda q, r: r['observer'].update(elapsed_seconds=float('inf'))),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                request, report = fixture()
                mutate(request, report)
                run = self.verify(request, report)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertTrue(run.stdout.strip().startswith('{'), 'missing structured rejection: ' + run.stderr)
                self.assertEqual(json.loads(run.stdout)['status'], 'FAIL')
                self.assertTrue(json.loads(run.stdout)['errors'])

    def test_rejects_additional_payload_replacing_a_fully_observed_worker(self):
        request, report = fixture()
        replacement = copy.deepcopy(report['observer']['samples'][-1]['processes'][-1])
        replacement['pid'] = 32
        replacement['creation_time'] = '2026-10-27T00:30:02Z'
        report['observer']['samples'].append(dict(offset_seconds=1803.0, processes=[replacement]))
        report['observer']['final_status_observed_offset_seconds'] = 1804
        report['observer']['elapsed_seconds'] = 1805
        run = self.verify(request, report)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'FAIL')

    def test_rejects_late_first_observation_and_delayed_or_early_final_status(self):
        for label in ('late-first-sample', 'delayed-final-status', 'final-before-last-sample'):
            with self.subTest(label=label):
                request, report = fixture()
                observer = report['observer']
                if label == 'late-first-sample':
                    for sample in observer['samples']:
                        sample['offset_seconds'] += 100
                    observer['elapsed_seconds'] += 100
                    observer['final_status_observed_offset_seconds'] += 100
                elif label == 'delayed-final-status':
                    observer['final_status_observed_offset_seconds'] = 1900
                    observer['elapsed_seconds'] = 1901
                else:
                    observer['final_status_observed_offset_seconds'] = 1801
                run = self.verify(request, report)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertEqual(json.loads(run.stdout)['status'], 'FAIL')

    def test_external_identity_is_required_independently_of_request_and_report(self):
        run = self.verify(*fixture(), run_attempt='3')
        self.assertEqual(run.returncode, 2)
        self.assertTrue(run.stdout.strip().startswith('{'), run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'FAIL')


class WorkerCLIIdentityTests(unittest.TestCase):
    def test_cli_forwards_identity_to_actual_worker_status_and_cycles(self):
        # Keep the real CLI, scheduler, cycle and Freeze behavior. Substitute only
        # the unit-owned service and monotonic/sleep boundary, never live intake.
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + str(ROOT / 'tests')
            env['UNIT_ROOT'] = tmp
            code = """
import json, os, sys
from pathlib import Path
from unittest.mock import patch
import main
from glp import background
from test_background_continuity import Clock
from test_background_103_compat import FakeService
svc=FakeService()
svc.store.root=Path(os.environ['UNIT_ROOT'])
clock=Clock()
sys.argv=['main.py','--background-worker','--background-interval-seconds','1800','--background-max-cycles','2','--background-launch-session','cli-session','--background-acceptance-nonce','cli-nonce']
with patch.object(background, 'LottoService', return_value=svc), patch.object(background.time,'monotonic',clock.monotonic), patch.object(background.time,'sleep',clock.sleep):
    result=main.main()
print((svc.store.root / 'background_status.json').read_text(encoding='utf-8'))
raise SystemExit(result)
"""
            run = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            state = json.loads(run.stdout)
            self.assertEqual(state['launch_session'], 'cli-session')
            self.assertEqual(state['acceptance_nonce'], 'cli-nonce')
            self.assertEqual([c['launch_session'] for c in state['cycles']], ['cli-session', 'cli-session'])
            self.assertEqual([c['acceptance_nonce'] for c in state['cycles']], ['cli-nonce', 'cli-nonce'])


class NativeDriverFailureBoundaryTests(unittest.TestCase):
    def invoke(self, tmp, prior=None):
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell, 'PowerShell is required; absence is not a passing native-script test')
        root = Path(tmp)
        exe = root / 'candidate.exe'
        exe.write_bytes(b'unit fixture only - never executable')
        report = root / 'acceptance.json'
        request = root / 'acceptance.json.request.json'
        if prior == 'request':
            request.write_text('preserved old request', encoding='utf-8')
        if prior == 'report':
            report.write_text('preserved old report', encoding='utf-8')
        driver = str(ROOT / 'scripts' / 'background_acceptance.ps1').replace("'", "''")
        wrapper = root / 'boundary.ps1'
        wrapper.write_text("""
$ErrorActionPreference='Stop'
function Start-Process { throw 'injected launcher startup failure' }
$env:GITHUB_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$env:GITHUB_RUN_ID='123'
$env:GITHUB_RUN_ATTEMPT='2'
try { & '""" + driver + """' -MainExe (Join-Path $PSScriptRoot 'candidate.exe') -EvidencePath (Join-Path $PSScriptRoot 'acceptance.json') -TimeoutSeconds 3600 }
catch { Write-Output $_; exit 2 }
""", encoding='utf-8')
        run = subprocess.run([shell, '-NoProfile', '-File', str(wrapper)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        return run, request, report

    def test_launcher_failure_preserves_prelaunch_request_and_bound_failure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, request, report = self.invoke(tmp)
            self.assertNotEqual(run.returncode, 0)
            self.assertTrue(request.exists(), run.stdout + run.stderr)
            expected = json.loads(request.read_text(encoding='utf-8-sig'))
            self.assertTrue(expected['launch_session'])
            self.assertTrue(expected['acceptance_nonce'])
            actual = json.loads(report.read_text(encoding='utf-8-sig'))
            self.assertEqual(actual['schema'], 'dlt-background-acceptance-v2')
            self.assertEqual(actual['status'], 'FAIL')
            self.assertEqual(actual['launch_session'], expected['launch_session'])
            self.assertEqual(actual['acceptance_nonce'], expected['acceptance_nonce'])
            self.assertIn('injected launcher startup failure', ' '.join(actual['errors']))

    def test_native_creation_timestamp_rounding_does_not_reject_same_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'candidate.exe').write_bytes(b'unit fixture only')
            driver = str(ROOT / 'scripts' / 'background_acceptance.ps1').replace("'", "''")
            wrapper = root / 'rounding.ps1'
            wrapper.write_text("""
$ErrorActionPreference='Stop'
$script:lookups=0
function Start-Process {
  $script:started=[DateTime]::UtcNow
  $script:root=[pscustomobject]@{ProcessId=100; ParentProcessId=1; ExecutablePath=(Join-Path $PSScriptRoot 'candidate.exe'); CreationDate=$script:started.AddTicks(-1)}
  $proc=[pscustomobject]@{Id=100; StartTime=$script:started; HasExited=$false}
  $proc | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
  return $proc
}
function Get-CimInstance {
  $script:lookups++
  if($script:lookups -eq 1){ return $script:root }
  if($script:lookups -eq 2){ throw 'injected process snapshot failure' }
  return $null
}
$env:GITHUB_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$env:GITHUB_RUN_ID='123'
$env:GITHUB_RUN_ATTEMPT='2'
try { & '""" + driver + """' -MainExe (Join-Path $PSScriptRoot 'candidate.exe') -EvidencePath (Join-Path $PSScriptRoot 'acceptance.json') }
catch { Write-Output $_; exit 2 }
""", encoding='utf-8')
            shell = shutil.which('pwsh')
            self.assertIsNotNone(shell)
            run = subprocess.run([shell, '-NoProfile', '-File', str(wrapper)], capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertNotEqual(run.returncode, 0)
            actual = json.loads((root / 'acceptance.json').read_text(encoding='utf-8-sig'))
            self.assertIn('injected process snapshot failure', ' '.join(actual['errors']))
            self.assertNotIn('launcher PID creation identity mismatch', ' '.join(actual['errors']))

    def test_cleanup_cannot_terminate_pid_reused_after_last_cim_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'candidate.exe').write_bytes(b'unit fixture only')
            driver = str(ROOT / 'scripts' / 'background_acceptance.ps1').replace("'", "''")
            wrapper = root / 'cleanup.ps1'
            wrapper.write_text("""
$ErrorActionPreference='Stop'
$env:UNIT_ROOT=$PSScriptRoot
Add-Type -TypeDefinition @'
using System;
using System.Text;
public static class DLTBackgroundNative {
  public static IntPtr OpenProcess(uint access, bool inherit, int pid) { return new IntPtr(123); }
  public static bool GetProcessTimes(IntPtr handle, out long creation, out long exit, out long kernel, out long user) {
    creation=DateTime.UtcNow.AddMinutes(1).ToFileTimeUtc(); exit=kernel=user=0; return true;
  }
  public static bool QueryFullProcessImageName(IntPtr handle, uint flags, StringBuilder path, ref int length) {
    path.Append(System.IO.Path.Combine(Environment.GetEnvironmentVariable("UNIT_ROOT"),"candidate.exe")); return true;
  }
  public static bool TerminateProcess(IntPtr handle, uint code) {
    System.IO.File.WriteAllText(System.IO.Path.Combine(Environment.GetEnvironmentVariable("UNIT_ROOT"),"terminated.txt"),"bad"); return true;
  }
  public static bool CloseHandle(IntPtr handle) { return true; }
  public static uint WaitForSingleObject(IntPtr handle, uint timeout) { return 258; }
}
'@
$script:lookups=0
function Start-Process {
  $script:started=[DateTime]::UtcNow
  $script:root=[pscustomobject]@{ProcessId=100; ParentProcessId=1; ExecutablePath=(Join-Path $PSScriptRoot 'candidate.exe'); CreationDate=$script:started}
  $proc=[pscustomobject]@{Id=100; StartTime=$script:started; HasExited=$false}
  $proc | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
  return $proc
}
function Get-CimInstance {
  $script:lookups++
  if($script:lookups -eq 2){ throw 'injected observation failure' }
  return $script:root
}
function Stop-Process { Set-Content -LiteralPath (Join-Path $PSScriptRoot 'terminated.txt') 'unsafe PID termination' }
$env:GITHUB_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$env:GITHUB_RUN_ID='123'
$env:GITHUB_RUN_ATTEMPT='2'
try { & '""" + driver + """' -MainExe (Join-Path $PSScriptRoot 'candidate.exe') -EvidencePath (Join-Path $PSScriptRoot 'acceptance.json') }
catch { Write-Output $_; exit 2 }
""", encoding='utf-8')
            shell = shutil.which('pwsh')
            self.assertIsNotNone(shell)
            run = subprocess.run([shell, '-NoProfile', '-File', str(wrapper)], capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((root / 'terminated.txt').exists(), 'cleanup terminated a replaced PID')
            actual = json.loads((root / 'acceptance.json').read_text(encoding='utf-8-sig'))
            self.assertIn('cleanup refused changed handle creation identity', ' '.join(actual['errors']))

    def test_cleanup_initialization_failure_retains_failure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'candidate.exe').write_bytes(b'unit fixture only')
            driver = str(ROOT / 'scripts' / 'background_acceptance.ps1').replace("'", "''")
            wrapper = root / 'cleanup-init.ps1'
            wrapper.write_text("""
$ErrorActionPreference='Stop'
$script:lookups=0
function Start-Process {
  $script:started=[DateTime]::UtcNow
  $script:root=[pscustomobject]@{ProcessId=100; ParentProcessId=1; ExecutablePath=(Join-Path $PSScriptRoot 'candidate.exe'); CreationDate=$script:started}
  $proc=[pscustomobject]@{Id=100; StartTime=$script:started; HasExited=$false}
  $proc | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
  return $proc
}
function Get-CimInstance {
  $script:lookups++
  if($script:lookups -eq 1){ return $script:root }
  if($script:lookups -eq 2){ throw 'injected observation failure' }
  return $null
}
function Add-Type { throw 'injected cleanup initialization failure' }
$env:GITHUB_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$env:GITHUB_RUN_ID='123'
$env:GITHUB_RUN_ATTEMPT='2'
try { & '""" + driver + """' -MainExe (Join-Path $PSScriptRoot 'candidate.exe') -EvidencePath (Join-Path $PSScriptRoot 'acceptance.json') }
catch { Write-Output $_; exit 2 }
""", encoding='utf-8')
            shell = shutil.which('pwsh')
            self.assertIsNotNone(shell)
            run = subprocess.run([shell, '-NoProfile', '-File', str(wrapper)], capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertNotEqual(run.returncode, 0)
            report = root / 'acceptance.json'
            self.assertTrue(report.exists(), 'cleanup failure lost report: ' + run.stdout + run.stderr)
            actual = json.loads(report.read_text(encoding='utf-8-sig'))
            self.assertEqual(actual['status'], 'FAIL')
            self.assertIn('injected cleanup initialization failure', ' '.join(actual['errors']))

    def test_owned_ancestor_foreign_path_reuse_is_rejected_before_next_sample(self):
        # A known launcher is seen once, reappears as a foreign executable, then
        # disappears before cleanup. Filtering new same-EXE candidates first
        # loses this observed reuse event; final cleanup cannot recover it.
        for change_creation in (False, True):
            with self.subTest(change_creation=change_creation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'candidate.exe').write_bytes(b'unit fixture only')
                driver = str(ROOT / 'scripts' / 'background_acceptance.ps1').replace("'", "''")
                wrapper = root / 'ancestor-reuse.ps1'
                wrapper.write_text("""
$ErrorActionPreference='Stop'
$script:snapshots=0
$script:sleeps=0
$script:cleanupEntered=$false
$global:unitTrace=[System.Collections.Generic.List[string]]::new()
function Start-Process {
  $script:snapshots=0
  $script:sleeps=0
  $script:cleanupEntered=$false
  $script:started=[DateTime]::UtcNow
  $script:root=[pscustomobject]@{ProcessId=100; ParentProcessId=1; ExecutablePath=(Join-Path $PSScriptRoot 'candidate.exe'); CreationDate=$script:started}
  $script:foreign=[pscustomobject]@{ProcessId=100; ParentProcessId=9; ExecutablePath=(Join-Path $PSScriptRoot 'foreign.exe'); CreationDate=$script:started.AddSeconds([int]$env:UNIT_CHANGE_CREATION)}
  $proc=[pscustomobject]@{Id=100; StartTime=$script:started; HasExited=$false}
  $proc | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
  return $proc
}
function Get-CimInstance {
  param($ClassName,$Filter)
  if($script:cleanupEntered){ $global:unitTrace.Add('cleanup-absent-100'); return $null }
  if($Filter -eq 'ProcessId=100'){
    if($script:snapshots -eq 0){ $global:unitTrace.Add('known-100-original'); return $script:root }
    $global:unitTrace.Add('known-100-foreign'); return $script:foreign
  }
  if($Filter -like 'Name=*'){
    $script:snapshots++
    if($script:snapshots -eq 1){ $global:unitTrace.Add('snapshot-100-original'); return $script:root }
    $global:unitTrace.Add('snapshot-100-foreign'); return $script:foreign
  }
  throw ('unexpected CIM filter: ' + $Filter)
}
function Start-Sleep {
  $script:sleeps++
  if($script:sleeps -ge 2){ throw 'controlled boundary after missed reuse' }
}
function Add-Type { $script:cleanupEntered=$true }
$env:GITHUB_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$env:GITHUB_RUN_ID='123'
$env:GITHUB_RUN_ATTEMPT='2'
try { & '""" + driver + """' -MainExe (Join-Path $PSScriptRoot 'candidate.exe') -EvidencePath (Join-Path $PSScriptRoot 'acceptance.json') }
catch { Write-Output $_; exit 2 }
finally { ConvertTo-Json -InputObject $global:unitTrace.ToArray() | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'trace.json') -Encoding utf8 }
""", encoding='utf-8')
                shell = shutil.which('pwsh')
                self.assertIsNotNone(shell, 'PowerShell absence is not a passing regression')
                run = subprocess.run([shell, '-NoProfile', '-File', str(wrapper)], capture_output=True,
                                     env=dict(os.environ, UNIT_CHANGE_CREATION='1' if change_creation else '0'),
                                     text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(run.returncode, 0)
                report = root / 'acceptance.json'
                self.assertTrue(report.exists(), run.stdout + run.stderr)
                actual = json.loads(report.read_text(encoding='utf-8-sig'))
                trace = json.loads((root / 'trace.json').read_text(encoding='utf-8-sig'))
                print('ANCESTOR_REUSE_TRACE ' + json.dumps(dict(change_creation=change_creation,
                      events=trace, accepted_samples=len(actual['observer']['samples']), errors=actual['errors'])))
                self.assertEqual(actual['status'], 'FAIL')
                self.assertIn('owned PID identity changed: 100', ' '.join(actual['errors']))
                self.assertEqual(len(actual['observer']['samples']), 1)
                self.assertIn('cleanup-absent-100', trace)

    def test_existing_expected_request_or_report_cannot_be_overwritten(self):
        for prior in ('request', 'report'):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as tmp:
                run, request, report = self.invoke(tmp, prior=prior)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('already exists', run.stdout + run.stderr)
                existing = request if prior == 'request' else report
                self.assertEqual(existing.read_text(encoding='utf-8'), 'preserved old ' + prior)


if __name__ == '__main__':
    unittest.main()
