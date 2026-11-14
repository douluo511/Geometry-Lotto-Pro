"""Regressions for missing numerical and evidence contracts (synthetic fixtures)."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute import v47_models as core, v47_registry as reg
from research.supercompute import v47_integrated as integ
from research.supercompute.tests.test_v47_registry import fixtures


class ModelRepairTests(unittest.TestCase):
    def test_ewma_consumes_half_life_and_predict_uses_fit(self):
        rows = fixtures('ssq')
        a, b = reg.EWMAModel(), reg.EWMAModel()
        ca = {'model_options': {'EWMA': {'half_life': 2}}}
        cb = {'model_options': {'EWMA': {'half_life': 80}}}
        fa, fb = a.fit(rows, 'ssq', ca), b.fit(rows, 'ssq', cb)
        self.assertEqual(fa['half_life'], 2)
        self.assertNotEqual(a.probs, b.probs)
        self.assertEqual(fb['half_life'], 80)
        self.assertEqual(a.predict(rows, 'ssq', ca), a.predict(rows[:-10], 'ssq', ca))

    def test_shrinkmix_records_long_term_prior(self):
        model = reg.ShrinkMixModel()
        fit = model.fit(fixtures('ssq'), 'ssq', {})
        self.assertIn('long_term_prior', fit)
        self.assertAlmostEqual(sum(fit['long_term_prior']['front']), 6)

    def test_physics_exposes_real_trajectories_and_event_counts(self):
        run = core.physics_toy('ssq', seed=11, steps=100)
        self.assertEqual(run.get('status'), 'UNCALIBRATED_PHYSICS_SIMULATION')
        self.assertEqual(run, core.physics_toy('ssq', seed=11, steps=100))
        self.assertGreater(run['areas']['front']['pair_impulses'], 0)
        self.assertGreater(run['areas']['front']['wall_impulses'], 0)
        self.assertEqual(len(run['areas']['front']['final_balls']), 33)
        self.assertGreater(len(run['areas']['front']['trajectory']), 2)
        self.assertNotEqual(run['areas']['front']['trajectory'][0]['balls'],
                            run['areas']['front']['trajectory'][-1]['balls'])

    def test_elastic_unequal_mass_collision_conserves_momentum(self):
        from research.supercompute import v47_physics as physics
        balls = [dict(mass=2., radius=.1, position=[.4,.5], velocity=[1.,0.]),
                 dict(mass=1., radius=.1, position=[.59,.5], velocity=[-1.,0.])]
        result = physics.step_system(balls, dt=.001, restitution=1., friction=0.,
                                     drag=0., airflow=(0.,0.))
        self.assertEqual(result['pair_impulses'], 1)
        self.assertAlmostEqual(2*balls[0]['velocity'][0]+balls[1]['velocity'][0], 1.)
        self.assertAlmostEqual(balls[0]['velocity'][0], -1/3)
        self.assertAlmostEqual(balls[1]['velocity'][0], 5/3)

    def test_m2_reports_uncertainty(self):
        result = core.m2_refutation([0,0,1,0], .1)
        self.assertIn('hit_rate_wilson95', result)
        self.assertLess(result['hit_rate_wilson95'][0], .25)
        self.assertGreater(result['hit_rate_wilson95'][1], .25)

    def test_lineage_contains_recomputable_id_genes_and_real_mutation(self):
        run = integ.cell_division(fixtures('ssq'), 'ssq', generations=2, validation=2)
        children = []
        for generation in run['lineage']:
            for cell in generation['evaluated']:
                self.assertIn('genes', cell)
                self.assertEqual(cell['id'], integ._identity(cell['genes']))
                if cell['origin'] == 'crossover_mutation':
                    children.append(cell)
                    self.assertEqual(len(cell['parents']), 2)
                    mutation = cell['mutation']
                    self.assertNotEqual(mutation['before'], mutation['after'])
                    self.assertEqual(cell['genes'][mutation['gene']], mutation['after'])
        self.assertGreaterEqual(len(children), 4)

    def test_previous_champion_rejects_identity_tampering(self):
        from research.supercompute.v47_forecast import _previous
        payload = {'schema':'SSQDLT_V47_UNIFIED_11_V1','game':'ssq',
                   'history_last_issue':'4100',
                   'evolution': {'champion': core.parameters(), 'champion_id':'bad'}}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'previous.json'
            p.write_bytes(core.canonical(payload))
            with self.assertRaisesRegex(ValueError, 'identity'):
                _previous(p, 'ssq')

    def test_history_rejects_reversed_issue_and_equal_dates(self):
        rows = fixtures('ssq')
        bad = copy.deepcopy(rows)
        bad[-1]['issue'] = '3999'
        with self.assertRaises(ValueError):
            core.validate_history(bad, 'ssq')
        bad = copy.deepcopy(rows)
        bad[-1]['draw_date'] = bad[-2]['draw_date']
        with self.assertRaises(ValueError):
            core.validate_history(bad, 'ssq')


if __name__ == '__main__':
    unittest.main()
