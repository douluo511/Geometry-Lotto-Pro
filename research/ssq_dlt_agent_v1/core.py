"""Application-owned Agent state. The language model never owns a verdict.

Claims precede effects, results are immutable, and unresolved claims stop a
restart. Local SHA/clock checks are integrity controls, not a trusted timestamp.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import math
import os
from pathlib import Path
import re
import time
import uuid

from research.ssq_dlt_v45 import delivery, discovery, models, sources, workflow
from research.ssq_dlt_v45.replay import replay_ready
from research.ssq_dlt_v45.store import Store
from research.ssq_dlt_v45_audit.promotion import registry as quarantine_registry, selection_result
from .ledger import Ledger
from .policy import AgentBlocked, BOUNDARY, canonical, digest, native, parse, validate_call, validate_config


def code_manifest():
    base=Path(__file__).resolve().parent.parent
    return {p.relative_to(base).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ('ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44','ssq_dlt_v45_audit')
            for p in sorted((base/name).rglob('*'))
            if p.is_file() and p.suffix in ('.py','.ps1','.xml','.txt')
            and not {'tests','__pycache__','evidence'}.intersection(p.relative_to(base/name).parts)}


def exclusive(path,raw):
    """An existing byte sequence may be reused, never replaced."""
    path=native(path); path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('xb') as f:
            f.write(raw); f.flush()
            import os
            os.fsync(f.fileno())
    except FileExistsError:
        if path.read_bytes()!=raw: raise AgentBlocked('ARTIFACT_IMMUTABLE_CONFLICT') from None
    return hashlib.sha256(raw).hexdigest()


def _error_code(exc):
    text=str(exc)
    return text if re.fullmatch('[A-Z][A-Z0-9_]{1,100}',text) else type(exc).__name__


class AgentContext:
    def __init__(self,config,run_key,*,mode='TOOLS_SMOKE_NO_MODEL',clock=None,monotonic=None):
        self.config=validate_config(config)
        if type(run_key) is not str or not 1<=len(run_key)<=200: raise AgentBlocked('INVALID_RUN_KEY')
        if mode not in ('TOOLS_SMOKE_NO_MODEL','SDK_SIMULATED_MODEL','SDK_LIVE_MODEL'):
            raise AgentBlocked('INVALID_EXECUTION_MODE')
        self.mode=mode; self.run_id=digest({'run_key':run_key}); self.run_key=run_key
        self.root=Path(self.config['state_dir']); self.run_root=self.root/'r'/self.run_id[:16]
        self.clock=clock or (lambda:datetime.now(timezone.utc)); self.monotonic=monotonic or time.monotonic
        self.started=self.monotonic(); self.pin=code_manifest(); self.config_sha=digest(self.config)
        self.sdk_model=os.environ.get('GLP_AGENT_MODEL') if mode=='SDK_LIVE_MODEL' else ('FIXED_SDK_FIXTURE' if mode=='SDK_SIMULATED_MODEL' else None)
        self.ledger=Ledger(self.root/'agent.sqlite3'); self.ledger.integrity()
        now=self._observe_clock()
        identity=dict(run_id=self.run_id,run_key=run_key,mode=mode,sdk_model=self.sdk_model,config_sha256=self.config_sha,
                      code_sha256=digest(self.pin),code_manifest=self.pin)
        old=self.ledger.read('run',self.run_id)
        if old is not None:
            if any(old[k]!=v for k,v in identity.items()): raise AgentBlocked('RUN_IDENTITY_CHANGED')
            self.created_at=old['created_at']; self.due_slot=old['due_slot']
        else:
            self.created_at=now.isoformat(); self.due_slot=workflow.active_slot(now).isoformat()
            self.ledger.append('run',self.run_id,dict(identity,created_at=self.created_at,due_slot=self.due_slot))
        self._current_model_claim=None

    def _observe_clock(self):
        now=self.clock()
        if not isinstance(now,datetime) or now.tzinfo is None: raise AgentBlocked('AWARE_CLOCK_REQUIRED')
        now=now.astimezone(timezone.utc)
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for row in db.execute("SELECT payload,sha256 FROM events WHERE kind='clock'"):
                    old=self.ledger.checked(row)
                    if datetime.fromisoformat(old['at'])>now: raise AgentBlocked('CLOCK_REWIND')
                value=dict(at=now.isoformat())
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('clock',uuid.uuid4().hex,canonical(value),digest(value)))
                db.commit()
            except BaseException: db.rollback(); raise
        return now

    def _guard(self,*,enforce_time=True):
        if digest(self.config)!=self.config_sha: raise AgentBlocked('CONFIG_CHANGED_DURING_RUN')
        if self.mode=='SDK_LIVE_MODEL' and os.environ.get('GLP_AGENT_MODEL')!=self.sdk_model:
            raise AgentBlocked('SDK_MODEL_CHANGED_DURING_RUN')
        if code_manifest()!=self.pin: raise AgentBlocked('CODE_CHANGED_DURING_RUN')
        if enforce_time and self.monotonic()-self.started>=self.config['limits']['max_seconds']:
            raise AgentBlocked('COOPERATIVE_TIME_BUDGET_EXHAUSTED')
        self._observe_clock()

    def _rows(self,kind):
        return [r for r in self.ledger.rows(kind) if r.get('run_id')==self.run_id]

    def _result(self,tool,action=None):
        rows=[r for r in self._rows('tool_result') if r['tool']==tool
              and (action is None or r['arguments'].get('action')==action)]
        return max(rows,key=lambda r:r['sequence']) if rows else None

    def snapshot(self):
        return {name:self._result(name) for name in
                ('discover_sources','verify_official_sources','run_frozen_models','audit_experiment')}

    def _claim_tool(self,tool,arguments,*,host_finalizing=False):
        scope=dict(tool=tool,arguments=arguments)
        if tool=='deliver_report':
            scope['snapshot_sha256']=digest(dict(snapshot=self.snapshot(),model_claims=self._rows('model_claim'),
                model_results=self._rows('model_result'),execution=self.ledger.read('execution_result',self.run_id)))
        identity=digest(scope)
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                claims=[self.ledger.checked(r) for r in db.execute("SELECT payload,sha256 FROM events WHERE kind='tool_claim'")]
                claims=[c for c in claims if c['run_id']==self.run_id]
                matching=sorted([c for c in claims if c['identity']==identity],key=lambda c:c['attempt'])
                for claim in matching:
                    previous=self.ledger.checked(db.execute("SELECT payload,sha256 FROM events WHERE kind='tool_result' AND key=?",(claim['claim_id'],)).fetchone())
                    if previous is None: raise AgentBlocked('UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION')
                    # Backend retries are bounded inside the adapters. A recorded
                    # result is reused; the Agent cannot repeat an external effect.
                    db.rollback(); return None,previous['public']
                if not host_finalizing and len(claims)>=self.config['limits']['max_tool_calls']: raise AgentBlocked('TOOL_CALL_BUDGET_EXHAUSTED')
                attempt=len(matching)+1
                if attempt>self.config['limits']['max_attempts_per_tool']: raise AgentBlocked('TOOL_ATTEMPT_BUDGET_EXHAUSTED')
                sequence=len(claims)+1; key=digest(dict(run_id=self.run_id,identity=identity,attempt=attempt))
                value=dict(run_id=self.run_id,claim_id=key,identity=identity,tool=tool,arguments=arguments,
                           sequence=sequence,attempt=attempt,host_finalizing=host_finalizing,
                           at=self.clock().astimezone(timezone.utc).isoformat())
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('tool_claim',key,canonical(value),digest(value)))
                db.commit(); return value,None
            except BaseException: db.rollback(); raise

    def call_tool(self,name,arguments):
        return self._invoke_tool(name,arguments)

    def finalize_report(self):
        """One host-only closeout, even when model/time/tool budgets are spent.

        Code/config/clock/integrity constraints still apply. This method is not
        a function tool and cannot execute a model or a network operation.
        """
        if self.ledger.read('execution_result',self.run_id) is None:
            raise AgentBlocked('EXECUTION_RESULT_REQUIRED_BEFORE_FINALIZATION')
        return self._invoke_tool('deliver_report',{},host_finalizing=True)

    def _invoke_tool(self,name,arguments,*,host_finalizing=False):
        # Validate before counting, accessing data, or invoking any dependency.
        arguments=validate_call(name,arguments)
        self._guard(enforce_time=not host_finalizing)
        claim,cached=self._claim_tool(name,arguments,host_finalizing=host_finalizing)
        if cached is not None: return deepcopy(cached)
        try:
            evidence,public=self._perform(name,arguments)
            self._guard(enforce_time=not host_finalizing)
        except Exception as exc:
            evidence=dict(status='BLOCKED_TOOL_ERROR',reason=_error_code(exc),error=type(exc).__name__)
            public=dict(status='BLOCKED_TOOL_ERROR',reason=_error_code(exc))
        public=dict(public,evidence_id=claim['claim_id'],**BOUNDARY)
        row=dict(claim,completed_at=self.clock().astimezone(timezone.utc).isoformat(),
                 evidence=evidence,evidence_sha256=digest(evidence),public=public)
        self.ledger.append('tool_result',claim['claim_id'],row)
        return deepcopy(public)

    def _perform(self,name,args):
        if name=='discover_sources':
            value=discovery.run_discovery(self.config['discovery'],self.run_root/'d')
            proof=discovery.verify_discovery(Path(value['receipt_path']).parent)
            return value,dict(status=value['status'],scope='DISCOVERY_ONLY_UNTRUSTED_URLS',
                              response_count=len(value.get('events',[])),candidate_count=len(value.get('candidates',[])),
                              receipt_integrity=proof['status'])
        if name=='verify_official_sources':
            games=workflow.history_stage(self.config,self.run_root,self.clock())
            checked=all(games[g].get('status')=='HISTORY_CHECKED' for g in ('SSQ','DLT'))
            public={g:dict(status=v['status'],rows=len(v.get('rows',[])),latest_issue=v.get('rows',[{}])[-1].get('issue'),
                           reason=v.get('reason')) for g,v in games.items()}
            # Do not send adapter messages or local paths to a language model.
            for value in public.values():
                if value['reason'] is not None: value['reason']=_error_code(AgentBlocked(value['reason']))
            return dict(status='HISTORY_CHECKED' if checked else 'BLOCKED',games=games),dict(
                status='HISTORY_CHECKED' if checked else 'BLOCKED',games=public,
                publication_asof_verified=False,next_legal_issue=None)
        if name=='run_frozen_models':
            verified=self._result('verify_official_sources')
            if not verified or verified['evidence'].get('status')!='HISTORY_CHECKED':
                raise AgentBlocked('OFFICIAL_HISTORY_VERIFICATION_REQUIRED')
            games={}
            for game,data in verified['evidence']['games'].items():
                if data['sha256']!=digest(data['rows']): raise AgentBlocked('FROZEN_HISTORY_SHA_MISMATCH')
                rows=sources.validate_history(game,data['rows'],self.clock())
                workflow.validate_issue_sequence(game,rows)
                prediction=models.generate(game,'UNASSIGNED',rows)
                models.validate_prediction(prediction)
                games[game]=prediction
            value=dict(status='NON_FORMAL_RESEARCH_UNASSIGNED',games=games,
                       official_history_evidence=verified['claim_id'],registry=models.registry())
            return value,dict(status=value['status'],games={g:dict(
                model_count=len(v['models']),primary_model=v['primary_model'],
                primary_D2=v['primary_d2'],issue='UNASSIGNED') for g,v in games.items()})
        if name=='audit_experiment': return self._audit(args)
        if name=='deliver_report': return self._deliver()
        raise AgentBlocked('TOOL_NOT_ALLOWED')

    def _audit(self,args):
        action=args['action']
        if action=='inspect':
            integrity=self.ledger.integrity()
            replay=replay_ready(Store(self.root/'replay.sqlite3'))
            value=dict(status='AUDIT_CHECKED',ledger_integrity=integrity,code_pin='PASS',replay=replay,
                       old_locked_test_rescored=False,formal_eight_slots='BLOCKED_UNAVAILABLE',
                       official_next_issue='BLOCKED_NO_EXPLICIT_TARGET_DEADLINE',
                       prospective_evidence='BLOCKED_NO_EXTERNAL_TSA_OR_APPROVAL',
                       random_null={'SSQ':'15/528','DLT':'10/595'},
                       known_quarantines=quarantine_registry(),model_selection=selection_result([]),
                       hypothesis_count=len(self._rows('hypothesis')))
            return value,deepcopy(value)
        if action=='register_hypothesis':
            hypothesis=parse(args['hypothesis_json'])
            existing=self._rows('hypothesis')
            if existing: raise AgentBlocked('ONE_REGISTERED_HYPOTHESIS_PER_RUN')
            hid=digest(dict(run_id=self.run_id,hypothesis=hypothesis))
            value=dict(run_id=self.run_id,hypothesis_id=hid,hypothesis=hypothesis,
                       code_sha256=digest(self.pin),parameters_sha256=digest(hypothesis['parameters']),
                       registered_at=self.clock().astimezone(timezone.utc).isoformat(),
                       registered_before_execution=True,scope='RESEARCH_ONLY_LOCAL_RECORD_NOT_TSA')
            # A single key also enforces the limit across concurrent workers.
            self.ledger.append('hypothesis',self.run_id,value)
            return value,dict(status='HYPOTHESIS_REGISTERED',hypothesis_id=hid,kind=hypothesis['kind'],
                              scope=value['scope'])
        items=self._rows('hypothesis')
        if len(items)!=1: raise AgentBlocked('EXACTLY_ONE_REGISTERED_HYPOTHESIS_REQUIRED')
        item=items[0]
        if item['code_sha256']!=digest(self.pin): raise AgentBlocked('EXPERIMENT_CODE_DRIFT')
        from .experiments import run_diagnostic
        result=run_diagnostic(item['hypothesis']['kind'],item['hypothesis']['parameters'])
        value=dict(run_id=self.run_id,hypothesis_id=item['hypothesis_id'],result=result,
                   executed_at=self.clock().astimezone(timezone.utc).isoformat())
        self.ledger.append('experiment',item['hypothesis_id'],value)
        public=dict(status=result['status'],hypothesis_id=item['hypothesis_id'],
                    classification=result.get('classification'),historical_outcomes_used=False,
                    locked_test_rescored=False)
        return value,public

    def evidence_report(self):
        snapshot=self.snapshot(); checked=snapshot['verify_official_sources']; prediction=snapshot['run_frozen_models']
        games={}
        for game in ('SSQ','DLT'):
            data=checked['evidence'].get('games',{}).get(game,{}) if checked else {}
            pred=prediction['evidence'].get('games',{}).get(game) if prediction else None
            games[game]=dict(status='NON_FORMAL_RESEARCH_UNASSIGNED' if pred else 'BLOCKED',
                reason='OFFICIAL_NEXT_ISSUE_DEADLINE_AND_TRUSTED_PREFREEZE_UNAVAILABLE',
                history_status=data.get('status','NOT_RUN'),history_sha256=data.get('sha256'),
                latest_completed_issue=data.get('rows',[{}])[-1].get('issue'),
                sample_count=len(data.get('rows',[])),prediction=pred)
        execution=self.ledger.read('execution_result',self.run_id)
        runtime=execution['result'] if execution else {'status':'IN_PROGRESS'}
        # Model-authored text is never incorporated into the evidence report.
        runtime={k:v for k,v in runtime.items() if k in ('status','mode','paid_api_calls','model_calls','reason','error','usage','estimated_usd')}
        return dict(schema='GLP_RESEARCH_AGENT_REPORT_1',run_id=self.run_id,run_key=self.run_key,
                    due_slot=self.due_slot,created_at=self.created_at,execution_mode=self.mode,
                    sdk_model=self.sdk_model,sdk_runtime=runtime,
                    config_sha256=self.config_sha,code_sha256=digest(self.pin),games=games,
                    tool_receipts={k:(v['public'] if v else {'status':'NOT_RUN'}) for k,v in snapshot.items()},
                    hypotheses=self._rows('hypothesis'),experiments=self._rows('experiment'),
                    known_quarantines=quarantine_registry(),model_selection=selection_result([]),
                    model_calls=self._rows('model_claim'),model_usage=self._rows('model_result'),
                    mail_status='QUEUE_PREPARATION_PENDING' if self.config['recipient'] else 'NOT_CONFIGURED',
                    deadline_enforcement='COOPERATIVE_TOOLS_AND_HTTP_TIMEOUT_NOT_OS_KILL',
                    cost_enforcement='LOCAL_CONSERVATIVE_ESTIMATE_NOT_PROVIDER_BILLING_CAP',
                    evidence_conclusion='NO_PROVEN_D2_IMPROVEMENT',**BOUNDARY)

    def _deliver(self):
        report=self.evidence_report(); raw=(canonical(report)+'\n').encode('utf-8'); rid=digest(report)
        directory=self.run_root/'reports'/rid[:16]
        body=render_html(report); files={}
        for name,data in (('report.json',raw),('report.html',body.encode('utf-8'))):
            files[name]=exclusive(directory/name,data)
        queue_id=None; final=self.ledger.read('execution_result',self.run_id) is not None
        if self.config['recipient'] and final:
            queue_id=self._queue_report(report,body)
        value=dict(status='REPORT_SAVED',report_id=rid,report_dir=str(directory),files=files,
                   report_sha256=rid,outbox_id=queue_id,delivery='QUEUED_ONLY' if queue_id else ('NOT_FINALIZED_PENDING' if self.config['recipient'] else 'NOT_CONFIGURED'))
        self.ledger.append('report',rid,dict(run_id=self.run_id,**value))
        return value,dict(status='REPORT_SAVED',report_id=rid,file_count=len(files),delivery=value['delivery'])

    def _queue_report(self,report,body):
        from email.message import EmailMessage
        rid=digest(report); recipient=self.config['recipient']
        key=digest(dict(run_id=self.run_id,report_sha256=rid,recipient=recipient))
        item=dict(id=key,recipient=recipient,report_sha256=rid,
                  subject='SSQ＋DLT V4.5 Agent 非正式研究／阻斷狀態',html=body)
        msg=EmailMessage(); msg['To']=recipient; msg['Subject']=item['subject']
        msg['Message-ID']=f'<{key}@glp.local>'
        msg.set_content('非正式研究；A=0 / NO_EDGE；下一合法期 BLOCKED。')
        msg.add_alternative(body,subtype='html'); msg.set_boundary('GLP-AGENT-'+key)
        raw=msg.as_bytes(); item['eml_sha256']=exclusive(self.root/'mail'/(key+'.eml'),raw)
        self.ledger.append('outbox',key,item)
        return key

    def begin_model_call(self,estimated_input_tokens,max_output_tokens):
        self._guard(); limits=self.config['sdk']
        if type(estimated_input_tokens) is not int or estimated_input_tokens<0 or estimated_input_tokens>limits['max_input_tokens']:
            raise AgentBlocked('MODEL_INPUT_BUDGET_EXHAUSTED')
        if type(max_output_tokens) is not int or not 1<=max_output_tokens<=limits['max_output_tokens']:
            raise AgentBlocked('MODEL_OUTPUT_BUDGET_EXHAUSTED')
        simulated=self.mode=='SDK_SIMULATED_MODEL'
        if not simulated and self.mode!='SDK_LIVE_MODEL': raise AgentBlocked('MODEL_NOT_ALLOWED_IN_THIS_MODE')
        rate_in=limits['input_usd_per_million']; rate_out=limits['output_usd_per_million']
        if not simulated and (rate_in is None or rate_out is None): raise AgentBlocked('EXPLICIT_MODEL_PRICES_REQUIRED')
        reserve=0 if simulated else (limits['max_input_tokens']*rate_in+max_output_tokens*rate_out)/1_000_000
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                rows=[self.ledger.checked(r) for r in db.execute("SELECT payload,sha256 FROM events WHERE kind='model_claim'")]
                rows=[r for r in rows if r['run_id']==self.run_id]
                for row in rows:
                    outcome=self.ledger.checked(db.execute("SELECT payload,sha256 FROM events WHERE kind='model_result' AND key=?",(row['claim_id'],)).fetchone())
                    if not outcome or outcome['status']!='ACCOUNTED': raise AgentBlocked('UNKNOWN_MODEL_OUTCOME_REQUIRES_RECONCILIATION')
                    if outcome.get('reservation_exceeded'): raise AgentBlocked('MODEL_USAGE_EXCEEDED_RESERVATION')
                if len(rows)>=limits['max_model_calls']: raise AgentBlocked('MODEL_CALL_BUDGET_EXHAUSTED')
                if sum(r['reserved_usd'] for r in rows)+reserve>limits['max_estimated_usd']+1e-12:
                    raise AgentBlocked('ESTIMATED_COST_BUDGET_EXHAUSTED')
                key=digest(dict(run_id=self.run_id,sequence=len(rows)+1))
                value=dict(run_id=self.run_id,claim_id=key,sequence=len(rows)+1,mode=self.mode,
                           estimated_input_tokens=estimated_input_tokens,reserved_input_tokens=limits['max_input_tokens'],
                           reserved_output_tokens=max_output_tokens,reserved_usd=reserve,
                           at=self.clock().astimezone(timezone.utc).isoformat())
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('model_claim',key,canonical(value),digest(value)))
                db.commit(); self._current_model_claim=value
            except BaseException:db.rollback(); raise

    def finish_model_call(self,usage):
        claim=self._current_model_claim
        if claim is None: raise AgentBlocked('MODEL_CALL_NOT_RESERVED')
        for name in ('input_tokens','output_tokens','total_tokens'):
            if type(usage.get(name)) is not int or usage[name]<0: raise AgentBlocked('INVALID_MODEL_USAGE')
        if usage['total_tokens']<usage['input_tokens']+usage['output_tokens']: raise AgentBlocked('INVALID_MODEL_USAGE')
        limits=self.config['sdk']; simulated=self.mode=='SDK_SIMULATED_MODEL'
        cost=0 if simulated else (usage['input_tokens']*limits['input_usd_per_million']+usage['output_tokens']*limits['output_usd_per_million'])/1_000_000
        value=dict(run_id=self.run_id,claim_id=claim['claim_id'],status='ACCOUNTED',usage=deepcopy(usage),
                   estimated_usd=cost,paid_api_calls=0 if simulated else 1,
                   reservation_exceeded=usage['input_tokens']>claim['reserved_input_tokens'] or usage['output_tokens']>claim['reserved_output_tokens'])
        self.ledger.append('model_result',claim['claim_id'],value); self._current_model_claim=None

    def mark_model_call_unknown(self):
        claim=self._current_model_claim
        if claim is not None:
            self.ledger.append('model_result',claim['claim_id'],dict(run_id=self.run_id,claim_id=claim['claim_id'],
                               status='UNKNOWN_REQUIRES_RECONCILIATION',paid_api_calls=None))
            self._current_model_claim=None

    def claim_execution(self):
        self._guard()
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old=self.ledger.checked(db.execute("SELECT payload,sha256 FROM events WHERE kind='execution' AND key=?",(self.run_id,)).fetchone())
                if old:
                    result=self.ledger.checked(db.execute("SELECT payload,sha256 FROM events WHERE kind='execution_result' AND key=?",(self.run_id,)).fetchone())
                    if result is None: raise AgentBlocked('UNKNOWN_EXECUTION_OUTCOME_REQUIRES_RECONCILIATION')
                    db.rollback(); return result
                value=dict(run_id=self.run_id,mode=self.mode,started_at=self.clock().isoformat())
                db.execute('INSERT INTO events VALUES(?,?,?,?)',('execution',self.run_id,canonical(value),digest(value)))
                db.commit(); return None
            except BaseException:db.rollback(); raise

    def finish_execution(self,result):
        value=dict(run_id=self.run_id,mode=self.mode,result=deepcopy(result),finished_at=self.clock().isoformat())
        self.ledger.append('execution_result',self.run_id,value)
        return value


def render_html(report):
    if (report.get('known_quarantines')!=quarantine_registry()
            or report.get('model_selection')!=selection_result([])):
        raise AgentBlocked('QUARANTINE_REPORT_BOUNDARY_MISMATCH')
    esc=lambda value:html.escape(str(value),quote=True)
    rows=[]; model_tables=[]
    for game,data in report['games'].items():
        prediction=data.get('prediction'); primary=prediction.get('primary_d2') if prediction else '未運行'
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in
                    (game,data['status'],data['sample_count'],data['latest_completed_issue'],primary,'UNASSIGNED / BLOCKED'))+'</tr>')
        if prediction:
            entries=[]
            for name,model in prediction['models'].items():
                values=[name,model['version']]+[model['dan'][str(k)] for k in range(1,6)]+[model['ticket']['front'],model['ticket']['back']]
                entries.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
            model_tables.append('<h3>'+esc(game)+' 固定版本研究號碼</h3><div style="overflow:auto"><table><tr><th>模型</th><th>版本</th><th>D1</th><th>D2</th><th>D3</th><th>D4</th><th>D5</th><th>單式前區</th><th>後區</th></tr>'+''.join(entries)+'</table></div>')
    tools=''.join('<tr><td>'+esc(k)+'</td><td>'+esc(v.get('status'))+'</td></tr>' for k,v in report['tool_receipts'].items())
    experiments=report['experiments']; diagnostic='尚未執行隔離診斷'
    if experiments:
        diagnostic='；'.join(esc(x['result'].get('status'))+' / '+esc(x['result'].get('classification')) for x in experiments)
    details=esc(canonical(report))
    return ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>SSQ＋DLT V4.5 研究與交付 Agent</title><style>body{font:16px/1.65 system-ui;background:#f3f5f8;color:#182338;margin:0;padding:28px}main{max-width:1100px;margin:auto}h1{font-size:28px}.card{background:white;padding:22px;border-radius:14px;margin:18px 0}.badge{background:#fff0d4;padding:10px;border-radius:8px}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #dde3ec}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}code{overflow-wrap:anywhere}@media(max-width:700px){body{padding:12px}.card{padding:12px}table{font-size:12px}td,th{padding:5px}}</style>'
      '<main><h1>SSQ＋DLT V4.5｜研究與交付 Agent</h1><p class="badge">非正式研究 · A=0 · NO_EDGE · 下一合法期 BLOCKED</p>'
      '<div class="card"><b>沒有證明 D2 命中率提升。</b><p>固定程式管理選號、統計與准入；Agent 只能安排五組工具。未取得正式批准、可信事前封存及全新前瞻證據。正式八槽未替換。</p>'
      '<p>運行模式：<b>'+esc(report['execution_mode'])+'</b>。SDK_SIMULATED_MODEL 表示使用真正 SDK 執行迴圈與預設模擬模型，沒有呼叫付費模型；TOOLS_SMOKE_NO_MODEL 表示直接驗證工具。</p>'
      '<p>郵件狀態：'+esc(report['mail_status'])+'，此 Agent 僅建立待發佇列。費用採本地保守預留；工具截止為合作式檢查，並非可強制終止程序。</p></div>'
      '<div class="card"><h2>原負控制隔離</h2><p>原來源試驗的 69／2880 為合成負控制，重現 PASS 不會清除科學反證 FAIL。根因仍 UNRESOLVED，該來源計畫及其派生證據不得晉級。隔離按精確計畫與來源譜系判定，不以模型同名封禁無關版本。</p><p>目前沒有正式准入的新主要挑戰者；原正式12項缺件，不能拿研究家族或合成負控12項代替。</p></div>'
      '<div class="card"><h2>本輪研究</h2><table><tr><th>彩種</th><th>狀態</th><th>歷史期數</th><th>最新完成期</th><th>主 D2</th><th>目標期</th></tr>'+''.join(rows)+'</table>'
      '<p>主 D2 只是固定版本的未指派期別研究輸出，不能視為可購彩的下一期預測。隨機基準：SSQ 15/528；DLT 10/595；合格前瞻樣本 0。</p>'+''.join(model_tables)+'</div>'
      '<div class="card"><h2>工具證據</h2><table>'+tools+'</table><p>'+diagnostic+'</p>'
      '<p>均勻收縮只改變相同的分數尺度；排序不變不能算作預測能力改善。歷史封存測試集沒有重用或重新評分。</p></div>'
      '<div class="card"><h2>追溯</h2><p>Run '+esc(report['run_id'])+'</p><p>程式 SHA '+esc(report['code_sha256'])+'</p><details><summary>完整本地報告</summary><pre>'+details+'</pre></details></div></main></html>')
