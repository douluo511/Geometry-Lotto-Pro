"""Pure validation of native background evidence; this module never launches work."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import ntpath
from datetime import datetime
from pathlib import Path
from typing import Any


MINIMUM_SECONDS = 1800
MAX_SAMPLE_GAP_SECONDS = 5


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _integer(value: Any) -> bool:
    return type(value) is int and value > 0


def _path(value: Any) -> str:
    return ntpath.normcase(ntpath.normpath(value)) if isinstance(value, str) and value.strip() else ''


def _date(value: Any) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('process creation timestamps must have a timezone')
    return result


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate(report: Any, request: Any, *, sha: str, run_id: str, run_attempt: str,
             exe_sha256: str, exe_path: str) -> dict[str, Any]:
    """Validate independent expected identity and the two named monotonic clocks.

    Wall timestamps bind process creation freshness only. Durations are checked
    solely within each respective monotonic clock; their origins are unrelated.
    """
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        if not isinstance(report, dict) or not isinstance(request, dict):
            raise ValueError('report and expected request must be objects')
        check(request.get('schema') == 'dlt-background-acceptance-request-v2', 'expected request schema')
        check(report.get('schema') == 'dlt-background-acceptance-v2', 'report schema (v2 required)')
        external = dict(github_sha=sha, github_run_id=run_id, github_run_attempt=run_attempt,
                        exe_sha256=exe_sha256, exe_path=exe_path)
        for key, expected in external.items():
            check(isinstance(expected, str) and bool(expected.strip()), 'empty external ' + key)
            actual_request, actual_report = request.get(key), report.get(key)
            if key == 'exe_path':
                check(_path(actual_request) == _path(expected) and _path(actual_report) == _path(expected), 'identity ' + key)
            else:
                check(actual_request == expected and actual_report == expected, 'identity ' + key)
        for key, length in [('github_sha', 40), ('exe_sha256', 64)]:
            value = external[key]
            check(len(value) == length and all(c in '0123456789abcdef' for c in value), 'invalid external ' + key)
        for key in ('launch_session', 'acceptance_nonce'):
            expected = request.get(key)
            check(isinstance(expected, str) and bool(expected.strip()), 'empty expected ' + key)
            check(report.get(key) == expected, 'report binding ' + key)
        check(report.get('status') == 'PASS' and report.get('errors') == [], 'driver did not succeed')
        check(report.get('exe_sha256_before') == exe_sha256 and report.get('exe_sha256_after') == exe_sha256,
              'executable bytes changed')

        launch = report['launch']
        worker = report['worker_status']
        observer = report['observer']
        check(launch.get('schema') == 'dlt-background-launch-v2', 'launch schema')
        check(worker.get('schema') == 'dlt-background-worker-v2', 'worker schema')
        for name, item in [('launch', launch), ('worker', worker)]:
            for key in ('launch_session', 'acceptance_nonce'):
                check(item.get(key) == request.get(key), name + ' binding ' + key)
            check(item.get('exe_sha256') == exe_sha256, name + ' executable hash')
            check(item.get('status') == 'PASS', name + ' failed')
            check(item.get('interval_seconds') == 1800 and item.get('production_poll_seconds') == 1800,
                  name + ' production interval')
        check(launch.get('max_cycles') == 2 and launch.get('wait_parent_exit') is True and launch.get('shell') is False,
              'launch arguments')
        check(worker.get('clock_origin') == 'worker_monotonic_start', 'worker clock origin')
        check(worker.get('startup_mode') == 'manual_app_launch_required_after_login' and worker.get('autostart_registered') is False,
              'manual startup contract')
        check(worker.get('parent_pid') == launch.get('parent_pid') and worker.get('parent_exit_observed') is True,
              'launcher parent exit')
        check(worker.get('cycle_count') == 2 and worker.get('worker_exit') == 'MAX_CYCLES_REACHED', 'two completed cycles')
        check(worker.get('failed_cycle_count') == 0 and worker.get('first_error') is None, 'earlier cycle failure')
        cycles = worker['cycles']
        check(isinstance(cycles, list) and len(cycles) == 2, 'two retained cycles required')
        previous_end = None
        for sequence, cycle in enumerate(cycles, 1):
            check(type(cycle.get('sequence')) is int and cycle.get('sequence') == sequence, 'cycle sequence')
            for key in ('launch_session', 'acceptance_nonce'):
                check(cycle.get(key) == request.get(key), 'cycle binding ' + key)
            start, end = cycle.get('started_offset_seconds'), cycle.get('finished_offset_seconds')
            valid = _number(start) and _number(end) and end >= start
            check(valid, 'invalid worker offsets')
            if previous_end is not None:
                check(valid and _number(previous_end) and start - previous_end >= MINIMUM_SECONDS,
                      'worker completion-to-next-start below 1800 seconds')
            previous_end = end
            result = cycle.get('result')
            check(cycle.get('status') == 'PASS' and cycle.get('error') is None and isinstance(result, dict), 'cycle failed')
            if not isinstance(result, dict):
                continue
            check(cycle.get('result_sha256') == _digest(result), 'cycle digest')
            check(all(result.get(key) == 'PASS' for key in ('status', 'network_gate', 'crosscheck_status')), 'fresh official update failed')
            check(all(isinstance(result.get(key), str) and bool(result[key]) for key in ('prediction_id', 'freeze_hash', 'target_issue')),
                  'missing immutable Freeze')
            check(len(result.get('research_dan_front', [])) == 2 and len(result.get('research_dan_back', [])) == 1, 'research dan defaults')
            check(result.get('production_edge_state') == 'NO_EDGE' and result.get('production_dan_state') == 'NULL_DAN', 'production promotion')
            check(isinstance(result.get('source_receipts'), list), 'update receipts must be retained when available')

        check(observer.get('clock_origin') == 'observer_stopwatch_start', 'observer clock origin')
        elapsed = observer.get('elapsed_seconds')
        exit_offset = observer.get('launcher_exit_offset_seconds')
        final_offset = observer.get('final_status_observed_offset_seconds')
        gap_limit = observer.get('max_sample_gap_seconds')
        check(_number(elapsed) and elapsed >= MINIMUM_SECONDS, 'observer elapsed below 1800 seconds')
        check(_number(exit_offset) and _number(final_offset) and _number(elapsed) and exit_offset <= final_offset <= elapsed,
              'observer exit/final ordering')
        check(observer.get('launcher_exit_code') == 0, 'launcher exit code')
        check(_number(exit_offset) and exit_offset <= 90, 'launcher startup exceeded 90 seconds')
        check(_number(gap_limit) and 0 < gap_limit <= MAX_SAMPLE_GAP_SECONDS, 'unbounded process samples')
        launch_time = _date(observer['launch_started_at'])
        samples = observer['samples']
        check(isinstance(samples, list) and len(samples) >= 2, 'missing process observations')
        check(_number(samples[0].get('offset_seconds')) and _number(gap_limit) and samples[0]['offset_seconds'] <= gap_limit,
              'late first process observation')
        identities: dict[int, tuple[Any, ...]] = {}
        worker_times = []
        previous_offset = None
        absent_after_seen = False
        saw_worker = False
        worker_pid = worker.get('pid')
        launcher_pid = observer.get('launcher_pid')
        child_pid = launch.get('child_pid')
        parent_pid = launch.get('parent_pid')
        check(all(_integer(pid) for pid in (worker_pid, launcher_pid, child_pid, parent_pid)), 'invalid process ids')
        check(child_pid != parent_pid and worker_pid != parent_pid, 'worker is launcher')
        for sample in samples:
            offset = sample.get('offset_seconds')
            check(_number(offset) and _number(elapsed) and offset <= elapsed, 'invalid process sample offset')
            if previous_offset is not None:
                check(_number(offset) and _number(previous_offset) and offset > previous_offset,
                      'regressing sample offsets')
                check(_number(offset) and _number(previous_offset) and _number(gap_limit) and offset - previous_offset <= gap_limit,
                      'process sample gap')
            previous_offset = offset
            present = set()
            for process in sample['processes']:
                pid = process.get('pid')
                check(_integer(pid) and pid not in present, 'invalid/duplicate sampled pid')
                present.add(pid)
                if _number(offset) and _number(exit_offset) and offset >= exit_offset:
                    check(pid not in (launcher_pid, parent_pid), 'launcher lineage observed after exit')
                created = _date(process['creation_time'])
                check(created >= launch_time, 'stale process creation')
                check(_path(process.get('exe_path')) == _path(exe_path) and process.get('exe_sha256') == exe_sha256,
                      'sampled executable identity')
                identity = (process.get('parent_pid'), process['creation_time'], _path(process.get('exe_path')), process.get('exe_sha256'))
                check(pid not in identities or identities[pid] == identity, 'pid identity reuse/replacement')
                identities.setdefault(pid, identity)
            if worker_pid in present:
                check(not absent_after_seen, 'worker disappeared and reappeared')
                saw_worker = True
                if _number(offset) and _number(exit_offset) and offset >= exit_offset:
                    worker_times.append(offset)
            elif saw_worker:
                absent_after_seen = True
        check(len(worker_times) >= 2 and worker_times[-1] - worker_times[0] >= MINIMUM_SECONDS,
              'externally observed live worker span below 1800 seconds')
        check(_number(previous_offset) and _number(final_offset) and previous_offset <= final_offset,
              'final status precedes last process sample')
        check(bool(worker_times) and _number(final_offset) and _number(gap_limit) and 0 <= final_offset - worker_times[-1] <= gap_limit,
              'final status delayed after last live worker sample')
        # Native one-file bootloader and payload have distinct PIDs. Each link must
        # be observed externally, fresh, same-path/hash, with stable creation identity.
        def descendant(pid: int, ancestor: int) -> bool:
            visited = set()
            while pid != ancestor:
                if pid in visited or pid not in identities:
                    return False
                visited.add(pid)
                parent = identities[pid][0]
                if parent not in identities or _date(identities[parent][1]) > _date(identities[pid][1]):
                    return False
                pid = parent
            return pid in identities

        check(descendant(parent_pid, launcher_pid), 'launcher payload lineage')
        check(descendant(child_pid, parent_pid), 'detached bootloader lineage')
        check(descendant(worker_pid, child_pid), 'worker payload lineage')
        lineage = set()
        current = worker_pid
        while current in identities and current not in lineage:
            lineage.add(current)
            if current == launcher_pid:
                break
            current = identities[current][0]
        check(set(identities) <= lineage, 'additional or replacement executable payload')
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
        errors.append('malformed evidence: ' + str(exc))
    return {'schema': 'dlt-background-verification-v2', 'status': 'FAIL' if errors else 'PASS', 'errors': errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--request', required=True)
    for argument in ('sha', 'run-id', 'run-attempt', 'exe-sha256', 'exe-path'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(Path(args.report).read_text(encoding='utf-8-sig'))
        request = json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
        result = validate(report, request, sha=args.sha, run_id=args.run_id, run_attempt=args.run_attempt,
                          exe_sha256=args.exe_sha256, exe_path=args.exe_path)
    except (OSError, ValueError) as exc:
        result = {'schema': 'dlt-background-verification-v2', 'status': 'FAIL', 'errors': ['cannot read evidence: ' + str(exc)]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
