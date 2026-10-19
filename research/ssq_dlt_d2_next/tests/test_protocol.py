from contextlib import ExitStack
from datetime import date,timedelta
import hashlib
from itertools import combinations
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_next import protocol,simulation
from research.ssq_dlt_v45.store import Store,canonical


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.stack=ExitStack()
        rng=random.Random(5317);limits={};config={'history':{}};old={'games':{}}
        self.documents={}
        for game,n,k,width,back in [('SSQ',33,6,7,[1]),('DLT',35,5,5,[1,2])]:
            rows=[dict(game=game,issue=('2025' if width==7 else '25')+f'{i+1:03d}',
                draw_date=(date(2025,1,1)+timedelta(days=i)).isoformat(),front=sorted(rng.sample(range(1,n+1),k)),back=back)
                for i in range(280)]
            doc={'game':game,'draws':rows};self.documents[game]=doc
            path=self.root/(game+'.json');path.write_text(canonical(doc),encoding='utf-8')
            rawsha=hashlib.sha256(path.read_bytes()).hexdigest()
            limits[game]=dict(rows=280,last_issue=rows[-1]['issue'],input_sha256=rawsha)
            config['history'][game]=dict(path=str(path),sha256=rawsha)
            old['games'][game]={'stages':{'development':{'stop':280}}}
        self.legacy=self.root/'legacy.json';self.legacy.write_text(canonical(old),encoding='utf-8')
        self.config=self.root/'config.json';self.config.write_text(canonical(config),encoding='utf-8')
        self.stack.enter_context(patch.object(protocol,'LIMITS',limits))
        self.stack.enter_context(patch.object(protocol,'LEGACY_PLAN_SHA',hashlib.sha256(self.legacy.read_bytes()).hexdigest()))
        self.out=self.root/'study'
    def tearDown(self):self.stack.close();self.temp.cleanup()
    def prepare(self):return protocol.prepare(self.legacy,self.config,self.out)

    def execute_fixture(self):
        with patch('research.ssq_dlt_d2_next.simulation.run_controls',return_value={'periods':[],'scope':'UNIT_TEST_STUB'}),patch('research.ssq_dlt_d2_next.inference.simulate_protocol',return_value={'scope':'UNIT_TEST_STUB'}):
            return protocol.execute(self.out)

    def test_prepare_physically_exports_only_fixed_development_and_plan_is_new(self):
        result=self.prepare();self.assertEqual(result['status'],'PREPARED_DEVELOPMENT_ONLY')
        plan,games,identity=protocol.load_plan(self.out)
        self.assertEqual(plan['legacy_partitions_allowed'],['development'])
        self.assertFalse(plan['hyperparameter_search']);self.assertEqual(plan['d2_size'],2)
        for game,rows in games.items():self.assertEqual(len(rows),280);self.assertEqual(len(plan['games'][game]['expected_issues']),40)
        with self.assertRaises(FileExistsError):self.prepare()

    def test_unrecognized_plan_rejected_before_reading_any_original(self):
        self.legacy.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'UNRECOGNIZED'):self.prepare()
        self.assertFalse(self.out.exists())

    def test_same_day_future_duplicate_issue_and_gap_are_blocked(self):
        for failure in ('same_day','future','duplicate','gap'):
            doc=json.loads(canonical(self.documents['SSQ']))
            if failure=='same_day':doc['draws'][1]['draw_date']=doc['draws'][0]['draw_date']
            elif failure=='future':doc['draws'][-1]['draw_date']='2099-12-31'
            elif failure=='duplicate':doc['draws'][1]['issue']=doc['draws'][0]['issue']
            else:doc['draws'].pop(5)
            with self.subTest(failure=failure),self.assertRaises(ValueError):protocol.validate_development('SSQ',doc)

    def test_tampering_recomputing_plan_sha_cannot_reregister(self):
        self.prepare();p=self.out/'plan.json';value=json.loads(p.read_bytes());value['selection']='POSTHOC_WINNER'
        p.write_text(canonical(value)+'\n',encoding='utf-8');(self.out/'plan.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'\n')
        with self.assertRaisesRegex(ValueError,'IMMUTABLE_REGISTRY'):protocol.load_plan(self.out)

    def test_future_row_injection_and_code_drift_rejected_before_execute(self):
        self.prepare()
        with patch.object(protocol,'source_manifest',return_value={}):
            with self.assertRaisesRegex(ValueError,'CODE_CHANGED'):protocol.load_plan(self.out)
        path=self.out/'dev-inputs/SSQ.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'INPUT_SHA'):protocol.load_plan(self.out)

    def test_complete_prefix_replay_metrics_csv_and_idempotent_result(self):
        self.prepare();one=self.execute_fixture()
        self.assertEqual(one['development_n'],{'SSQ':40,'DLT':40})
        checked=protocol.verify(self.out);self.assertEqual(checked['forecast_periods'],80);self.assertEqual(checked['model_periods'],640)
        old={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.out.glob('*.json')}
        with patch('research.ssq_dlt_d2_next.simulation.run_controls',side_effect=AssertionError('Do not rerun')):
            repeated=protocol.execute(self.out)
        self.assertTrue(repeated['reused_execution'])
        self.assertEqual(old,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.out.glob('*.json')})
        self.assertEqual(len((self.out/'development-periods.csv').read_text('utf-8').splitlines()),641)

    def test_unknown_execution_never_discards_failed_round(self):
        self.prepare();plan,games,identity=protocol.load_plan(self.out)
        Store(self.out/'research.sqlite3').append('mechanism_execution_claim',identity,{'unit':'simulated_interruption'})
        with self.assertRaisesRegex(ValueError,'UNKNOWN_EXECUTION'):protocol.execute(self.out)

    def test_result_tamper_not_reported_as_cached_success(self):
        self.prepare();self.execute_fixture();p=self.out/'development.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'RESULT_SHA'):protocol.execute(self.out)


class SimulationContractTests(unittest.TestCase):
    def test_exactly_two_dan_both_required(self):
        self.assertEqual(simulation.full_hit([1,2],[1,3,4,5,6]),0)
        self.assertEqual(simulation.full_hit([1,2],[1,2,4,5,6]),1)
        for invalid in ([1],[1,1],[1,2,3],[True,2]):
            with self.assertRaises(ValueError):simulation.full_hit(invalid,[1,2,3,4,5])

    def test_uniform_brier_is_one_draw_not_independent_pairs(self):
        n,k=8,3;p=k*(k-1)/(n*(n-1));prob={pair:p for pair in combinations(range(1,n+1),2)}
        self.assertAlmostEqual(simulation.pair_brier(prob,[1,2,3],n,k),p*(1-p),places=14)
        prob.pop((1,2))
        with self.assertRaises(ValueError):simulation.pair_brier(prob,[1,2,3],n,k)

    def test_generators_are_legal_reproducible_and_reference_not_oracle_in_nulls(self):
        for game in ('SSQ','DLT'):
            for scenario in simulation.SPEC['scenarios']:
                rows,reference=simulation.synthetic_history(game,scenario,0)
                self.assertEqual((rows,reference),simulation.synthetic_history(game,scenario,0))
                self.assertEqual(len(rows),480)
                for row in rows:self.assertEqual(len(row['front']),len(set(row['front'])))
                if scenario in ('FAIR','SCRAMBLED_PAIR_STRONG','RING_SCRAMBLED'):
                    self.assertEqual(reference,[[1,2]]*480)


if __name__=='__main__':unittest.main()
