import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.ssq_dlt_d2_forensics import generators, protocol
from research.ssq_dlt_v45.store import Store


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'study'
        self.prior=self.root/'prior.json'
        self.prior.write_text(json.dumps({'status':'DO_NOT_PROMOTE','negative_control_failures':{
            protocol.PRIOR_NEGATIVE_KEY:{'holm_p':.03414134606736723,'status':'FALSIFIED_NEGATIVE_CONTROL'}}}),encoding='utf-8')

    def test_registered_rectangle_and_family(self):
        rows=protocol.expected_streams()
        self.assertEqual(len(rows),240)
        self.assertEqual(len(set(rows)),240)
        self.assertEqual(len(protocol.NEGATIVE)*len(protocol.GAMES)*len(protocol.MODELS),24)
        self.assertEqual(len(rows)*240,57600)

    def test_two_sided_tail_against_exact_small_enumeration(self):
        for n in range(1,12):
            for h in range(n+1):
                p=.25
                lower=sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(h+1))
                upper=sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(h,n+1))
                self.assertAlmostEqual(protocol.two_sided_binomial(h,n,p),min(1,2*min(lower,upper)),places=12)

    def test_prepare_is_exclusive_and_preserves_failure(self):
        protocol.prepare(self.output,self.prior)
        plan=protocol.load_plan(self.output)
        self.assertEqual(plan['prior_failure']['status'],'FALSIFIED_NEGATIVE_CONTROL')
        self.assertEqual(plan['spec']['formal_A'],0)
        with self.assertRaises(FileExistsError):protocol.prepare(self.output,self.prior)

    def test_changed_plan_cannot_be_loaded(self):
        protocol.prepare(self.output,self.prior)
        with (self.output/'plan.json').open('ab') as handle:handle.write(b' ')
        with self.assertRaisesRegex(ValueError,'PLAN_SHA_MISMATCH'):protocol.load_plan(self.output)

    def test_source_drift_cannot_be_loaded(self):
        protocol.prepare(self.output,self.prior)
        with patch.object(protocol,'source_manifest',return_value={}):
            with self.assertRaisesRegex(ValueError,'SOURCE_OR_PROTOCOL_DRIFT'):protocol.load_plan(self.output)

    def test_runtime_drift_cannot_be_loaded(self):
        protocol.prepare(self.output,self.prior)
        with patch.object(protocol.sys,'version','DIFFERENT_RUNTIME'):
            with self.assertRaisesRegex(ValueError,'RUNTIME_DRIFT'):protocol.load_plan(self.output)

    def test_prior_failure_cannot_be_replaced(self):
        protocol.prepare(self.output,self.prior)
        self.prior.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'PRIOR_FAILURE_CHANGED'):protocol.load_plan(self.output)

    def test_interrupted_claim_cannot_restart_or_generate(self):
        protocol.prepare(self.output,self.prior)
        Store(self.output/'research.sqlite3').append('forensics_claim','v1',{'at':'UNIT_FIXTURE'})
        with patch.object(protocol.generators,'synthetic_history',side_effect=AssertionError('MUST_NOT_GENERATE')):
            with self.assertRaisesRegex(ValueError,'UNKNOWN_PRIOR_EXECUTION_CLAIM'):protocol.execute(self.output)

    def test_future_outcomes_do_not_enter_prefix(self):
        rows,_=generators.synthetic_history('DLT','MT_DIRECT',0,warmup=240,evaluation_draws=2,root_seed=999)
        base=protocol.predict_at('DLT',rows,240)
        other=copy.deepcopy(rows)
        for row in other[240:]:row['front']=[1,2,3,4,5]
        self.assertEqual(base,protocol.predict_at('DLT',other,240))

    def test_target_issue_or_date_in_history_blocks(self):
        rows,_=generators.synthetic_history('DLT','MT_DIRECT',0,warmup=240,evaluation_draws=1,root_seed=999)
        changed=copy.deepcopy(rows);changed[239]['issue']=changed[240]['issue']
        with self.assertRaisesRegex(ValueError,'F01_'):protocol.predict_at('DLT',changed,240)
        changed=copy.deepcopy(rows);changed[239]['draw_date']=changed[240]['draw_date']
        with self.assertRaisesRegex(ValueError,'F01_'):protocol.predict_at('DLT',changed,240)

    def test_illegal_prefix_index_blocks(self):
        rows,_=generators.synthetic_history('SSQ','MT_DIRECT',0,warmup=240,evaluation_draws=1,root_seed=999)
        for index in (-1,0,239,241,True):
            with self.assertRaises(ValueError):protocol.predict_at('SSQ',rows,index)

    def test_positive_diagnostics_interfaces_on_toy_seed(self):
        for game in protocol.GAMES:
            for scenario in protocol.POSITIVE:
                rows,meta=generators.synthetic_history(game,scenario,0,warmup=240,evaluation_draws=1,root_seed=999)
                n,k,_,_=protocol.original.RULES[game]
                truth=protocol.calibration.true_pair_probabilities(meta['law'],n,k,ring=meta.get('ring'))
                pred=protocol.predict_at(game,rows,240)
                empirical,prior,target=protocol.components(game,rows[:240])
                decomp=protocol.calibration.brier_decomposition(empirical,prior,truth,rows[240]['front'])
                self.assertLess(abs(decomp['mix_mse_identity_residual']),1e-12)
                self.assertLess(abs(decomp['mix_oracle_identity_residual']),1e-12)
                self.assertAlmostEqual(decomp['mix_mse'],sum((pred[protocol.frozen.MODEL_IDS[0]]['pair_probabilities'][p]-truth[p])**2 for p in truth)/len(truth),places=12)
                fit=protocol.calibration.fit_moment_matched_cb(target,k,maxiter=200,tol=1e-9)
                self.assertTrue(fit['converged'])
                self.assertLessEqual(fit['max_abs_error'],1e-9)


if __name__=='__main__':unittest.main()
