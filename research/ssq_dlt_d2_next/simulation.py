"""Predeclared positive/negative controls, never lottery hit-rate evidence."""
from collections import Counter
from datetime import date,timedelta
import hashlib
from itertools import combinations
import math
import random

from research.ssq_dlt_v45 import models as original

SPEC=dict(seed=2026101901,replications=12,warmup=240,evaluation_draws=240,
          scenarios=['FAIR','MARGINAL_STRONG','PAIR_WEAK','PAIR_STRONG','PAIR_REVERSAL','SCRAMBLED_PAIR_STRONG','RING_PERSISTENT','RING_SCRAMBLED'],
          marginal_weight=3.0,weak_pair_odds_ratio=2.0,strong_pair_odds_ratio=8.0,
          reversal_at_evaluation_index=120,ring_mixture_probability=0.25,
          reference_scope='GENERATOR_KNOWLEDGE_FOR_POSITIVE_CONTROLS_ARBITRARY_FIXED_PAIR_FOR_NEGATIVE_CONTROLS',
          reference_is_forecast_candidate=False)


def stream_seed(game,scenario,replication):
    raw=original.canonical_bytes([SPEC['seed'],game,scenario,replication])
    return int.from_bytes(hashlib.sha256(raw).digest(),'big')


def tilted_uniform(rng,n,k,pair,odds_ratio):
    """Exact exponential tilt of a uniform fixed-k draw on pair inclusion.

    P(pair hits)=OR*p0/(1+(OR-1)*p0). Conditional on hit or miss, draw
    uniformly from that support; reject-until-miss has bounded expectation
    <=1.03 here. A hard bound fails closed rather than changing the law.
    """
    p0=k*(k-1)/(n*(n-1)); p=odds_ratio*p0/(1+(odds_ratio-1)*p0)
    others=[x for x in range(1,n+1) if x not in pair]
    if rng.random()<p:return sorted(list(pair)+rng.sample(others,k-2))
    for _ in range(1000):
        draw=sorted(rng.sample(range(1,n+1),k))
        if not set(pair)<=set(draw):return draw
    raise RuntimeError('SYNTHETIC_REJECTION_LIMIT')


def synthetic_history(game,scenario,replication):
    from .models import sample_conditional
    if scenario not in SPEC['scenarios'] or type(replication) is not int or not 0<=replication<SPEC['replications']:
        raise ValueError('UNREGISTERED_SYNTHETIC_STREAM')
    n,k,bn,bk=original.RULES[game];rng=random.Random(stream_seed(game,scenario,replication))
    rows=[];oracles=[];ring=rng.sample(range(1,n+1),n)
    for index in range(SPEC['warmup']+SPEC['evaluation_draws']):
        pair=[1,2]
        if scenario=='PAIR_REVERSAL' and index>=SPEC['warmup']+SPEC['reversal_at_evaluation_index']:pair=[n-1,n]
        if scenario.startswith('RING_'):
            if scenario=='RING_SCRAMBLED':ring=rng.sample(range(1,n+1),n)
            pair=sorted(ring[:2]) if scenario=='RING_PERSISTENT' else [1,2]
            if rng.random()<SPEC['ring_mixture_probability']:
                start=rng.randrange(n);front=sorted(ring[(start+j)%n] for j in range(k))
            else:front=sorted(rng.sample(range(1,n+1),k))
        elif scenario=='FAIR':front=sorted(rng.sample(range(1,n+1),k))
        elif scenario=='MARGINAL_STRONG':
            weights=[SPEC['marginal_weight'] if x in pair else 1.0 for x in range(1,n+1)]
            front=sample_conditional(weights,k,rng)
        else:
            odds=SPEC['weak_pair_odds_ratio'] if scenario=='PAIR_WEAK' else SPEC['strong_pair_odds_ratio']
            front=tilted_uniform(rng,n,k,pair,odds)
            if scenario=='SCRAMBLED_PAIR_STRONG':
                permutation=rng.sample(range(1,n+1),n);front=sorted(permutation[x-1] for x in front)
        rows.append(dict(game=game,issue=f'{index+1:07d}' if game=='SSQ' else f'{index+1:05d}',
                         draw_date=(date(2000,1,1)+timedelta(days=index)).isoformat(),front=front,
                         back=list(range(1,bk+1))))
        oracles.append(pair)
    return rows,oracles


def full_hit(pair,front):
    if type(pair) is not list or len(pair)!=2 or len(set(pair))!=2 or any(type(x) is not int or x<1 for x in pair):
        raise ValueError('EXACTLY_TWO_DISTINCT_POSITIVE_INTEGER_DAN_REQUIRED')
    return int(set(pair)<=set(front))


def pair_brier(probabilities,front,n,k):
    """Every pair is dependent. Return ONE aggregate loss for ONE draw."""
    original.validate_numbers(front,k,n)
    if set(probabilities)!=set(combinations(range(1,n+1),2)):raise ValueError('COMPLETE_PAIR_PROBABILITIES_REQUIRED')
    if any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities.values()):raise ValueError('INVALID_PAIR_PROBABILITY')
    draw_pairs=list(combinations(sorted(front),2))
    return (sum(p*p for p in probabilities.values())-2*sum(probabilities[p] for p in draw_pairs)+math.comb(k,2))/math.comb(n,2)


def run_controls(progress=None):
    from .models import MODEL_IDS,predict_candidates
    from .inference import common_metrics
    records=[]; summaries=[]
    for scenario in SPEC['scenarios']:
        for game in ('SSQ','DLT'):
            hit_lists={m:[] for m in (*MODEL_IDS,original.PRIMARY_MODEL,original.NULL_MODEL,'GENERATOR_REFERENCE_PAIR')}
            selected_true={m:0 for m in MODEL_IDS};brier=[];n,k,_,_=original.RULES[game]
            for replication in range(SPEC['replications']):
                rows,oracles=synthetic_history(game,scenario,replication)
                counts=Counter(pair for row in rows[SPEC['warmup']-60:SPEC['warmup']] for pair in combinations(row['front'],2))
                marg=Counter(x for row in rows[SPEC['warmup']-60:SPEC['warmup']] for x in row['front'])
                pairs=tuple(combinations(range(1,n+1),2))
                for index in range(SPEC['warmup'],len(rows)):
                    target=rows[index];new=predict_candidates(game,rows[:index])
                    primary=list(min(pairs,key=lambda p:(-counts[p],-marg[p[0]]-marg[p[1]],p)))
                    null=sorted(original._sample(original.DEFAULT_SEED,game,f'SYNTHETIC:{scenario}:{replication}:{index}',original.NULL_MODEL,'dan',2,n))
                    predictions={m:new[m]['d2'] for m in MODEL_IDS}
                    predictions.update({original.PRIMARY_MODEL:primary,original.NULL_MODEL:null,'GENERATOR_REFERENCE_PAIR':oracles[index]})
                    hits={m:full_hit(pair,target['front']) for m,pair in predictions.items()}
                    for m,hit in hits.items():hit_lists[m].append(hit)
                    for m in MODEL_IDS:selected_true[m]+=int(predictions[m]==oracles[index])
                    loss=pair_brier(new[MODEL_IDS[0]]['pair_probabilities'],target['front'],n,k);brier.append(loss)
                    records.append(dict(game=game,scenario=scenario,replication=replication,index=index,
                        training_end=index-1,predictions=predictions,hits=hits,draw_front=target['front'],
                        cbpair_brier=loss,formal_A=0,decision='NO_EDGE'))
                    old=rows[index-60]
                    counts.subtract(combinations(old['front'],2));counts.update(combinations(target['front'],2))
                    marg.subtract(old['front']);marg.update(target['front'])
            metrics={m:common_metrics(game,hits,hit_lists[original.NULL_MODEL]) for m,hits in hit_lists.items()}
            p0=k*(k-1)/(n*(n-1))
            summaries.append(dict(game=game,scenario=scenario,replications=SPEC['replications'],
                n=len(brier),metrics=metrics,selected_reference_pair=selected_true,
                reference_kind='ARBITRARY_FIXED_PAIR_NOT_AN_ORACLE' if scenario in ('FAIR','SCRAMBLED_PAIR_STRONG','RING_SCRAMBLED') else 'KNOWN_GENERATOR_FAVOURED_PAIR_NOT_A_LEARNED_FORECAST',
                mean_cbpair_brier=sum(brier)/len(brier),uniform_pair_brier=p0*(1-p0),
                brier_observation_unit='ONE_DRAW_NOT_ONE_PAIR',scope='SYNTHETIC_MECHANISM_CONTROL_NOT_LOTTERY_EVIDENCE'))
            if progress:progress(dict(stage='synthetic',scenario=scenario,game=game,done=True))
    return dict(spec=SPEC,summaries=summaries,periods=records,formal_A=0,decision='NO_EDGE')
