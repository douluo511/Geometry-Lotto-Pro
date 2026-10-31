"""TEST_ONLY: real SQLite/old evidence, synthetic clock and outcomes, never formal."""
import contextlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from research.harness_v46 import closed_loop, core, convergence, schedule, cli
from research.harness_v46.tests.test_core import fixture

def at(text): return datetime.fromisoformat(text)

def bundle(issue='29999', day='2026-10-24'):
    result={g:fixture(g) for g in ('SSQ','DLT')}
    for value in result.values():
        value.update(target_issue=issue,as_of=day+'T09:00:00+00:00',
                     sales_cutoff=day+'T13:00:00+00:00',
                     target_draw_at=day+'T13:25:00+00:00')
    return result

class FreezeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.snaps=bundle()
        self.before=at('2026-10-24T12:59:57+00:00')
        self.cutoff=at('2026-10-24T13:00:00+00:00')

    @contextlib.contextmanager
    def clock(self,initial=None):
        state={'now':initial or self.before}
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return cls.fromisoformat(state['now'].isoformat()).astimezone(tz or timezone.utc)
        with patch.object(schedule,'datetime',Clock),patch.object(closed_loop,'datetime',Clock):
            yield state

    def direct(self,db,**kwargs):
        return schedule.scheduled_once(self.snaps,db,require_delivery_window=False,**kwargs)

    def assert_rows(self,db,want):
        if not db.exists():
            self.assertEqual(want,0);return
        with contextlib.closing(sqlite3.connect(db)) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'predictions' in tables:self.assertEqual(conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],want)
            elif want:self.fail('missing frozen rows')
            if want==0:
                for name in ('run_manifests','run_snapshots','run_context','scheduled_target_guard',
                             'audit_events','workflow_events','shadow_trace_events','tsa_claims'):
                    if name in tables:
                        self.assertEqual(conn.execute('SELECT COUNT(*) FROM '+name).fetchone()[0],0,name)

    def test_elapsed_forecast_cannot_use_stale_clock_in_direct_or_workspace_entry(self):
        for entry in ('direct','workspace'):
            with self.subTest(entry=entry):
                ws=self.root/entry;ws.mkdir();db=ws/'ledger.sqlite3'
                original=schedule.forecast
                with self.clock() as state:
                    def slow(snapshot,model):
                        value=original(snapshot,model);state['now']=self.cutoff;return value
                    with patch.object(schedule,'forecast',side_effect=slow):
                        with self.assertRaisesRegex(core.GateError,'CUTOFF'):
                            self.direct(db) if entry=='direct' else closed_loop.advance_workspace(ws,snapshots=self.snaps)
                self.assert_rows(db,0)

    def test_final_trace_crossing_cutoff_rolls_back_all_twelve_cards_and_guards(self):
        db=self.root/'late-final.sqlite3';original=schedule.tsa_request
        with self.clock() as state:
            def slow(conn,run,game):
                value=original(conn,run,game)
                if game=='DLT':state['now']=self.cutoff
                return value
            with patch.object(schedule,'tsa_request',side_effect=slow):
                with self.assertRaisesRegex(core.GateError,'CUTOFF'):self.direct(db)
        self.assert_rows(db,0)

    def test_frozen_time_uses_observation_after_forecast_not_entry(self):
        db=self.root/'fresh-time.sqlite3';original=schedule.forecast
        fresh=at('2026-10-24T12:59:58+00:00')
        with self.clock() as state:
            def slow(snapshot,model):
                value=original(snapshot,model);state['now']=fresh;return value
            with patch.object(schedule,'forecast',side_effect=slow):self.direct(db)
        with contextlib.closing(sqlite3.connect(db)) as conn:
            stamps={r[0] for r in conn.execute('SELECT frozen_at FROM predictions')}
        self.assertEqual(stamps,{'2026-10-24T12:59:58+00:00'})

    def test_real_sqlite_writer_lock_across_cutoff_cannot_admit_a_batch(self):
        db=self.root/'lock.sqlite3';anchor=sqlite3.connect(db)
        try:
            core.init_ledger(anchor);convergence.init_workflow(anchor)
            anchor.executescript(schedule.GUARD_SCHEMA);anchor.commit();anchor.execute('BEGIN IMMEDIATE')
            reached=threading.Event();connect=sqlite3.connect
            def tracked(*args,**kwargs):
                conn=connect(*args,**kwargs)
                conn.set_trace_callback(lambda sql:reached.set() if sql.lstrip().upper().startswith(('CREATE','BEGIN','INSERT')) else None)
                return conn
            with self.clock() as state,patch.object(schedule.sqlite3,'connect',side_effect=tracked):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(self.direct,db)
                    self.assertTrue(reached.wait(10),'worker never reached actual SQLite')
                    self.assertTrue(anchor.in_transaction);self.assertFalse(future.done())
                    state['now']=self.cutoff;anchor.commit()
                    with self.assertRaisesRegex(core.GateError,'CUTOFF'):future.result(timeout=15)
        finally:anchor.close()
        self.assert_rows(db,0)

    def test_real_reader_lock_wait_must_finish_before_cutoff_validation(self):
        # BEGIN IMMEDIATE would wait at COMMIT, after its final clock check.
        # A reader holds a real SHARED lock; an exclusive writer must wait
        # before validating time. Clocks/outcomes remain synthetic TEST_ONLY.
        db=self.root/'reader-lock.sqlite3';reader=sqlite3.connect(db)
        try:
            core.init_ledger(reader);convergence.init_workflow(reader)
            reader.executescript(schedule.GUARD_SCHEMA);reader.commit()
            reader.execute('BEGIN')
            reader.execute('SELECT count(*) FROM predictions').fetchone()
            begin=threading.Event();commit=threading.Event();connect=sqlite3.connect
            def tracked(*args,**kwargs):
                conn=connect(*args,**kwargs)
                def trace(sql):
                    text=sql.lstrip().upper()
                    if text.startswith('BEGIN'):begin.set()
                    if text.startswith('COMMIT'):commit.set()
                conn.set_trace_callback(trace);return conn
            with self.clock() as state,patch.object(schedule.sqlite3,'connect',side_effect=tracked):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(self.direct,db)
                    self.assertTrue(begin.wait(10),'worker never attempted a transaction')
                    # Old IMMEDIATE reaches COMMIT, new EXCLUSIVE waits at BEGIN.
                    commit.wait(5)
                    self.assertFalse(future.done(),'reader was not actually blocking writer')
                    state['now']=self.cutoff;reader.commit()
                    with self.assertRaisesRegex(core.GateError,'CUTOFF'):future.result(timeout=15)
        finally:reader.close()
        self.assert_rows(db,0)

    def test_per_game_reader_lock_cannot_delay_commit_past_cutoff(self):
        ws=self.root/'game-reader';ws.mkdir();db=ws/'ledger.sqlite3'
        reader=sqlite3.connect(db)
        try:
            reader.executescript(closed_loop.GAME_SCHEMA);reader.commit()
            reader.execute('BEGIN')
            reader.execute('SELECT count(*) FROM game_predictions').fetchone()
            begin=threading.Event();commit=threading.Event();connect=sqlite3.connect
            def tracked(*args,**kwargs):
                conn=connect(*args,**kwargs)
                def trace(sql):
                    text=sql.lstrip().upper()
                    if text.startswith('BEGIN'):begin.set()
                    if text.startswith('COMMIT'):commit.set()
                conn.set_trace_callback(trace);return conn
            with self.clock() as state,patch.object(closed_loop.sqlite3,'connect',side_effect=tracked):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(closed_loop.advance_game_workspace,ws,snapshot=self.snaps['SSQ'])
                    self.assertTrue(begin.wait(10),'worker never attempted a transaction')
                    commit.wait(5)
                    self.assertFalse(future.done(),'reader was not actually blocking writer')
                    state['now']=self.cutoff;reader.commit()
                    with self.assertRaisesRegex(core.GateError,'CUTOFF'):future.result(timeout=15)
        finally:reader.close()
        with contextlib.closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM game_predictions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM game_runs').fetchone()[0],0)

    def test_same_issue_freeze_in_lock_gap_reuses_other_workers_original_cards(self):
        ws=self.root/'same-issue-gap';ws.mkdir();db=ws/'ledger.sqlite3'
        connect=sqlite3.connect;injected=[]
        class Connection:
            def __init__(self,conn):self.conn=conn
            def __getattr__(self,name):return getattr(self.conn,name)
            def execute(proxy,sql,*args):
                value=proxy.conn.execute(sql,*args)
                if sql=='ROLLBACK' and not injected:
                    injected.append(True)
                    closed_loop.advance_game_workspace(ws,snapshot=self.snaps['SSQ'],observed_at=self.before)
                return value
        with patch.object(closed_loop.sqlite3,'connect',side_effect=lambda *a,**k:Connection(connect(*a,**k))):
            try:
                out=closed_loop.advance_game_workspace(ws,snapshot=self.snaps['SSQ'],observed_at=self.before)
            except core.GateError as exc:
                self.fail('an identical concurrent freeze must be reused: '+str(exc))
        self.assertTrue(injected,'other worker did not run in released-lock interval')
        self.assertEqual(out['pending_issues'],['29999'])
        with contextlib.closing(connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM game_predictions').fetchone()[0],6)
            self.assertEqual(conn.execute('SELECT count(*) FROM game_runs').fetchone()[0],1)

    def test_backwards_actual_clock_is_rejected_before_freeze(self):
        db=self.root/'backwards.sqlite3';original=schedule.forecast
        with self.clock() as state:
            def backwards(snapshot,model):
                value=original(snapshot,model);state['now']=self.before-timedelta(seconds=1);return value
            with patch.object(schedule,'forecast',side_effect=backwards):
                with self.assertRaisesRegex(core.GateError,'CLOCK_MOVED_BACKWARD'):self.direct(db)
        self.assert_rows(db,0)

    def test_explicit_synthetic_clock_retry_keeps_original_timestamps(self):
        db=self.root/'synthetic.sqlite3'
        first=self.direct(db,now=self.before)
        with contextlib.closing(sqlite3.connect(db)) as conn:
            old=conn.execute('SELECT * FROM predictions ORDER BY lottery,model').fetchall()
        retry=self.direct(db,now=self.before+timedelta(seconds=1))
        with contextlib.closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM predictions ORDER BY lottery,model').fetchall(),old)
        self.assertEqual(first['run_id'],retry['run_id']);self.assertEqual(first['formal_A'],0)

    def seed(self,ws,mode):
        snaps=bundle()
        report=(closed_loop.advance_workspace(ws,snapshots=snaps,observed_at=at('2026-10-24T10:00:00+00:00'))
                if mode=='dual' else closed_loop.advance_game_workspace(ws,snapshot=snaps['SSQ'],observed_at=at('2026-10-24T10:00:00+00:00')))
        return snaps,report

    def publish_old(self,ws,mode,snaps,report):
        results={g:{'lottery':g,'issue':'29999','front':s['draws'][-2]['front'],
                    'back':s['draws'][-2]['back'],'drawn_at':s['target_draw_at']} for g,s in snaps.items()}
        if mode=='dual':
            p=ws/'outcomes'/(report['run_ids'][0]+'.json');value=results
        else:p=ws/'outcomes_by_game/SSQ/29999.json';value=results['SSQ']
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf-8')
        return p

    def new_request(self,ws,mode):
        snaps=bundle('30000','2026-10-25');now=at('2026-10-25T10:00:00+00:00')
        return (closed_loop.advance_workspace(ws,snapshots=snaps,observed_at=now) if mode=='dual'
                else closed_loop.advance_game_workspace(ws,snapshot=snaps['SSQ'],observed_at=now))

    def assert_original_count(self,ws,mode):
        with contextlib.closing(sqlite3.connect(ws/'ledger.sqlite3')) as c:
            table='predictions' if mode=='dual' else 'game_predictions'
            self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],12 if mode=='dual' else 6)
            if mode=='game':self.assertEqual(c.execute('SELECT issue FROM game_runs').fetchall(),[('29999',)])

    def test_unknown_evidence_prevents_new_dual_commit(self):
        for folder,reason in [('outcomes','UNKNOWN_OUTCOME_RUN'),('receipts','UNKNOWN_STORED_RECEIPT')]:
            with self.subTest(folder=folder):
                ws=self.root/folder;(ws/folder).mkdir(parents=True)
                bad=ws/folder/('V47-'+'f'*32+'.json');bad.write_text('{}',encoding='utf-8')
                with self.assertRaisesRegex(core.GateError,reason):
                    closed_loop.advance_workspace(ws,snapshots=self.snaps,observed_at=self.before)
                self.assert_rows(ws/'ledger.sqlite3',0)
                self.assertEqual(bad.read_text(encoding='utf-8'),'{}')

    def test_prior_bad_json_or_receipt_conflict_cannot_commit_new_cards(self):
        for mode in ('dual','game'):
            for error in ('json','receipt'):
                with self.subTest(mode=mode,error=error):
                    ws=self.root/(mode+error);snaps,report=self.seed(ws,mode)
                    p=self.publish_old(ws,mode,snaps,report)
                    if error=='json':p.write_bytes(b'{malformed preserved')
                    else:
                        now=at('2026-10-24T14:00:00+00:00')
                        if mode=='dual':
                            closed_loop.advance_workspace(ws,observed_at=now)
                            p=ws/'receipts'/(report['run_ids'][0]+'.json')
                        else:
                            closed_loop.advance_game_workspace(ws,game='SSQ',observed_at=now)
                            p=ws/'receipts_by_game/SSQ/29999.json'
                        p.write_bytes(b'{"conflicting":"preserved"}')
                    before=p.read_bytes()
                    with self.assertRaises((core.GateError,ValueError)):self.new_request(ws,mode)
                    self.assert_original_count(ws,mode);self.assertEqual(p.read_bytes(),before)

    def test_corrupt_prior_game_card_blocks_before_new_issue_commit(self):
        ws=self.root/'corrupt';self.seed(ws,'game')
        with contextlib.closing(sqlite3.connect(ws/'ledger.sqlite3')) as c:
            c.execute('DROP TRIGGER protect_game_predictions_update')
            c.execute("UPDATE game_predictions SET prediction_sha256=? WHERE model='hot60'",('0'*64,));c.commit()
        with self.assertRaisesRegex(core.GateError,'GAME_FROZEN_PREDICTION_REPLAY_MISMATCH'):
            self.new_request(ws,'game')
        self.assert_original_count(ws,'game')

    def test_existing_operational_ledger_bootstraps_dual_without_erasing_operations(self):
        ws=self.root/'existing-operations';ws.mkdir()
        db=ws/'ledger.sqlite3';c=closed_loop._operational_open(db);c.close()
        try:report=closed_loop.advance_workspace(ws,snapshots=self.snaps,observed_at=self.before)
        except Exception as exc:self.fail('valid operational-only workspace must accept canonical dual input: '+str(exc))
        self.assertEqual(report['formal_A'],0);self.assertEqual(len(report['run_ids']),1)
        with contextlib.closing(sqlite3.connect(db)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM operational_events').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM predictions').fetchone()[0],12)

    def test_unrelated_other_game_bad_outcome_does_not_block_new_ssq(self):
        ws=self.root/'other-game';snaps=bundle()
        closed_loop.advance_game_workspace(ws,snapshot=snaps['DLT'],observed_at=self.before)
        p=ws/'outcomes_by_game/DLT/29999.json';p.parent.mkdir(parents=True);p.write_bytes(b'{malformed')
        out=closed_loop.advance_game_workspace(ws,snapshot=snaps['SSQ'],observed_at=self.before)
        self.assertEqual(out['lottery'],'SSQ');self.assertEqual(out['pending_issues'],['29999'])

    def test_legacy_interfaces_reject_both_canonical_namespaces_before_storage_access(self):
        snap=self.root/'snapshot.json';snap.write_text(json.dumps(self.snaps['SSQ']),encoding='utf-8')
        result=self.root/'result.json';result.write_text(json.dumps({'lottery':'SSQ','issue':'29999','front':[1,2,3,4,5,6],'back':[1]}),encoding='utf-8')
        for prefix in ('V47-','V47G-'):
            for command in ('forecast','score'):
                with self.subTest(prefix=prefix,command=command):
                    db=self.root/(prefix+command+'.sqlite3');args=SimpleNamespace(run_id=prefix+'a'*32,database=str(db),snapshot=str(snap),official_result=str(result),model='all')
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            cli.run_forecast(args) if command=='forecast' else cli.run_score(args)
                    except core.GateError as exc:self.assertIn('V47_RUN_ID_REQUIRES',str(exc))
                    except Exception as exc:self.fail('must reject canonical namespace before file/SQL work: '+str(exc))
                    else:self.fail('legacy interface accepted a canonical identity')
                    self.assertFalse(db.exists())

    def test_legacy_v46_scoring_stays_compatible(self):
        db=self.root/'legacy.sqlite3';snap=self.snaps['SSQ'];run='V46-test-only'
        with contextlib.closing(sqlite3.connect(db)) as c:
            core.init_ledger(c)
            with c:
                for m in core.MODELS:core.freeze_shadow(c,run,snap,core.forecast(snap,m),self.before.isoformat())
        p=self.root/'legacy-result.json';p.write_text(json.dumps({'lottery':'SSQ','issue':'29999','front':[1,2,3,4,5,6],'back':[1]}),encoding='utf-8')
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):cli.run_score(SimpleNamespace(database=str(db),run_id=run,official_result=str(p)))
        self.assertEqual(len(json.loads(stream.getvalue())['scores']),6)
        self.assertIn('NO_EDGE',json.loads(stream.getvalue())['warning'])

if __name__=='__main__':unittest.main()

