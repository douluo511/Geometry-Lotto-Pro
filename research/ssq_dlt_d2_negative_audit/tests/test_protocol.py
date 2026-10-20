"""Synthetic lifecycle fixtures, never representations of the real 2880 audit."""
from contextlib import ExitStack
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch
from research.ssq_dlt_d2_negative_audit import protocol as p
from research.ssq_dlt_d2_next.models import registry
from research.ssq_dlt_d2_next.simulation import SPEC

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        science={}
        for i in range(49):
            path=self.repo/'research'/f'science{i}.py';path.parent.mkdir(exist_ok=True);path.write_text('fixture\n')
            science[path.relative_to(self.repo).as_posix()]=p.sha(path)
        audit=self.repo/'research/audit.py';audit.write_text('synthetic audit fixture\n')
        source={'research/audit.py':p.sha(audit)}
        originals=self.root/'original';originals.mkdir()
        values=dict(original_plan=dict(new_registry=registry(),synthetic=SPEC),original_synthetic={},
                    original_decision=dict(negative_control_failures={p.TARGET:dict(holm_p=.034)}),science_plan=dict(source_sha256=science))
        self.inputs={}
        for name,value in values.items():
            path=originals/(name+'.json');path.write_text(json.dumps(value));self.inputs[name]=path
        self.stack=ExitStack();self.addCleanup(self.stack.close);self.addCleanup(self.temp.cleanup)
        self.stack.enter_context(patch.multiple(p,ROOT=self.repo,EXPECTED={n:p.sha(v) for n,v in self.inputs.items()}))
        self.stack.enter_context(patch.object(p,'own_sources',return_value=source))
        self.out=self.root/'new-audit';p.prepare(self.inputs,self.out)
        self.family=dict(cells={p.TARGET:dict(hits=69,n=2880,holm_p=.034)},rejections=[p.TARGET])
        self.replay=dict(status='PASS',n=2880,target_hits=69,original_anomaly_reproduced=True)
    def tearDown(self):
        self.stack.close();self.temp.cleanup()
    def invoke(self,side_effect=None):
        with patch.object(p,'rescore_family',return_value=self.family),patch('research.ssq_dlt_d2_negative_audit.replay.replay_target',return_value=self.replay,side_effect=side_effect):
            return p.execute(self.out)
    def test_synthetic_fixture_lifecycle_and_readonly_verify(self):
        self.assertEqual(self.invoke()['cause'],'UNRESOLVED')
        before={x.name:p.sha(x) for x in self.out.iterdir() if x.is_file()}
        self.assertIn('PASS_READONLY',p.verify(self.out)['status'])
        self.assertEqual(before,{x.name:p.sha(x) for x in self.out.iterdir() if x.is_file()})
    def test_second_execution_does_not_repeat(self):
        self.invoke()
        with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):self.invoke()
    def test_failed_effect_keeps_failure_and_after_snapshot(self):
        with self.assertRaisesRegex(ValueError,'EVIDENCE_RETAINED'):self.invoke(RuntimeError('SYNTHETIC_DRIVER_FAILURE'))
        failed=p.read(self.out/'failure.json')
        self.assertEqual(failed['primary_failure']['reason'],'SYNTHETIC_DRIVER_FAILURE')
        self.assertEqual(p.read(self.out/'before.json'),p.read(self.out/'after.json'))
        self.assertFalse((self.out/'result.json').exists())
    def test_incomplete_run_never_automatically_restarts(self):
        p.write_new(self.out/'STARTED.json',dict(status='STARTED_NOT_PASS'))
        with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):self.invoke()
    def test_during_run_input_change_is_retained_as_fail(self):
        def mutate(*args,**kwargs):
            with self.inputs['original_synthetic'].open('a') as f:f.write(' ')
            return self.replay
        with self.assertRaisesRegex(ValueError,'EVIDENCE_RETAINED'):self.invoke(mutate)
        self.assertIn('input:original_synthetic',p.read(self.out/'failure.json')['integrity_changes'])
    def test_result_file_byte_tamper_is_rejected(self):
        self.invoke();path=self.out/'replay.json';path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'RESULT_FILE_SHA'):p.verify(self.out)
    def test_top_level_result_tamper_is_rejected(self):
        self.invoke();result=p.read(self.out/'result.json');result['cause']='FIXED'
        (self.out/'result.json').write_text(p.canonical(result))
        with self.assertRaisesRegex(ValueError,'RESULT_SHA'):p.verify(self.out)
    def test_resealed_scope_change_is_rejected(self):
        plan=p.read(self.out/'plan.json');plan['original_seed']=42
        (self.out/'plan.json').write_text(p.canonical(plan));(self.out/'plan-sha.json').write_text(p.canonical(dict(sha256=p.digest(plan))))
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):p.load_plan(self.out)
    def test_original_input_change_fails_before_execution(self):
        self.inputs['original_synthetic'].write_text('{"modified":true}')
        with self.assertRaisesRegex(ValueError,'INPUT_OR_SCIENCE_CHANGED'):p.execute(self.out)
        self.assertFalse((self.out/'STARTED.json').exists())
    def test_existing_output_and_wrong_pin_rejected(self):
        with self.assertRaises(FileExistsError):p.prepare(self.inputs,self.out)
        self.inputs['original_synthetic'].write_text('tampered')
        with self.assertRaisesRegex(ValueError,'INPUT_SHA_MISMATCH'):p.prepare(self.inputs,self.root/'another-audit')
    def test_output_in_original_tree_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'SEPARATE_FROM_ORIGINAL_INPUTS'):p.prepare(self.inputs,self.inputs['original_synthetic'].parent/'bad-state')
    def test_passing_reconstruction_cannot_drop_the_original_rejection(self):
        self.family['rejections']=[]
        with self.assertRaisesRegex(ValueError,'EVIDENCE_RETAINED'):self.invoke()
        self.assertEqual(p.read(self.out/'failure.json')['primary_failure']['reason'],'ORIGINAL_NEGATIVE_FAILURE_NOT_REPRODUCED')
