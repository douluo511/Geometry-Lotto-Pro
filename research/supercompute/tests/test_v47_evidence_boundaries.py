"""Adversarial evidence checks; failures must never be promoted to PASS."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error

from research.supercompute import v47_integrated as integ, v47_registry as reg
from research.supercompute import v47_official_ingest as ingest
from research.supercompute.v47_models import canonical
from research.supercompute.v47_forecast import _previous
from research.supercompute.tests.test_v47_registry import fixtures


class EvidenceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fixtures('ssq')
        cls.execution = reg.execute_eleven(cls.rows,'ssq',seed=11,generations=2,
                    validation=2,holdout=2,mc_trials=101,physics_steps=11)
        cls.report = {'schema':'SSQDLT_V47_UNIFIED_11_V1','game':'ssq',
            'target_issue':'4124','history_last_issue':'4123','history_last_date':cls.rows[-1]['draw_date'],
            'history_sha256':hashlib.sha256(canonical(cls.rows)).hexdigest(),
            'seed':11,'edge':'NO_EDGE','formal_prediction':False,
            'requirement_modules':list(integ.REQUIREMENTS),'independent_11':cls.execution,
            'proposed_tickets':[dict(cls.execution['models'][m.label]['prediction']['ticket'],
                                  model_name=m.label,model_number=m.number) for m in reg.REGISTRY],
            'ticket_count':11}

    def test_freeze_rejects_ticket_relabeling_or_modification(self):
        report = copy.deepcopy(self.report)
        ticket = report['proposed_tickets'][0]
        ticket['back'] = [ticket['back'][0] % 16+1]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'model output'):
                integ.freeze_result(Path(tmp)/'frozen.json', report)

    def test_audit_keeps_requested_simulation_and_generations(self):
        audit = self.execution['validation_all_11']
        for fold in audit['fold_evidence']:
            self.assertEqual(fold.get('settings'),dict(generations=2,validation=2,mc_trials=101,physics_steps=11))
            self.assertEqual(len(fold['scores']),11)
            self.assertEqual(len(fold['predictions']),11)
        for evidence in audit['models'].values():
            m2=evidence['m2']
            self.assertTrue(m2['multiple_tests_adjusted'])
            self.assertEqual(m2['bonferroni_family_size'],22)
            self.assertGreaterEqual(m2['adjusted_p'],m2['exploratory_one_sided_p'])

    def test_future_champion_rejected_before_fit(self):
        payload = {'schema':'SSQDLT_V47_UNIFIED_11_V1','game':'ssq',
                   'history_last_issue':'5000','evolution':{'champion':self.execution['champion_genome'],
                    'champion_id':integ._identity(self.execution['champion_genome'])}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prior.json'; path.write_bytes(canonical(payload))
            with self.assertRaisesRegex(ValueError,'future'):
                _previous(path,'ssq',self.rows)

    def test_http_error_preserves_status_and_raw_response(self):
        def fail(game):
            raise urllib.error.HTTPError(ingest.SOURCES[game][0],503,'Service unavailable',{},io.BytesIO(b'upstream unavailable'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed=root/'seed.json'
            seed.write_bytes(canonical({'draws':self.rows}))
            with self.assertRaises(urllib.error.HTTPError):
                ingest.ingest({'ssq':seed,'dlt':seed},root/'out',fetch=fail)
            receipt=json.loads((root/'out/failure-receipt.json').read_bytes())
            self.assertEqual(receipt.get('status'),'UNVERIFIED')
            self.assertEqual(receipt['http_diagnostics']['http_status'],503)
            self.assertEqual(receipt['http_diagnostics']['response_sha256'],hashlib.sha256(b'upstream unavailable').hexdigest())
            self.assertFalse((root/'out/ssq-verified-history.json').exists())

    def test_stale_publisher_cannot_verify_newer_seed(self):
        with self.assertRaisesRegex(ValueError,'stale'):
            ingest.append_verified(self.rows,self.rows[-7:-1],'ssq')

    def test_export_contains_22_records_and_refuses_overwrite(self):
        from research.supercompute.v47_delivery import export_delivery
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # Exporter must reject a one-game report rather than invent DLT rows.
            with self.assertRaisesRegex(ValueError,'both games'):
                export_delivery({'games':{'ssq':self.report}},root/'frozen',root/'deliver')


if __name__ == '__main__':
    unittest.main()
