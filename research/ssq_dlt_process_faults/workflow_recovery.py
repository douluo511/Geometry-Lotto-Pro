"""Opt-in recovery workflow; existing V4.5 sources and ledgers stay immutable.

Uses a durable publication intent before writing reports or preparing mail.
The original code/config drift rule requires a separate state directory.
Research remains unassigned: formal_A=0, NO_EDGE and target=None.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid

from ..ssq_dlt_v45 import delivery, runtime, workflow as original
from ..ssq_dlt_v45.models import generate, validate_prediction
from ..ssq_dlt_v45.replay import replay_ready, write_replay_report
from ..ssq_dlt_v45.store import Store, canonical, digest, parse
from ..ssq_dlt_v45.workflow import (
    STAGES, active_slot, history_stage, metrics, observe_clock,
)
from .publication import durable_publish


def code_pin():
    """Pin all original workflow code plus the two recovery implementation files."""
    pin = original.code_pin()
    base = Path(__file__).resolve().parent
    for name in ('publication.py', 'workflow_recovery.py'):
        path = base / name
        pin[path.relative_to(base.parent).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pin


def tick(config, now=None):
    # Preserve the original stage clocks: only deterministic fault tests supply
    # an explicit time; live stages sample the wall clock after their work.
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    now = clock()
    slot = active_slot(now)
    key = slot.isoformat()
    root = Path(config['state_dir'])
    if not root.is_absolute():
        raise ValueError('ABSOLUTE_STATE_REQUIRED')
    if any(config.get(f) for f in ('formal', 'authorized', 'tsa_verified')):
        raise ValueError('CALLER_BOOLEAN_IS_NOT_AUTHORIZATION')
    if any(k in config for k in ('target', 'targets', 'official_target')):
        raise ValueError('NO_VERIFIED_TARGET_ADAPTER')
    store = Store(root / 'workflow.sqlite3')
    observe_clock(store, now)
    pin = code_pin()
    existing = store.read('workflow_cycle', key)
    identity = dict(due_slot=key, config_sha256=digest(config), code_sha256=pin)
    if existing and existing != identity:
        raise ValueError('WORKFLOW_CODE_OR_CONFIG_DRIFT_REQUIRES_NEW_STATE')
    store.append('workflow_cycle', key, identity)
    stages = {}
    errors = []
    for stage, hour, minute in STAGES:
        current = clock()
        observe_clock(store, current)
        scheduled = slot.replace(hour=hour, minute=minute)
        if current < scheduled:
            break
        stagekey = key + '/' + stage
        old = store.read('workflow_stage', stagekey)
        if old:
            if datetime.fromisoformat(old['observed_at']) > current:
                raise ValueError('CLOCK_REWIND')
            if stage == 'publish':
                runtime.write_report(root / 'reports', old['result']['report'])
            stages[stage] = old['result']
            continue
        try:
            if stage == 'discover':
                from ..ssq_dlt_v45.discovery import run_discovery
                result = run_discovery(config.get('discovery', {}), root / 'discovery')
            elif stage == 'history':
                result = history_stage(config, root, current)
                if any(x['status'] == 'BLOCKED' for x in result.values()):
                    checked = clock()
                    observe_clock(store, checked)
                    store.append('workflow_failure', uuid.uuid4().hex, dict(
                        due_slot=key, stage=stage, observed_at=checked.isoformat(), result=result))
                    stages[stage] = result
                    continue
            elif stage == 'predict':
                result = {}
                for game, data in stages.get('history', {}).items():
                    if data['status'] == 'BLOCKED':
                        continue
                    prediction = generate(game, 'UNASSIGNED', data['rows'])
                    validate_prediction(prediction)
                    result[game] = dict(
                        status='RESEARCH_UNASSIGNED', target=None,
                        history_rows=len(data['rows']), history_last_issue=data['rows'][-1]['issue'],
                        history_sha256=data['sha256'], receipts=data['receipts'],
                        publication_asof_verified=False, preview=prediction)
                if set(result) != set(('SSQ', 'DLT')):
                    raise ValueError('BOTH_HISTORIES_REQUIRED')
            elif stage == 'check':
                if 'predict' not in stages:
                    raise ValueError('PREDICTION_NOT_READY')
                for data in stages['predict'].values():
                    validate_prediction(data['preview'])
                result = dict(
                    prediction_sha256=digest(stages['predict']), local_hash_verified=True,
                    trusted_external_timestamp='BLOCKED', formal_A=0)
            else:
                good = ('check' in stages and 'predict' in stages
                        and stages['check']['prediction_sha256'] == digest(stages['predict']))
                games = stages['predict'] if good else {
                    g: dict(status='BLOCKED', target=None, reason=stages.get('history', {}).get(
                        g, {}).get('reason', 'PREPARATION_INCOMPLETE'))
                    for g in ('SSQ', 'DLT')}
                created = clock()
                observe_clock(store, created)
                report = dict(
                    schema='GLP_V45_RESEARCH_REPORT_1', due_slot=key, created_at=created.isoformat(),
                    scope='RESEARCH_UNASSIGNED', games=games, blockers=runtime.BLOCKERS,
                    workflow=dict(
                        discovery=stages.get('discover', {}),
                        prepared_at=store.read('workflow_stage', key + '/check'),
                        punctuality='AT_DUE' if created == slot else 'LATE',
                        metrics_snapshot='BEFORE_CURRENT_PUBLICATION_AND_SMTP_ATTEMPT_SEE_TICK_RECEIPT_FOR_UPDATED_COUNTS',
                        metrics=metrics(store, created)),
                    **runtime.BOUNDARY)
                publication_key = digest(dict(due_slot=key, games=games))
                result = durable_publish(
                    store, root, publication_key, report, good, config.get('recipient'))
                if not result['research_ready']:
                    # A later successful preparation can have a distinct key.
                    stages[stage] = result
                    continue
            completed = clock()
            observe_clock(store, completed)
            payload = dict(
                due_slot=key, stage=stage, scheduled_at=scheduled.isoformat(),
                observed_at=completed.isoformat(), backdated=False, result=result)
            try:
                store.append('workflow_stage', stagekey, payload)
            except ValueError as exc:
                if str(exc) != 'IMMUTABLE_CONFLICT':
                    raise
                payload = store.read('workflow_stage', stagekey)
            stages[stage] = payload['result']
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc).startswith('CLOCK_REWIND'):
                raise
            failure = dict(
                due_slot=key, stage=stage, observed_at=clock().isoformat(),
                error=type(exc).__name__, reason=str(exc))
            store.append('workflow_failure', uuid.uuid4().hex, failure)
            errors.append(failure)
    publication_blocked = any(
        error['stage'] == 'publish' and error['reason'].startswith('BLOCKED_')
        for error in errors)
    mail = ([dict(status='BLOCKED_PUBLICATION_INTEGRITY')] if publication_blocked
            else delivery.flush(store, config.get('smtp')))
    replay = replay_ready(store)
    replay_dir = write_replay_report(root / 'replays', replay)
    finished = clock()
    observe_clock(store, finished)
    receipt = dict(
        at=finished.isoformat(), started_at=now.isoformat(), due_slot=key,
        completed_stages=list(stages), errors=errors, mail=mail, replay=replay['status'],
        replay_directory=str(replay_dir), metrics=metrics(store, finished),
        scheduler_execution='DIRECT_TICK_NOT_SCHEDULER_PROOF', formal_A=0, decision='NO_EDGE')
    store.append('workflow_tick', uuid.uuid4().hex, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.config.is_absolute():
        parser.error('absolute config required')
    try:
        result = tick(parse(args.config.read_bytes()))
        print(canonical(result))
        return 0 if not result['errors'] else 2
    except Exception as exc:
        print(canonical(dict(
            status='FAIL', error=type(exc).__name__, reason=str(exc), formal_A=0, decision='NO_EDGE')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
