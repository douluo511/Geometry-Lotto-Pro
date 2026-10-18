"""Registered retrospective execution using synthetic histories only."""
from datetime import date, timedelta, datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research.ssq_dlt_v45 import study
from research.ssq_dlt_v45.store import parse


class StudyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='v45-study-')
        self.root=Path(self.tmp.name)
        self.config={'history':{}}
        for game in ('SSQ','DLT'):
            upper,count,back_count=(33,6,1) if game=='SSQ' else (35,5,2)
            history=[]
            for i in range(145):
                front=sorted({(i*3+j*4)%upper+1 for j in range(count)})
                history.append(dict(issue=f'2025{i+1:03d}' if game=='SSQ' else f'25{i+1:03d}',
                    draw_date=(date(2025,1,1)+timedelta(days=i)).isoformat(),front=front,back=list(range(1,back_count+1))))
            raw=json.dumps(dict(game=game,draws=history)).encode()
            path=self.root/(game+'.json');path.write_bytes(raw)
            self.config['history'][game]={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        self.output=self.root/'study'

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        return study.prepare(self.config,self.output,now=datetime(2026,10,18,tzinfo=timezone.utc))

    def test_plan_contains_all_issues_fixed_primary_global_family_and_power(self):
        plan=self.prepare()
        self.assertEqual(plan['family']['size'],10)
        self.assertEqual(len(set(plan['family']['identities'])),10)
        self.assertEqual(plan['primary_model'],'R45-PAIRWISE-D2')
        self.assertEqual(plan['seed'],20261018)
        self.assertFalse(plan['improvement_spec']['parameter_search'])
        self.assertEqual(plan['future_trial']['status'],'BLOCKED_NOT_STARTED')
        for gp in plan['games'].values():
            issues=[i for s in study.STAGES for i in gp['stages'][s]['expected_issues']]
            self.assertEqual(len(issues),25)
            self.assertEqual(len(set(issues)),25)

    def test_complete_run_is_unpromoted_verified_and_cannot_retest(self):
        self.prepare()
        result=study.execute(self.config,self.output)
        self.assertEqual(result['period_rows'],50)
        self.assertEqual(result['formal_A'],0)
        self.assertEqual(result['independent_prospective_samples'],0)
        self.assertEqual(result['decision'],'NO_EDGE')
        self.assertEqual(len([r for r in result['summaries'] if r['p_holm'] is not None]),10)
        self.assertEqual(study.verify(self.output)['status'],'PASS')
        saved=(self.output/'results.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):
            study.execute(self.config,self.output)
        self.assertEqual((self.output/'results.json').read_bytes(),saved)

    def test_plan_edit_is_rejected_before_outcomes(self):
        self.prepare()
        plan=parse((self.output/'plan.json').read_bytes());plan['seed']=42
        (self.output/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'PLAN_SHA'):
            study.execute(self.config,self.output)
        self.assertFalse((self.output/'results.json').exists())

    def test_modified_input_pin_is_rejected_without_start_claim(self):
        self.prepare()
        self.config['history']['SSQ']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'INPUT_PIN_CHANGED'):
            study.execute(self.config,self.output)
        self.assertFalse((self.output/'results.json').exists())

    def test_render_artifact_tampering_is_rejected(self):
        self.prepare();study.execute(self.config,self.output)
        (self.output/'report.html').write_text('TAMPERED',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SHA'):
            study.verify(self.output)

    def test_input_future_duplicate_and_wrong_game_fail_before_registration(self):
        for fault in ('future','duplicate','game'):
            with self.subTest(fault=fault):
                path=Path(self.config['history']['SSQ']['path'])
                original=path.read_bytes();doc=json.loads(original)
                if fault=='future': doc['draws'][-1]['draw_date']='2099-01-01'
                elif fault=='duplicate': doc['draws'][-1]['issue']=doc['draws'][-2]['issue']
                else: doc['game']='DLT'
                raw=json.dumps(doc).encode();path.write_bytes(raw)
                spec={**self.config,'history':{**self.config['history'],'SSQ':{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}}}
                with self.assertRaises(ValueError):
                    study.prepare(spec,self.root/('bad-'+fault),now=datetime(2026,10,18,tzinfo=timezone.utc))
                self.assertFalse((self.root/('bad-'+fault)/'plan.json').exists())
                path.write_bytes(original)
