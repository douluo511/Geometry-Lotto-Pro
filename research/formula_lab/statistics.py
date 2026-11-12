"""Exploratory inference; never an automatic claim of predictive edge."""
import math
from collections import Counter

import numpy as np
from scipy.stats import binomtest

from research.supercompute.engine import SPECS

BINARY=('d2','front_full','back_full','exact')
METRICS=BINARY+('front_hits','back_hits')


def joint_distribution(spec):
    fm,fp,bm,bp=spec
    def zone(m,k):
        return {h:math.comb(k,h)*math.comb(m-k,k-h)/math.comb(m,k)
                for h in range(k+1) if 0<=k-h<=m-k}
    return {f'{f},{b}':pf*pb for f,pf in zone(fm,fp).items() for b,pb in zone(bm,bp).items()}


def theory(game):
    fm,fp,bm,bp=SPECS[game]
    return dict(d2=math.comb(fp,2)/math.comb(fm,2),
                front_full=1/math.comb(fm,fp),back_full=1/math.comb(bm,bp),
                exact=1/(math.comb(fm,fp)*math.comb(bm,bp)),
                front_hits=fp*fp/fm,back_hits=bp*bp/bm,joint=joint_distribution(SPECS[game]))


def holm(pvalues):
    if not pvalues or any(not math.isfinite(x) or not 0<=x<=1 for x in pvalues):
        raise ValueError('finite p-values in [0,1] required')
    adjusted=[0.0]*len(pvalues); previous=0.0
    for rank,i in enumerate(sorted(range(len(pvalues)),key=lambda i:(pvalues[i],i))):
        previous=max(previous,min(1.0,(len(pvalues)-rank)*pvalues[i]))
        adjusted[i]=previous
    return adjusted


def _binary(values):
    if not values or any(type(v) is not int or v not in (0,1) for v in values):
        raise ValueError('nonempty binary observations required')


def rate(values,p):
    _binary(values)
    test=binomtest(sum(values),len(values),p=p)
    ci=test.proportion_ci(confidence_level=.95,method='exact')
    return dict(hits=sum(values),n=len(values),rate=sum(values)/len(values),
                ci95_exact=[float(ci.low),float(ci.high)],p_raw=float(test.pvalue))


def block_interval(model,control,block=7,repeats=499):
    if len(model)!=len(control) or not model or not 1<=block<=30 or not 99<=repeats<=1999:
        raise ValueError('matched bounded cohort required')
    delta=np.asarray(model,dtype=float)-np.asarray(control,dtype=float)
    if not np.all(np.isfinite(delta)):raise ValueError('nonfinite score')
    n=len(delta);block=min(block,n)
    rng=np.random.default_rng(774131)
    starts=rng.integers(0,n,size=(repeats,math.ceil(n/block)))
    indices=((starts[:,:,None]+np.arange(block))%n).reshape(repeats,-1)[:,:n]
    return np.quantile(delta[indices].mean(axis=1),[.025,.975]).tolist()


def paired(model,control):
    _binary(model);_binary(control)
    if len(model)!=len(control):raise ValueError('cohort mismatch')
    a=sum(m==1 and c==0 for m,c in zip(model,control))
    b=sum(m==0 and c==1 for m,c in zip(model,control))
    both=sum(m==c==1 for m,c in zip(model,control))
    return dict(n=len(model),model_only=a,control_only=b,both_hit=both,
                both_miss=len(model)-a-b-both,delta=(a-b)/len(model),
                p_raw=float(binomtest(a,a+b).pvalue) if a+b else 1.0,
                delta_ci95_block_exploratory=block_interval(model,control))


def summarize(games):
    """Holm over ALL games, both modes, ALL controls and four binary endpoints."""
    summaries={}; tests=[]
    for game,result in games.items():
        fair=theory(game);summaries[game]={}
        for mode in ('frozen','rolling'):
            rows=result[mode]['rows']
            if not rows:raise ValueError('no evaluation periods')
            names=list(rows[0]['scores'])
            values={name:{m:[r['scores'][name][m] for r in rows] for m in METRICS} for name in names}
            summary=dict(n=len(rows),theory=fair,models={},paired={})
            for name in names:
                v=values[name]
                summary['models'][name]={m:rate(v[m],fair[m]) for m in BINARY}
                # Control-vs-theory results are descriptive intervals, not hidden tests.
                if name!='FORMULA':
                    for metric in BINARY:summary['models'][name][metric].pop('p_raw')
                else:
                    for metric in BINARY:tests.append(summary['models'][name][metric])
                summary['models'][name]['front_mean']=sum(v['front_hits'])/len(rows)
                summary['models'][name]['back_mean']=sum(v['back_hits'])/len(rows)
                summary['models'][name]['joint_histogram']=dict(Counter(f"{f},{b}" for f,b in zip(v['front_hits'],v['back_hits'])))
            for control in names:
                if control=='FORMULA':continue
                comparison={m:paired(values['FORMULA'][m],values[control][m]) for m in BINARY}
                tests.extend(comparison.values())
                for metric in ('front_hits','back_hits'):
                    a,b=values['FORMULA'][metric],values[control][metric]
                    comparison[metric]=dict(delta=(sum(a)-sum(b))/len(rows),
                                            delta_ci95_block_exploratory=block_interval(a,b))
                summary['paired'][control]=comparison
            summaries[game][mode]=summary
    for item,p in zip(tests,holm([t['p_raw'] for t in tests])):
        item['p_holm_studywide']=p;item['family_size']=len(tests)
    return dict(games=summaries,comparisons=len(tests),formal_A=0,edge='NO_EDGE',
        assumptions='Binomial intervals/tests assume iid Bernoulli trials; paired exact tests assume exchangeable discordances. Adaptive rolling dependence can violate these. Block intervals are unadjusted exploratory diagnostics. No test corrects historical researcher reuse.',
        null_scope='Fixed #479 research NULL; formal V4.7 NULL unchanged and not authenticated here.')
