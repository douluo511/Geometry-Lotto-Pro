import pytest
from research.formula_lab import statistics as stats


def test_small_space_distribution_hand_counted():
    # Select 2 of 4 in front and 1 of 3 at back: 18 equiprobable draws.
    dist=stats.joint_distribution((4,2,3,1))
    assert dist == pytest.approx({'0,0':2/18,'0,1':1/18,'1,0':8/18,'1,1':4/18,'2,0':2/18,'2,1':1/18})


def test_real_game_theory_independently_known_combinations():
    ssq=stats.theory('ssq'); dlt=stats.theory('dlt')
    assert ssq['d2']==pytest.approx(15/528)
    assert dlt['d2']==pytest.approx(10/595)
    assert ssq['exact']==pytest.approx(1/17721088)
    assert dlt['exact']==pytest.approx(1/21425712)
    assert sum(ssq['joint'].values())==pytest.approx(1)


def test_holm_uses_entire_declared_family_and_validates_nan():
    assert stats.holm([.01,.04,.03]) == pytest.approx([.03,.06,.06])
    with pytest.raises(ValueError): stats.holm([float('nan')])


def test_zero_hits_keeps_finite_nonzero_upper_confidence_limit():
    result=stats.rate([0]*20, 1/100)
    assert result['hits']==0 and result['n']==20
    assert result['ci95_exact'][0]==0
    assert result['ci95_exact'][1]==pytest.approx(0.168433470983)


def test_exact_paired_keeps_both_misses_and_pairs_direction():
    x=[1,1,1,0,0,0]; y=[0,0,0,0,0,0]
    result=stats.paired(x,y)
    assert result['n']==6 and result['both_miss']==3
    assert result['model_only']==3 and result['control_only']==0
    assert result['p_raw']==.25
    assert result['delta']==.5
    assert stats.paired([0]*10,[0]*10)['p_raw']==1
    with pytest.raises(ValueError): stats.paired([1],[1,0])


def test_block_interval_is_reproducible_and_not_resampled_independently():
    x=[i%3 for i in range(30)]
    assert stats.block_interval(x,x)==[0.0,0.0]
    a=stats.block_interval(x,[0]*30)
    assert a==stats.block_interval(x,[0]*30)
    assert a[0]>0
