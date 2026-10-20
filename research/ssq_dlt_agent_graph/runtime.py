"""LangGraph checkpoints coordinate work; immutable receipts own the facts."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import TypedDict
import json,sqlite3,uuid

from .journal import GraphBlocked,Journal,canonical,digest,process_lock
from . import settings
from .memory import MemoryStore

CHECKPOINT_APP_ID=0x47434731


class State(TypedDict,total=False):
    header_sha256:str
    step_refs:dict
    phase:str
    reason:str


def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:
        f.write(canonical(value)+'\n');f.flush()
        __import__('os').fsync(f.fileno())


def error_code(exc):
    value=str(exc)
    return value if __import__('re').fullmatch('[A-Z][A-Z0-9_]{1,120}',value) else type(exc).__name__


class GraphRunner:
    def __init__(self,config,thread_id,*,clock=None,host_factory=None,parent_thread_id=None):
        self.config=settings.validate(config)
        if type(thread_id) is not str or not __import__('re').fullmatch('[A-Za-z0-9_.:-]{1,100}',thread_id):raise GraphBlocked('INVALID_GRAPH_THREAD_ID')
        if parent_thread_id is not None and parent_thread_id==thread_id:raise GraphBlocked('PARENT_THREAD_MUST_DIFFER')
        self.thread_id=thread_id;self.parent_thread_id=parent_thread_id
        self.root=Path(self.config['root']);self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.host_factory=host_factory;self.injected=host_factory is not None

    def _now(self):return settings.aware(self.clock())
    def _key(self,stage):return self.thread_id+'|'+stage
    def _clock_floor(self):
        now=self._now()
        for event in self.journal.rows('clock'):
            if datetime.fromisoformat(event['at'])>now:raise GraphBlocked('GRAPH_CLOCK_REWIND')
        self.journal.append('clock',uuid.uuid4().hex,dict(at=now.isoformat()))
        return now

    def _guard(self,*,execute=True):
        if settings.identity(self.config)!=self.header['identity']:raise GraphBlocked('GRAPH_IDENTITY_CHANGED')
        self.journal.integrity();now=self._clock_floor()
        if execute and now>=datetime.fromisoformat(self.header['deadline']):raise GraphBlocked('DURABLE_GRAPH_DEADLINE_EXHAUSTED')
        if self.host.pin()!=self.header['host_pin']:raise GraphBlocked('GRAPH_HOST_IDENTITY_CHANGED')

    def _open(self):
        marker=self.root/'GRAPH_APPLICATION.json'
        if not marker.exists():
            if any(p.name!='process.lock' for p in self.root.iterdir()):raise GraphBlocked('NEW_GRAPH_ROOT_REQUIRED')
            write_new(marker,dict(application='SSQ_DLT_AGENT_GRAPH_1'))
        if json.loads(marker.read_bytes())!={'application':'SSQ_DLT_AGENT_GRAPH_1'}:raise GraphBlocked('FOREIGN_GRAPH_ROOT')
        self.journal=Journal(self.root/'evidence.sqlite3')
        current=settings.identity(self.config)
        old=self.journal.read('run',self.thread_id)
        if old and (old['identity']!=current or old['injected_host']!=self.injected or old['parent_thread_id']!=self.parent_thread_id):raise GraphBlocked('GRAPH_RUN_IDENTITY_CHANGED')
        if old is None:
            for other in self.journal.rows('run'):
                end=self.journal.read('terminal',other['thread_id'])
                if end is None:raise GraphBlocked('OTHER_UNFINISHED_THREAD_REQUIRES_RESUME')
                if end['status']=='RECONCILIATION_REQUIRED':raise GraphBlocked('OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION')
                if end['status']=='BLOCKED' and self.parent_thread_id is None:raise GraphBlocked('KNOWN_BLOCKED_REQUIRES_CHILD_VERIFICATION')
        now=self._clock_floor()
        if self.host_factory is None:
            from .host import LegacyHost
            self.host_factory=LegacyHost
        self.host=self.host_factory(self.config['host'],'GRAPH:'+self.thread_id,clock=self.clock)
        if old is None:
            if self.host.pending_unknown_in_graph_root():raise GraphBlocked('OTHER_UNKNOWN_OUTCOME_REQUIRES_RECONCILIATION')
            parent=None
            if self.parent_thread_id is not None:
                parent=self.journal.read('run',self.parent_thread_id)
                terminal=self.journal.read('terminal',self.parent_thread_id)
                if not parent or not terminal or terminal['status']!='BLOCKED':raise GraphBlocked('ONLY_KNOWN_BLOCKED_PARENT_CAN_FORK')
                if parent['identity']['source_manifest']!=current['source_manifest'] or parent['identity']['dependency_versions']!=current['dependency_versions']:raise GraphBlocked('PARENT_CODE_OR_RUNTIME_CHANGED')
                old_sha={k:v['sha256'] for k,v in parent['identity']['input_manifest'].items()}
                new_sha={k:v['sha256'] for k,v in current['input_manifest'].items()}
                if old_sha==new_sha:raise GraphBlocked('NEW_PINNED_SOURCE_EVIDENCE_REQUIRED')
                if parent['limits']!=self.config['limits']:raise GraphBlocked('FAMILY_BUDGET_CANNOT_CHANGE')
            self.header=dict(thread_id=self.thread_id,parent_thread_id=self.parent_thread_id,
                family_id=parent['family_id'] if parent else self.thread_id,
                identity=current,host_pin=self.host.pin(),injected_host=self.injected,
                started_at=now.isoformat(),deadline=parent['deadline'] if parent else (now+timedelta(seconds=self.config['limits']['max_wall_seconds'])).isoformat(),
                limits=self.config['limits'],**settings.BOUNDARY)
            self.journal.append('run',self.thread_id,self.header)
        else:
            self.header=old
            if self.host.pin()!=old['host_pin']:raise GraphBlocked('GRAPH_HOST_IDENTITY_CHANGED')
        self.memory=MemoryStore(self.root/'memory.sqlite3',forbidden_paths=[self.root/'checkpoints.sqlite3',self.root/'evidence.sqlite3',self.root/'host/agent.sqlite3'])

    def _reserve(self,stage):
        self._guard()
        key=self._key(stage)
        if self.journal.read('reservation',key):return
        reservations=[r for r in self.journal.rows('reservation') if r['family_id']==self.header['family_id']]
        if len(reservations)>=self.header['limits']['max_stage_calls']:raise GraphBlocked('DURABLE_STAGE_BUDGET_EXHAUSTED')
        self.journal.append('reservation',key,dict(thread_id=self.thread_id,family_id=self.header['family_id'],stage=stage,at=self._now().isoformat()))

    def _validate_state(self,state):
        if state.get('header_sha256')!=digest(self.header):raise GraphBlocked('CHECKPOINT_HEADER_MISMATCH')
        refs=state.get('step_refs',{})
        if type(refs) is not dict or set(refs)-set(settings.STAGES):raise GraphBlocked('CHECKPOINT_UNKNOWN_STAGE')
        for stage,checksum in refs.items():
            row=self.journal.read('step',self._key(stage))
            if row is None or digest(row)!=checksum:raise GraphBlocked('CHECKPOINT_RECEIPT_MISMATCH')

    def _stored(self,stage):return self.journal.read('step',self._key(stage))
    def _save_step(self,stage,result,state):
        value=dict(thread_id=self.thread_id,stage=stage,result=result)
        self.journal.append('step',self._key(stage),value)
        return dict(step_refs={**state.get('step_refs',{}),stage:digest(value)},phase='RUNNING',reason='')

    def _blocked(self,state,stage,reason,*,unknown=False):
        # A failure while writing a tool result may follow an actual effect.
        # The exception's name cannot establish that it is safe to repeat.
        trigger_reason=reason
        try:
            if self.host.pending_unknown():
                unknown=True
                reason='UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION'
        except Exception:
            unknown=True
            reason='HOST_OUTCOME_NOT_VERIFIABLE_REQUIRES_RECONCILIATION'
        result=dict(status='RECONCILIATION_REQUIRED' if unknown else 'BLOCKED',blocked_node=stage,reason=reason,
                    thread_id=self.thread_id,parent_thread_id=self.parent_thread_id,trigger_reason=trigger_reason,
                    graph_header_sha256=digest(self.header),paid_api_calls=0,model_calls=0,**settings.BOUNDARY)
        self.journal.append('terminal',self.thread_id,result)
        return dict(phase=result['status'],reason=reason)

    def _source_guard(self):
        from research.ssq_dlt_d2_forensics_evidence.coverage import load_raw_pair
        from research.ssq_dlt_v45.sources import load_pinned
        from research.ssq_dlt_v45.workflow import validate_issue_sequence
        games={}
        for game in ('SSQ','DLT'):
            left,right=self.config['sources'][game]
            recent,proof=load_raw_pair(game,left['path'],left['sha256'],right['path'],right['sha256'],self._now())
            archive=load_pinned(game,self.config['host']['history'][game],self._now())
            validate_issue_sequence(game,archive)
            lookup={r['issue']:r for r in archive}
            if archive[-1]['issue']!=recent[-1]['issue']:raise GraphBlocked('PINNED_ARCHIVE_MUST_MATCH_VERIFIED_LATEST')
            if any(row['issue'] not in lookup or row!=lookup[row['issue']] for row in recent):raise GraphBlocked('RAW_SOURCE_VS_ARCHIVE_CONFLICT')
            games[game]=dict(coverage=proof,archive_count=len(archive),archive_sha256=self.config['host']['history'][game]['sha256'])
        return dict(status='PASS_CACHED_SOURCE_GUARD_ONLY',games=games,publication_asof_verified=False,**settings.BOUNDARY)

    def _memory_evidence(self):
        return dict(status='MEMORY_RETRIEVAL_COMPLETED_DATA_ONLY',queries=[self.memory.retrieve_evidence(
            key=query['key'],scope=query['scope'],as_of=self._now()) for query in self.config['memory_queries']],
            authorizes_tools=False,authorizes_formal_publication=False)

    def _node(self,stage):
        def execute(state):
            try:
                self._validate_state(state);self._guard()
                for predecessor in settings.STAGES[:settings.STAGES.index(stage)]:
                    if self._stored(predecessor) is None:raise GraphBlocked('PLAN_PREDECESSOR_RECEIPT_REQUIRED')
                old=self._stored(stage)
                if old is not None:
                    if stage in settings.TOOL_ARGUMENTS:
                        native=self.host.lookup(stage,settings.TOOL_ARGUMENTS[stage])
                        if native['state']!='KNOWN' or native['result']!=old['result']:raise GraphBlocked('GRAPH_STEP_VS_HOST_RECEIPT_MISMATCH')
                    return dict(step_refs={**state.get('step_refs',{}),stage:digest(old)},phase='RUNNING',reason='')
                self._reserve(stage)
                if stage=='source_guard':result=self._source_guard()
                elif stage=='memory':result=self._memory_evidence()
                else:
                    if stage=='deliver_report':self.host.prepare_delivery()
                    args=settings.TOOL_ARGUMENTS[stage];native=self.host.lookup(stage,args)
                    if native['state']=='UNKNOWN':raise GraphBlocked('UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION')
                    result=native['result'] if native['state']=='KNOWN' else self.host.call_tool(stage,args)
                    native=self.host.lookup(stage,args)
                    if native['state']!='KNOWN' or native['result']!=result:raise GraphBlocked('HOST_RESULT_NOT_PROVEN_BY_LEDGER')
                    if result.get('status')!=settings.EXPECTED[stage]:
                        return self._blocked(state,stage,result.get('reason','HOST_TOOL_BLOCKED'))
                self._guard()
                return self._save_step(stage,result,state)
            except Exception as exc:
                reason=error_code(exc)
                return self._blocked(state,stage,reason,unknown='UNKNOWN' in reason or 'RECONCILIATION' in reason)
        return execute

    def _gate(self,state):
        try:
            self._validate_state(state);self._guard()
            for stage in settings.STAGES[:-1]:
                if self._stored(stage) is None:raise GraphBlocked('COMPLETION_REQUIRES_EVERY_STAGE_RECEIPT')
            for stage,args in settings.TOOL_ARGUMENTS.items():
                native=self.host.lookup(stage,args)
                if native['state']!='KNOWN' or native['result']!=self._stored(stage)['result']:raise GraphBlocked('FINAL_HOST_RECEIPT_MISMATCH')
            report=self.host.read_report()
            result=dict(status='COMPLETED_RESEARCH_ONLY',thread_id=self.thread_id,parent_thread_id=self.parent_thread_id,
                graph_header_sha256=digest(self.header),report={k:v for k,v in report.items() if k not in ('report_json','report_html')},
                publication='BLOCKED',planning='DETERMINISTIC_NO_MODEL_CALLS',paid_api_calls=0,model_calls=0,
                memory_summary=self._stored('memory')['result'],**settings.BOUNDARY)
            self.journal.append('terminal',self.thread_id,result)
            return dict(phase='COMPLETED_RESEARCH_ONLY',reason='OFFICIAL_ADMISSION_STILL_BLOCKED')
        except Exception as exc:return self._blocked(state,'gate',error_code(exc))

    def run(self,*,resume=False,stop_after=None):
        if stop_after is not None and stop_after not in settings.STAGES[:-1]:raise GraphBlocked('UNKNOWN_STOP_AFTER_STAGE')
        # Refuse foreign directories before creating even the process lock.
        if self.root.exists() and not (self.root/'GRAPH_APPLICATION.json').is_file():
            if any(p.name!='process.lock' for p in self.root.iterdir()):raise GraphBlocked('NEW_GRAPH_ROOT_REQUIRED')
        self.root.mkdir(parents=True,exist_ok=True)
        with process_lock(self.root/'process.lock'):
            self._open();self._guard(execute=False)
            terminal=self.journal.read('terminal',self.thread_id)
            if terminal is not None:
                if terminal['status']=='COMPLETED_RESEARCH_ONLY':
                    for stage in settings.STAGES[:-1]:
                        if self._stored(stage) is None:raise GraphBlocked('COMPLETED_THREAD_MISSING_STAGE_RECEIPT')
                    for stage,args in settings.TOOL_ARGUMENTS.items():
                        native=self.host.lookup(stage,args)
                        if native['state']!='KNOWN' or native['result']!=self._stored(stage)['result']:raise GraphBlocked('COMPLETED_THREAD_HOST_RECEIPT_MISMATCH')
                    report=self.host.read_report()
                    if {k:v for k,v in report.items() if k not in ('report_json','report_html')}!=terminal['report']:raise GraphBlocked('COMPLETED_THREAD_REPORT_MISMATCH')
                return terminal
            pending=self.host.pending_unknown()
            if pending:
                initial=dict(header_sha256=digest(self.header),step_refs={},phase='RUNNING',reason='')
                self._blocked(initial,'restore','UNKNOWN_TOOL_OUTCOME_REQUIRES_RECONCILIATION',unknown=True)
                return self.journal.read('terminal',self.thread_id)
            from langgraph.graph import StateGraph,START,END
            from langgraph.checkpoint.sqlite import SqliteSaver
            path=self.root/'checkpoints.sqlite3';is_new=not path.exists()
            with closing(sqlite3.connect(str(path),check_same_thread=False)) as db:
                app=db.execute('PRAGMA application_id').fetchone()[0]
                if (not is_new and app!=CHECKPOINT_APP_ID) or (is_new and app!=0):raise GraphBlocked('FOREIGN_GRAPH_CHECKPOINT_DB')
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise GraphBlocked('CHECKPOINT_SQLITE_INTEGRITY_FAILED')
                db.execute(f'PRAGMA application_id={CHECKPOINT_APP_ID}');db.execute('PRAGMA synchronous=FULL');db.commit()
                saver=SqliteSaver(db);builder=StateGraph(State)
                for stage in settings.STAGES:builder.add_node(stage,self._gate if stage=='gate' else self._node(stage))
                builder.add_edge(START,settings.STAGES[0])
                for index,stage in enumerate(settings.STAGES[:-1]):
                    following=settings.STAGES[index+1]
                    builder.add_conditional_edges(stage,lambda s,next_node=following:next_node if s.get('phase')=='RUNNING' else END)
                builder.add_edge('gate',END)
                graph=builder.compile(checkpointer=saver,interrupt_after=[stop_after] if stop_after else [])
                cfg={'configurable':{'thread_id':self.thread_id}}
                previous=graph.get_state(cfg)
                if previous.values:
                    self._validate_state(previous.values)
                    if not resume:raise GraphBlocked('EXISTING_CHECKPOINT_REQUIRES_EXPLICIT_RESUME')
                    initial=None
                else:
                    if resume:raise GraphBlocked('RESUME_REQUIRES_EXISTING_CHECKPOINT')
                    initial=dict(header_sha256=digest(self.header),step_refs={},phase='RUNNING',reason='')
                graph.invoke(initial,cfg,durability='sync')
                after=graph.get_state(cfg);self._validate_state(after.values)
                terminal=self.journal.read('terminal',self.thread_id)
                if terminal is None:
                    if not after.next:raise GraphBlocked('CHECKPOINT_COMPLETED_WITHOUT_TERMINAL_EVIDENCE')
                    return dict(status='PAUSED_CHECKPOINT',thread_id=self.thread_id,next_nodes=list(after.next),
                        graph_header_sha256=digest(self.header),paid_api_calls=0,model_calls=0,**settings.BOUNDARY)
                return terminal
