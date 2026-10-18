"""Synthetic stage-clock faults; no claim of real scheduler elapsed execution."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.ssq_dlt_v45 import workflow
from research.ssq_dlt_v45.store import Store, canonical, digest
from research.ssq_dlt_v45.tests.test_pipeline import _history

MON=datetime(2026,10,19,6,10,tzinfo=timezone.utc)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=dict(state_dir=str(self.root/'state'),history={},live_sources=False,recipient=None)
        import hashlib
        for game in ('SSQ','DLT'):
            p=self.root/(game+'.json'); p.write_text(canonical(dict(game=game,draws=_history(game))),encoding='utf-8')
            self.config['history'][game]=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        self.discover=patch('research.ssq_dlt_v45.discovery.run_discovery',return_value=dict(status='DEGRADED',scope='SOURCE_DISCOVERY_ONLY'))
        self.discover.start(); self.addCleanup(self.discover.stop)

    def store(self): return Store(self.root/'state'/'workflow.sqlite3')

    def test_five_stages_have_real_observation_times_and_no_early_publish(self):
        for minute,expected in ((0,1),(10,2),(20,3),(35,4),(50,5)):
            result=workflow.tick(self.config,MON+timedelta(minutes=minute))
            self.assertEqual(len(result['completed_stages']),expected)
            self.assertFalse(result['errors'])
            self.assertEqual(len(self.store().rows('workflow_publish')),int(expected==5))
        stages=self.store().rows('workflow_stage')
        self.assertTrue(all(datetime.fromisoformat(s['observed_at'])==datetime.fromisoformat(s['scheduled_at']) for s in stages))
        report=self.store().rows('workflow_publish')[0]['report']
        self.assertEqual(report['formal_A'],0)
        self.assertTrue(all(v['target'] is None for v in report['games'].values()))
        self.assertEqual(result['metrics']['on_time_research_output']['rate'],1)
        self.assertIsNone(result['metrics']['replay_complete']['rate'])

    def test_boot_catchup_no_backdating_and_repeat_preserves_predictions(self):
        now=MON+timedelta(hours=4)
        first=workflow.tick(self.config,now)
        before=self.store().rows('workflow_stage')
        second=workflow.tick(self.config,now+timedelta(minutes=30))
        self.assertEqual(before,self.store().rows('workflow_stage'))
        self.assertEqual(len(self.store().rows('workflow_publish')),1)
        self.assertTrue(all(s['observed_at']==now.isoformat() for s in before))
        self.assertEqual(second['metrics']['on_time_research_output']['rate'],0)
        self.assertEqual(first['formal_A'],0)

    def test_network_failure_still_emits_blocked_status_then_recovers_once(self):
        config={**self.config,'live_sources':True}
        now=MON+timedelta(minutes=50)
        with patch.object(workflow.sources,'capture_pair',side_effect=TimeoutError('NETWORK_DOWN')):
            workflow.tick(config,now)
            workflow.tick(config,now+timedelta(minutes=30))
        self.assertEqual(len(self.store().rows('workflow_publish')),1)
        blocked=self.store().rows('workflow_publish')[0]
        self.assertFalse(blocked['research_ready'])
        originals=Path(blocked['report_directory'],'report.json').read_bytes()
        def recover(game,directory,clock):
            return workflow.sources.validate_history(game,_history(game),clock),[]
        with patch.object(workflow.sources,'capture_pair',side_effect=recover):
            result=workflow.tick(config,now+timedelta(minutes=60))
        self.assertFalse(result['errors'])
        self.assertEqual(len(self.store().rows('workflow_publish')),2)
        self.assertEqual(Path(blocked['report_directory'],'report.json').read_bytes(),originals)
        self.assertEqual(result['metrics']['on_time_research_output']['rate'],0)

    def test_source_tampering_and_future_data_do_not_get_predictions(self):
        for fixture in ('sha','future'):
            with self.subTest(fixture=fixture):
                self.config['state_dir']=str(self.root/fixture)
                p=Path(self.config['history']['SSQ']['path']); old=p.read_bytes()
                if fixture=='sha': p.write_bytes(old+b' ')
                else:
                    import hashlib
                    from research.ssq_dlt_v45.store import parse
                    value=parse(old); value['draws'][-1]['draw_date']='2026-10-19'
                    p.write_text(canonical(value),encoding='utf-8')
                    self.config['history']['SSQ']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                workflow.tick(self.config,MON+timedelta(minutes=50))
                store=Store(Path(self.config['state_dir'])/'workflow.sqlite3')
                self.assertIsNone(store.read('workflow_stage',workflow.active_slot(MON).isoformat()+'/predict'))
                self.assertFalse(store.rows('workflow_publish')[0]['research_ready'])
                p.write_bytes(old)

    def test_model_drift_config_drift_and_fake_authorization_fail_closed(self):
        workflow.tick(self.config,MON)
        with self.assertRaisesRegex(ValueError,'DRIFT'):
            workflow.tick({**self.config,'preview':False},MON)
        with patch.object(workflow,'code_pin',return_value={'models.py':'bad'}):
            with self.assertRaisesRegex(ValueError,'DRIFT'): workflow.tick(self.config,MON)
        for flag in ('formal','authorized','tsa_verified'):
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION'):
                workflow.tick({**self.config,flag:True},MON)
        with self.assertRaisesRegex(ValueError,'TARGET'):
            workflow.tick({**self.config,'targets':{'SSQ':'guessed'}},MON)

    def test_saved_artifact_tamper_detected_on_repeated_publication(self):
        now=MON+timedelta(minutes=50); workflow.tick(self.config,now)
        folder=Path(self.store().rows('workflow_publish')[0]['report_directory'])
        (folder/'report.html').write_text('tampered',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SHA'): workflow.tick(self.config,now)

    def test_clock_rewind_and_naive_clock_rejected(self):
        workflow.tick(self.config,MON+timedelta(minutes=50))
        with self.assertRaisesRegex(ValueError,'CLOCK_REWIND'):
            workflow.tick(self.config,MON)
        with self.assertRaisesRegex(ValueError,'AWARE_CLOCK'):
            workflow.active_slot(datetime(2026,10,19))
        with self.assertRaisesRegex(ValueError,'CLOCK_REWIND'):
            workflow.tick(self.config,MON-timedelta(days=2))

    def test_scheduled_day_boundaries_keep_fixed_jst_not_machine_timezone(self):
        self.assertEqual(workflow.active_slot(MON).isoformat(),'2026-10-19T16:00:00+09:00')
        self.assertEqual(workflow.active_slot(MON-timedelta(seconds=1)).weekday(),5)
        self.assertEqual(workflow.active_slot(MON.astimezone(timezone(timedelta(hours=-4)))),workflow.active_slot(MON))

    def test_crash_before_final_receipt_cannot_reset_clock_floor(self):
        now=MON+timedelta(days=2,minutes=50)
        with patch.object(workflow,'write_replay_report',side_effect=OSError('INJECTED_PROCESS_FAILURE')):
            with self.assertRaises(OSError): workflow.tick(self.config,now)
        self.assertEqual(self.store().rows('workflow_tick'),[])
        self.assertEqual(len(self.store().rows('workflow_publish')),1)
        with self.assertRaisesRegex(ValueError,'CLOCK_REWIND'):
            workflow.tick(self.config,MON)


if __name__=='__main__': unittest.main()
