"""TEST_ONLY: audit state/control never promotes formal eligibility."""
import contextlib, hashlib, importlib, importlib.util, io, json, sqlite3, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from research.harness_v46 import closed_loop, core

class AuditControlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('research.harness_v46.audit_control'),
                             'existing runner lacks bounded audit task/control implementation')
        self.a=importlib.import_module('research.harness_v46.audit_control')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.ws=self.base/'workspace';self.src=self.base/'source';self.src.mkdir()
        b=b'known owned fixture';(self.src/'fixture.txt').write_bytes(b)
        blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
        self.cap={'head':'a'*40,'tree':'b'*40,'files':[{'path':'fixture.txt','git_blob':blob,'sha256':hashlib.sha256(b).hexdigest()}]}
        (self.src/'source_capture.json').write_text(json.dumps(self.cap),encoding='utf-8')
        (self.src/'source_tree.json').write_text(json.dumps({'sha':'b'*40,'tree':[{'path':'fixture.txt','type':'blob','sha':blob,'mode':'100644'}]}),encoding='utf-8')
        self.actors={'orchestrator':'/root','researcher':'/root/recon','developer':'/root/dev',
                     'executor':'/root/exec','reviewer':'/root/review'}
    def plan(self,key='owned-audit'):
        return self.a.create_session(self.ws,key=key,actors=self.actors,source_root=self.src)
    def test_interpreter_entry_link_pins_physical_binary_without_relaxing_workspace_paths(self):
        physical=self.base/'python-real';physical.write_bytes(b'physical-interpreter-fixture')
        entry=self.base/'python-entry';entry.write_bytes(b'entry-link-fixture')
        resolve=Path.resolve;reparse=self.a._is_reparse
        def resolve_entry(path,*args,**kwargs):
            return physical if path==entry else resolve(path,*args,**kwargs)
        with patch.object(self.a.sys,'executable',str(entry)),patch.object(Path,'resolve',resolve_entry),patch.object(self.a,'_is_reparse',side_effect=lambda path:path==entry or reparse(path)):
            try:pin=self.a._controller_pin()
            except core.GateError as exc:self.fail('trusted process interpreter entry must pin its physical binary: '+str(exc))
            self.assertEqual(pin['interpreter_invocation'],str(entry))
            self.assertEqual(pin['files']['interpreter']['path'],str(physical))
            self.assertEqual(pin['files']['interpreter']['sha256'],hashlib.sha256(physical.read_bytes()).hexdigest())
            with self.assertRaises(core.GateError):self.a._path(entry)
            physical.write_bytes(b'drifted-interpreter-fixture')
            self.assertNotEqual(pin,self.a._controller_pin())
    def execute_session(self,s):
        with patch.object(self.a.shutil,'which',return_value=None):
            return self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
    def conn(self):
        return sqlite3.connect(self.ws/'ledger.sqlite3')
    def test_plan_is_fixed_idempotent_and_role_bound(self):
        s=self.plan();self.assertEqual(s,self.plan())
        self.assertEqual({t['kind'] for t in s['tasks']},{'source_integrity','journal_integrity','intake_integrity','frozen_inventory','container_readiness'})
        other=dict(self.actors,executor='/root/other')
        with self.assertRaises(core.GateError):self.a.create_session(self.ws,key='owned-audit',actors=other,source_root=self.src)
    def test_self_reviewer_and_command_fields_rejected_before_storage(self):
        bad=dict(self.actors,reviewer=self.actors['executor'])
        with self.assertRaises(core.GateError):self.a.create_session(self.ws,key='x',actors=bad,source_root=self.src)
        with self.assertRaises(core.GateError):self.a.dispatch(self.ws,{'operation':'plan','key':'x','actors':self.actors,'command':'whoami & powershell'},source_root=self.src)
        self.assertFalse((self.ws/'ledger.sqlite3').exists())
    def test_old_tables_and_rows_are_preserved(self):
        self.ws.mkdir();c=self.conn();c.executescript("CREATE TABLE prior_predictions(id INTEGER PRIMARY KEY,payload TEXT);INSERT INTO prior_predictions VALUES(1,'original-frozen');")
        c.close();s=self.plan();self.execute_session(s)
        with contextlib.closing(self.conn()) as c:self.assertEqual(c.execute('SELECT * FROM prior_predictions').fetchall(),[(1,'original-frozen')])
    def test_append_only_definitions_events_and_facts(self):
        s=self.plan();self.execute_session(s)
        with contextlib.closing(self.conn()) as c:
            for table in ('agent_audit_sessions','agent_audit_tasks','agent_audit_events','agent_audit_facts'):
                with self.subTest(table=table):
                    for sql in ('UPDATE '+table+' SET payload=payload','DELETE FROM '+table,'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                        with self.assertRaises(sqlite3.DatabaseError):c.execute(sql)
                        c.rollback()
    def test_actual_checks_and_missing_engine_never_grant_deployment(self):
        out=self.execute_session(self.plan())
        by={x['kind']:x for x in out['tasks']}
        self.assertEqual(by['source_integrity']['outcome'],'LOCAL_CHECK_OK')
        self.assertEqual(by['container_readiness']['outcome'],'BLOCKED')
        self.assertIn('DOCKER',by['container_readiness']['result']['reason'])
        self.assertEqual(out['DEPLOYMENT_PASS'],'NOT_VERIFIED');self.assertEqual(out['formal_A'],0)
        self.assertEqual(out['decision'],'NO_EDGE');self.assertFalse(out['role_identity_authenticated'])
    def test_repeat_finished_run_does_not_execute_again(self):
        s=self.plan();self.execute_session(s)
        with patch.object(self.a,'_perform',side_effect=AssertionError('unexpected rerun')):
            self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
    def test_wrong_executor_rejected(self):
        s=self.plan()
        with self.assertRaises(core.GateError):self.a.run_session(self.ws,s['session_id'],actor='/root/wrong')
    def test_crash_claim_is_unknown_and_not_retried(self):
        s=self.plan()
        with patch.object(self.a,'_perform',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
        out=self.a.report_session(self.ws,s['session_id'])
        self.assertTrue(any(x['state']=='UNKNOWN_RUNNING' for x in out['tasks']))
        with patch.object(self.a,'_perform',side_effect=AssertionError('uncertain side effect replayed')):
            self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
    def test_two_concurrent_runs_claim_each_handler_once(self):
        s=self.plan();original=self.a._perform;seen=[]
        def counted(*args,**kwargs):
            seen.append(args[0]);return original(*args,**kwargs)
        with patch.object(self.a,'_perform',side_effect=counted),patch.object(self.a.shutil,'which',return_value=None):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _:self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor']),range(2)))
        self.assertEqual(len(seen),len(set(seen)))
    def test_source_drift_blocks_before_handlers(self):
        s=self.plan();(self.src/'fixture.txt').write_bytes(b'changed after plan')
        with patch.object(self.a,'_perform',side_effect=AssertionError('drift executed')):
            out=self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
        self.assertTrue(any(t['outcome']=='FAILED' and 'SOURCE' in t['result'].get('reason','') for t in out['tasks']))
    def test_changed_evidence_invalidates_report(self):
        s=self.plan();out=self.execute_session(s);t=next(t for t in out['tasks'] if t.get('evidence_path'))
        (self.ws/t['evidence_path']).write_bytes(b'{}')
        with self.assertRaises(core.GateError):self.a.report_session(self.ws,s['session_id'])
    def test_rehashed_wrong_task_identity_rejected(self):
        s=self.plan();self.execute_session(s)
        with contextlib.closing(self.conn()) as c:
            c.execute('DROP TRIGGER agent_audit_events_no_update')
            row=c.execute('SELECT event_id,payload FROM agent_audit_events ORDER BY event_id LIMIT 1').fetchone()
            value=json.loads(row[1]);value['task_id']='V47AT-'+'f'*32
            c.execute('UPDATE agent_audit_events SET payload=?,checksum=? WHERE event_id=?',(core.canon(value),core.digest(value),row[0]));c.commit()
        with self.assertRaises(core.GateError):self.a.report_session(self.ws,s['session_id'])
    def test_review_binds_other_actor_and_exact_aggregate(self):
        s=self.plan();out=self.execute_session(s)
        for actor,digest in [(self.actors['executor'],out['result_digest']),(self.actors['reviewer'],'f'*64)]:
            with self.assertRaises(core.GateError):self.a.record_review(self.ws,s['session_id'],actor=actor,result_digest=digest,note='external claim')
        r=self.a.record_review(self.ws,s['session_id'],actor=self.actors['reviewer'],result_digest=out['result_digest'],note='actual separate review, local record')
        self.assertEqual(r['review_authority'],'NOT_VERIFIED');self.assertEqual(r['formal_A'],0)
    def test_hypothesis_refutation_appends_and_cannot_self_verify(self):
        s=self.plan();out=self.execute_session(s);e=next(t['evidence_id'] for t in out['tasks'] if t.get('evidence_id'))
        with self.assertRaises(core.GateError):self.a.remember(self.ws,s['session_id'],actor=self.actors['researcher'],text='pretend proof',evidence_id=e,status='VERIFIED_LOCAL')
        h=self.a.remember(self.ws,s['session_id'],actor=self.actors['researcher'],text='hypothesis',evidence_id=e,status='HYPOTHESIS')
        f=self.a.remember(self.ws,s['session_id'],actor=self.actors['reviewer'],text='counterexample',evidence_id=e,status='REFUTED',refutes=h['fact_id'])
        report=self.a.report_session(self.ws,s['session_id'])
        facts={x['fact_id']:x for x in report['facts']}
        self.assertEqual(facts[h['fact_id']]['status'],'HYPOTHESIS');self.assertEqual(facts[f['fact_id']]['refutes'],h['fact_id'])
    def test_cross_session_fact_evidence_rejected(self):
        s=self.plan();out=self.execute_session(s);e=next(t['evidence_id'] for t in out['tasks'] if t.get('evidence_id'));other=self.plan('other')
        with self.assertRaises(core.GateError):self.a.remember(self.ws,other['session_id'],actor=self.actors['researcher'],text='launder',evidence_id=e,status='HYPOTHESIS')
    def test_oversized_result_is_incomplete_not_success(self):
        s=self.plan()
        with patch.object(self.a,'_perform',return_value={'outcome':'LOCAL_CHECK_OK','text':'x'*300000}):
            out=self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
        t=next(x for x in out['tasks'] if x.get('evidence_path'))
        self.assertEqual(t['outcome'],'BLOCKED');self.assertFalse(t['capture_complete'])
        for p in (self.ws/'audit_evidence').rglob('*'):
            if p.is_file():self.assertLessEqual(p.stat().st_size,150000)
    def test_wal_or_hot_journal_refused_without_sidecars(self):
        s=self.plan();wal=self.ws/'ledger.sqlite3-wal';wal.write_bytes(b'untrusted WAL')
        with self.assertRaises(core.GateError):self.a.report_session(self.ws,s['session_id'])
        self.assertFalse((self.ws/'ledger.sqlite3-shm').exists());self.assertEqual(wal.read_bytes(),b'untrusted WAL')
    def test_parent_traversal_and_reparse_metadata_refused(self):
        with self.assertRaises(core.GateError):self.a.create_session(self.ws/'..'/'escape',key='x',actors=self.actors,source_root=self.src)
        with patch.object(self.a,'_is_reparse',side_effect=lambda p:Path(p)==self.ws):
            with self.assertRaises(core.GateError):self.plan()
    def test_readonly_report_does_not_change_ledger_or_evidence(self):
        s=self.plan();self.execute_session(s);before={str(p):p.read_bytes() for p in self.ws.rglob('*') if p.is_file()}
        self.a.report_session(self.ws,s['session_id'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.ws.rglob('*') if p.is_file()})
    def test_duplicate_or_oversized_request_json_rejected(self):
        p=self.base/'request.json'
        for raw in (b'{"operation":"report","operation":"run"}',b' '*20000):
            p.write_bytes(raw)
            with self.assertRaises(core.GateError):self.a.load_request(p)
    def test_original_cli_rejects_mixed_modes_before_workspace_mutation(self):
        p=self.base/'request.json';p.write_text('{}',encoding='utf-8')
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                closed_loop.main(['--workspace',str(self.ws),'--audit-request',str(p),'--operational-tick'])
        self.assertFalse(self.ws.exists())
    def test_original_cli_dispatches_audit_report(self):
        s=self.plan();self.execute_session(s);p=self.base/'request.json';p.write_text(json.dumps({'operation':'report','session_id':s['session_id']}),encoding='utf-8')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(closed_loop.main(['--workspace',str(self.ws),'--audit-request',str(p)]),0)
        result=json.loads(out.getvalue());self.assertEqual(result['schema'],'V47-LOCAL-AGENT-AUDIT-REPORT-1');self.assertEqual(result['formal_A'],0)

    def test_empty_audit_flag_does_not_fall_through_to_operational_execution(self):
        with patch.object(closed_loop,'operational_tick',side_effect=AssertionError('audit request fell through')):
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    closed_loop.main(['--workspace',str(self.ws),'--audit-request','','--operational-tick'])
        self.assertFalse(self.ws.exists())

    def test_controller_pin_covers_executed_journal_dependency(self):
        dependency=self.base/'loaded-journal-dependency.py';dependency.write_bytes(b'original dependency')
        with patch.object(closed_loop,'__file__',str(dependency)):
            s=self.plan();dependency.write_bytes(b'changed executed journal dependency')
            with patch.object(self.a,'_perform',side_effect=AssertionError('changed dependency executed')):
                out=self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
        self.assertTrue(any(t['outcome']=='FAILED' and 'SOURCE' in str(t['result']) for t in out['tasks']))

    def test_delegated_intake_repeated_reads_share_the_total_budget(self):
        self.ws.mkdir();tick='V47T-'+'a'*32
        with contextlib.closing(self.conn()) as c:
            c.execute('CREATE TABLE operational_events(event_id INTEGER,tick_id TEXT,event_type TEXT)')
            c.execute('INSERT INTO operational_events VALUES(1,?,?)',(tick,'STARTED'));c.commit()
        folder=self.ws/'operational_intake'/tick/'SSQ';body=b'x'*1024;sha=hashlib.sha256(body).hexdigest()
        rel='raw/SSQ/national/'+sha+'.bin';(folder/rel).parent.mkdir(parents=True);(folder/rel).write_bytes(body)
        artifact={'artifact_path':rel,'raw_sha256':sha,'size_bytes':len(body),'http_status':200,'body_preserved':True}
        gate={'formal_A':0,'official_target_admission':'BLOCKED','external_tsa':'NOT_RUN','decision':'NO_EDGE'}
        bundle={'schema':'V47-OFFICIAL-INTAKE-BUNDLE-1',**gate,'games':{'SSQ':{**gate,'sources':[{'source_id':'national','raw_artifacts':[artifact]*16}]}}}
        (folder/'intake.json').write_text(json.dumps(bundle),encoding='utf-8')
        # Preflight unique files fit; repeated delegated reads must not escape.
        with patch.object(self.a,'MAX_TOTAL',20000):
            with self.assertRaises(core.GateError):self.a._intake(self.ws)

    def test_journal_budget_counts_identity_and_checksum_columns_before_fetchall(self):
        self.plan()
        with contextlib.closing(self.conn()) as c:
            c.executescript(closed_loop.OPERATIONAL_SCHEMA)
            for i in range(10):
                c.execute('INSERT INTO operational_events(tick_id,event_type,lottery,event_payload,event_sha256) VALUES(?,?,?,?,?)',('x'*2000,'STARTED',None,'{}','a'*64))
            c.commit()
        with patch.object(self.a,'MAX_TOTAL',10000),patch.object(closed_loop,'_operational_check_journal',side_effect=AssertionError('oversized metadata fetched')):
            out=self.a._perform('journal_integrity',self.ws,{})
        self.assertEqual(out['outcome'],'BLOCKED')

    def test_poisoned_extra_trigger_cannot_modify_prior_rows(self):
        self.ws.mkdir()
        with contextlib.closing(self.conn()) as c:
            c.executescript("CREATE TABLE prior_predictions(id INTEGER PRIMARY KEY,payload TEXT);INSERT INTO prior_predictions VALUES(1,'original');")
        s=self.plan()
        with contextlib.closing(self.conn()) as c:
            c.execute("CREATE TRIGGER injected_side_effect AFTER INSERT ON agent_audit_events BEGIN UPDATE prior_predictions SET payload='changed'; END")
        with self.assertRaises((core.GateError,sqlite3.DatabaseError)):self.a.run_session(self.ws,s['session_id'],actor=self.actors['executor'])
        with contextlib.closing(self.conn()) as c:self.assertEqual(c.execute('SELECT payload FROM prior_predictions').fetchone()[0],'original')

    def test_same_named_noop_guard_is_not_accepted(self):
        s=self.plan()
        with contextlib.closing(self.conn()) as c:
            c.execute('DROP TRIGGER agent_audit_events_no_update')
            c.execute('CREATE TRIGGER agent_audit_events_no_update BEFORE UPDATE ON agent_audit_events BEGIN SELECT 1; END')
        with self.assertRaises(core.GateError):self.a.report_session(self.ws,s['session_id'])

    def test_connection_authorizer_denies_old_table_dml(self):
        self.ws.mkdir()
        with contextlib.closing(self.conn()) as c:c.execute('CREATE TABLE prior_predictions(id INTEGER PRIMARY KEY,payload TEXT)')
        self.plan()
        with self.a._connection(self.ws,write=True) as c:
            with self.assertRaises(sqlite3.DatabaseError):c.execute("INSERT INTO prior_predictions VALUES(1,'not allowed')")

    @unittest.skipUnless(__import__('os').name=='nt','Windows junction test')
    def test_real_windows_junction_is_refused(self):
        import os,subprocess
        target=self.base/'junction-target';target.mkdir();link=self.base/'junction'
        result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],capture_output=True,timeout=10)
        if result.returncode:self.skipTest('junction creation unavailable: '+str(result.returncode))
        try:
            with self.assertRaises(core.GateError):self.a.create_session(link/'workspace',key='junction',actors=self.actors,source_root=self.src)
        finally:
            os.rmdir(link)


