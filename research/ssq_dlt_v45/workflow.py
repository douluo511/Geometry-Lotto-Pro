"""Five scheduled research stages. No search hit can assign an official target.

Local preparation and successful mail submission are separate measurements.
Catch-up uses its real observation clock, never the missed scheduled clock.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import uuid

from . import delivery, runtime, sources
from .models import generate, validate_prediction
from .replay import replay_ready, write_replay_report
from .store import Store, canonical, digest, parse

STAGES = (('discover',15,10),('history',15,20),('predict',15,30),('check',15,45),('publish',16,0))


def active_slot(now):
    if now.tzinfo is None:
        raise ValueError('AWARE_CLOCK_REQUIRED')
    local=now.astimezone(runtime.JST)
    for offset in range(8):
        day=local-timedelta(days=offset)
        start=day.replace(hour=15,minute=10,second=0,microsecond=0)
        if day.weekday() in (0,2,5) and start<=local:
            return day.replace(hour=16,minute=0,second=0,microsecond=0)
    raise ValueError('NO_DUE_SLOT')


def code_pin():
    base=Path(__file__).resolve().parent
    return {p.relative_to(base.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for root in (base,base.parent/'ssq_dlt_d2_v44') for p in sorted(root.rglob('*'))
            if p.is_file() and p.suffix in ('.py','.ps1','.xml')
            and not {'tests','__pycache__','evidence'}.intersection(p.relative_to(root).parts)}


def validate_issue_sequence(game,rows):
    """Check observed within-year continuity without inventing a calendar.

    A valid file SHA and two agreeing recent sources cannot resolve a hole
    between an older pinned archive and the recent source window. Year-end
    final ordinals and absent dates need separate official resolution.
    """
    width=7 if game=='SSQ' else 5
    previous_year=previous_ordinal=None
    for row in rows:
        issue=row['issue']; year=row['draw_date'][:4]
        prefix=year if game=='SSQ' else year[2:]
        if (type(issue) is not str or len(issue)!=width or not issue.isascii()
                or not issue.isdigit() or issue[:-3]!=prefix):
            raise ValueError('BLOCKED_GAME_ISSUE_FORMAT_OR_YEAR_MISMATCH')
        ordinal=int(issue[-3:])
        if not 1<=ordinal<=999:
            raise ValueError('BLOCKED_ISSUE_ORDINAL_OUT_OF_RANGE')
        if year==previous_year and ordinal!=previous_ordinal+1:
            raise ValueError('BLOCKED_INTRA_YEAR_ISSUE_GAP_REQUIRES_OFFICIAL_RESOLUTION')
        previous_year,previous_ordinal=year,ordinal


def history_stage(config,root,now):
    games={}
    for game in ('SSQ','DLT'):
        try:
            rows=sources.load_pinned(game,config['history'][game],now)
            receipts=[]
            if config.get('live_sources',True):
                recent,receipts=sources.capture_pair(game,root/'sources',now)
                cached={r['issue']:r for r in rows}
                for row in recent:
                    if row['issue'] in cached and cached[row['issue']]!=row:
                        raise ValueError('OFFICIAL_VS_PINNED_CONFLICT')
                    cached[row['issue']]=row
                if int(recent[-1]['issue'])<int(rows[-1]['issue']):
                    raise ValueError('OFFICIAL_SOURCE_BEHIND_PINNED_LATEST')
                rows=sorted(cached.values(),key=lambda r:(r['draw_date'],r['issue']))
            validate_issue_sequence(game,rows)
            games[game]=dict(status='HISTORY_CHECKED',rows=rows,receipts=receipts,
                sha256=digest(rows),publication_asof_verified=False,target=None)
        except Exception as exc:
            games[game]=dict(status='BLOCKED',reason=str(exc),error=type(exc).__name__,target=None)
    return games


def observe_clock(store,now):
    """Persist a global clock floor before work, even if this process crashes.

    The transaction serializes competing ticks. This only protects the local
    ledger clock; it is not an independent timestamp authority.
    """
    payload=dict(at=now.astimezone(timezone.utc).isoformat())
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for row in db.execute("SELECT payload,sha256 FROM events WHERE kind IN ('workflow_clock','workflow_tick')"):
                previous=store.checked(row)
                if datetime.fromisoformat(previous['at'])>now:
                    raise ValueError('CLOCK_REWIND_ACROSS_CYCLES')
            db.execute('INSERT INTO events VALUES(?,?,?,?)',('workflow_clock',uuid.uuid4().hex,canonical(payload),digest(payload)))
            db.commit()
        except BaseException:
            db.rollback(); raise


def metrics(store,now):
    cycles=store.rows('workflow_cycle')
    elapsed=[c for c in cycles if datetime.fromisoformat(c['due_slot'])<=now]
    publications=store.rows('workflow_publish')
    ready={p['due_slot'] for p in publications if p['research_ready'] and
           datetime.fromisoformat(p['created_at'])<=datetime.fromisoformat(p['due_slot'])}
    accepted={x['id'] for x in store.rows('sent')}
    mail={p['due_slot'] for p in publications if p.get('outbox_id') in accepted}
    def rate(n,d):
        return dict(numerator=n,denominator=d,rate=n/d if d else None)
    return dict(scope='OBSERVED_CYCLES_ONLY_NOT_UNOBSERVED_SCHEDULE_RELIABILITY',
        on_time_research_output=rate(sum(c['due_slot'] in ready for c in elapsed),len(elapsed)),
        smtp_accepted_cycles=rate(sum(c['due_slot'] in mail for c in elapsed),len(elapsed)),
        qualified_pre_draw_freeze=rate(0,len(elapsed)*2),
        replay_complete=rate(0,0),replay_reason='NO_ADMITTED_TARGET_BOUND_FORECASTS',
        inbox_delivery='NOT_VERIFIED',formal_A=0,decision='NO_EDGE')


def tick(config,now=None):
    # Explicit clocks are for deterministic fault tests. Live work samples the
    # wall clock again after each completed stage, never reuses tick-start as
    # the time at which later network bytes/predictions became observable.
    clock=(lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    now=clock()
    slot=active_slot(now); key=slot.isoformat()
    root=Path(config['state_dir'])
    if not root.is_absolute(): raise ValueError('ABSOLUTE_STATE_REQUIRED')
    if any(config.get(f) for f in ('formal','authorized','tsa_verified')):
        raise ValueError('CALLER_BOOLEAN_IS_NOT_AUTHORIZATION')
    if any(k in config for k in ('target','targets','official_target')):
        raise ValueError('NO_VERIFIED_TARGET_ADAPTER')
    store=Store(root/'workflow.sqlite3')
    observe_clock(store,now)
    pin=code_pin()
    existing=store.read('workflow_cycle',key)
    identity=dict(due_slot=key,config_sha256=digest(config),code_sha256=pin)
    if existing and existing!=identity:
        raise ValueError('WORKFLOW_CODE_OR_CONFIG_DRIFT_REQUIRES_NEW_STATE')
    store.append('workflow_cycle',key,identity)
    stages={}; errors=[]
    for stage,hour,minute in STAGES:
        current=clock()
        observe_clock(store,current)
        scheduled=slot.replace(hour=hour,minute=minute)
        if current<scheduled: break
        stagekey=key+'/'+stage
        old=store.read('workflow_stage',stagekey)
        if old:
            if datetime.fromisoformat(old['observed_at'])>current:
                raise ValueError('CLOCK_REWIND')
            if stage=='publish':
                runtime.write_report(root/'reports',old['result']['report'])
            stages[stage]=old['result']; continue
        try:
            if stage=='discover':
                from .discovery import run_discovery
                result=run_discovery(config.get('discovery',{}),root/'discovery')
            elif stage=='history':
                result=history_stage(config,root,current)
                if any(x['status']=='BLOCKED' for x in result.values()):
                    # Preserve both game statuses but permit recovery next tick.
                    checked=clock(); observe_clock(store,checked)
                    store.append('workflow_failure',uuid.uuid4().hex,dict(due_slot=key,stage=stage,observed_at=checked.isoformat(),result=result))
                    stages[stage]=result; continue
            elif stage=='predict':
                result={}
                for game,data in stages.get('history',{}).items():
                    if data['status']=='BLOCKED': continue
                    prediction=generate(game,'UNASSIGNED',data['rows'])
                    validate_prediction(prediction)
                    result[game]=dict(status='RESEARCH_UNASSIGNED',target=None,
                        history_rows=len(data['rows']),history_last_issue=data['rows'][-1]['issue'],
                        history_sha256=data['sha256'],receipts=data['receipts'],
                        publication_asof_verified=False,preview=prediction)
                if set(result)!=set(('SSQ','DLT')):
                    raise ValueError('BOTH_HISTORIES_REQUIRED')
            elif stage=='check':
                if 'predict' not in stages: raise ValueError('PREDICTION_NOT_READY')
                for data in stages['predict'].values(): validate_prediction(data['preview'])
                result=dict(prediction_sha256=digest(stages['predict']),local_hash_verified=True,
                    trusted_external_timestamp='BLOCKED',formal_A=0)
            else:
                good=('check' in stages and 'predict' in stages and
                      stages['check']['prediction_sha256']==digest(stages['predict']))
                games=stages['predict'] if good else {g:dict(status='BLOCKED',target=None,
                    reason=stages.get('history',{}).get(g,{}).get('reason','PREPARATION_INCOMPLETE'))
                    for g in ('SSQ','DLT')}
                created=clock()
                observe_clock(store,created)
                report=dict(schema='GLP_V45_RESEARCH_REPORT_1',due_slot=key,created_at=created.isoformat(),
                    scope='RESEARCH_UNASSIGNED',games=games,blockers=runtime.BLOCKERS,
                    workflow=dict(discovery=stages.get('discover',{}),
                        prepared_at=store.read('workflow_stage',key+'/check'),
                        punctuality='AT_DUE' if created==slot else 'LATE',
                        metrics_snapshot='BEFORE_CURRENT_PUBLICATION_AND_SMTP_ATTEMPT_SEE_TICK_RECEIPT_FOR_UPDATED_COUNTS',
                        metrics=metrics(store,created)),**runtime.BOUNDARY)
                publication_key=digest(dict(due_slot=key,games=games))
                previous=store.read('workflow_publish',publication_key)
                if previous:
                    folder=runtime.write_report(root/'reports',previous['report'])
                    result=previous
                else:
                    folder=runtime.write_report(root/'reports',report)
                    outbox=delivery.prepare(store,root/'outbox',config['recipient'],report,runtime.render(report)) if config.get('recipient') else None
                    result=dict(due_slot=key,created_at=created.isoformat(),research_ready=good,
                        report_directory=str(folder),outbox_id=outbox,report=report)
                    store.append('workflow_publish',publication_key,result)
                if not good:
                    # A BLOCKED status is still published once per unchanged state.
                    # Later successful preparation may append a distinct late report.
                    stages[stage]=result; continue
            completed=clock(); observe_clock(store,completed)
            payload=dict(due_slot=key,stage=stage,scheduled_at=scheduled.isoformat(),
                observed_at=completed.isoformat(),backdated=False,result=result)
            try: store.append('workflow_stage',stagekey,payload)
            except ValueError as exc:
                if str(exc)!='IMMUTABLE_CONFLICT': raise
                payload=store.read('workflow_stage',stagekey)
            stages[stage]=payload['result']
        except Exception as exc:
            if isinstance(exc,ValueError) and str(exc).startswith('CLOCK_REWIND'):
                raise
            failure=dict(due_slot=key,stage=stage,observed_at=clock().isoformat(),error=type(exc).__name__,reason=str(exc))
            store.append('workflow_failure',uuid.uuid4().hex,failure); errors.append(failure)
    mail=delivery.flush(store,config.get('smtp'))
    replay=replay_ready(store); replay_dir=write_replay_report(root/'replays',replay)
    finished=clock()
    observe_clock(store,finished)
    receipt=dict(at=finished.isoformat(),started_at=now.isoformat(),due_slot=key,completed_stages=list(stages),errors=errors,
        mail=mail,replay=replay['status'],replay_directory=str(replay_dir),metrics=metrics(store,finished),
        scheduler_execution='DIRECT_TICK_NOT_SCHEDULER_PROOF',formal_A=0,decision='NO_EDGE')
    store.append('workflow_tick',uuid.uuid4().hex,receipt)
    return receipt


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--config',required=True,type=Path)
    a=p.parse_args(argv)
    if not a.config.is_absolute(): p.error('absolute config required')
    try:
        result=tick(parse(a.config.read_bytes())); print(canonical(result))
        return 0 if not result['errors'] else 2
    except Exception as exc:
        print(canonical(dict(status='FAIL',error=type(exc).__name__,reason=str(exc),formal_A=0,decision='NO_EDGE'))); return 1


if __name__=='__main__': raise SystemExit(main())
