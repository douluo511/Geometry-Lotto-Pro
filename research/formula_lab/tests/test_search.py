"""Only seeded synthetic data. No real draw fixtures or network calls."""
import copy
from dataclasses import replace
import random

import numpy as np
import pytest

from research.formula_lab import search as lab
from research.supercompute.engine import SPECS


def synthetic(game='ssq', n=110, seed=19):
    rng = random.Random(seed)
    fm, fp, bm, bp = SPECS[game]
    return [dict(issue=str(100000 + i),
                 front=sorted(rng.sample(range(1, fm + 1), fp)),
                 back=sorted(rng.sample(range(1, bm + 1), bp))) for i in range(n)]


@pytest.mark.parametrize('game', ['ssq', 'dlt'])
def test_reference_and_vector_fit_identical_including_ties(game):
    rows = synthetic(game)
    a = lab.fit(rows[:80], game, backend='reference')
    b = lab.fit(rows[:80], game, backend='numpy')
    assert a == b
    assert len(a) == 72
    assert lab.fit(rows[:80], game, backend='numpy', workers=2) == a


def test_hand_computed_modular_fit_and_smallest_residual_tie():
    # Constant position value produces zero offset for ATOM:LAG1.
    rows = [dict(issue=str(10000 + i), front=[1,2,3,4,5,6], back=[1]) for i in range(50)]
    fitted = lab.fit(rows, 'ssq')
    item = next(x for x in fitted if x['expr']['id'] == 'ATOM:LAG1:NONE:W8')
    assert item['offsets'] == {'front': [0]*6, 'back': [0]}
    assert lab.predict_one(rows, 'ssq', item)['front'] == [1,2,3,4,5,6]


def test_freeze_uses_only_development_and_parameters_never_refit():
    rows = synthetic()
    cfg = lab.Config(train=60, validation=20, holdout=10)
    model = lab.select(rows[:80], 'ssq', cfg)
    before = copy.deepcopy(model)
    pred = lab.predict(rows[:80], 'ssq', model)
    changed = copy.deepcopy(rows)
    changed[80:] = synthetic(n=30, seed=111)
    assert lab.select(changed[:80], 'ssq', cfg) == model
    assert lab.predict(changed[:80], 'ssq', model) == pred
    lab.predict(rows[:90], 'ssq', model)
    assert model == before
    assert model['fit_last_issue'] == rows[59]['issue']


def test_test_outcome_cannot_change_own_prediction_or_prior_decisions():
    rows = synthetic(n=90)
    cfg = lab.Config(train=60, validation=20, holdout=10)
    a = lab.evaluate(rows, 'ssq', cfg)
    changed = copy.deepcopy(rows)
    changed[85]['front'] = [1,2,3,4,5,6]
    changed[85]['back'] = [1]
    b = lab.evaluate(changed, 'ssq', cfg)
    for mode in ('frozen', 'rolling'):
        assert a[mode]['rows'][:5] == b[mode]['rows'][:5]
        assert a[mode]['rows'][5]['predictions'] == b[mode]['rows'][5]['predictions']
        assert len(a[mode]['rows']) == 10
    assert a['frozen']['model'] == b['frozen']['model']


def test_complexity_penalty_is_applied_before_selection():
    rows = synthetic(n=80)
    low = lab.select(rows, 'ssq', lab.Config(train=60, validation=20, holdout=10, penalty=0))
    high = lab.select(rows, 'ssq', lab.Config(train=60, validation=20, holdout=10, penalty=2))
    assert sum(x['complexity'] for x in high['selected']) <= sum(x['complexity'] for x in low['selected'])
    assert all(x['penalized_score'] == pytest.approx(x['coverage'] - 2*x['complexity']) for x in high['selected'])


def test_candidate_and_ensemble_tickets_are_legal():
    for game in SPECS:
        rows = synthetic(game, n=80)
        model = lab.select(rows, game, lab.Config(train=60, validation=20, holdout=10))
        for t in [lab.predict(rows, game, model)] + [lab.predict_one(rows, game, f) for f in model['selected']]:
            fm, fp, bm, bp = SPECS[game]
            assert len(t['front']) == fp and sorted(set(t['front'])) == t['front']
            assert len(t['back']) == bp and sorted(set(t['back'])) == t['back']
            assert 1 <= min(t['front']) <= max(t['front']) <= fm
            assert 1 <= min(t['back']) <= max(t['back']) <= bm
            assert len(t['d2_pair']) == 2 and set(t['d2_pair']) <= set(t['front'])


@pytest.mark.parametrize('change', [dict(train=0), dict(holdout=0), dict(workers=9), dict(penalty=float('nan')), dict(validation=True)])
def test_resource_or_invalid_parameters_rejected(change):
    with pytest.raises(ValueError):
        lab.Config(**change)


def test_duplicate_issue_and_unsorted_or_boolean_balls_rejected():
    rows = synthetic(n=90)
    for mutate in (lambda x: x[2].update(issue=x[1]['issue']),
                   lambda x: x[2].update(front=[True,2,3,4,5,6]),
                   lambda x: x[2].update(front=[2,1,3,4,5,6])):
        bad = copy.deepcopy(rows)
        mutate(bad)
        with pytest.raises(ValueError):
            lab.evaluate(bad, 'ssq', lab.Config(train=60, validation=20, holdout=10))


def test_edited_frozen_model_refused():
    rows = synthetic(n=80)
    model = lab.select(rows, 'ssq', lab.Config(train=60, validation=20, holdout=10))
    model['selected'][0]['offsets']['front'][0] += 1
    with pytest.raises(ValueError):
        lab.predict(rows, 'ssq', model)
