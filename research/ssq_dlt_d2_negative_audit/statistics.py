"""Independent Decimal tail, Holm correction and finite permutation checks.

No call to the original statistics implementation, no seed search, no model
selection. The original one-sided family is retained exactly as registered.
"""
from collections import Counter
from decimal import Decimal,localcontext
from fractions import Fraction
from itertools import combinations,permutations
from math import comb,isfinite,isclose

MODELS=('R46-CBPAIR-SHRINK','R46-REPLICATED-PAIR')
NEGATIVES=('FAIR','SCRAMBLED_PAIR_STRONG','RING_SCRAMBLED')
GAMES={'SSQ':(33,6),'DLT':(35,5)}
# Same numerical tolerance as the pre-existing independent SciPy cross-check
# (outputs/V45-D2-study/check_study_stats.py). It is not the scientific alpha.
LEGACY_FLOAT_ABS_TOLERANCE=1e-10

def binomial_upper(hits,n,p):
    if type(n) is not int or type(hits) is not int or not 0<=hits<=n or not isinstance(p,Fraction) or not 0<p<1:
        raise ValueError('INVALID_EXACT_TAIL_INPUT')
    with localcontext() as ctx:
        ctx.prec=80
        pp=Decimal(p.numerator)/Decimal(p.denominator);qq=1-pp
        mass=qq**n;tail=mass if hits==0 else Decimal(0)
        for index in range(n):
            mass*=Decimal(n-index)/Decimal(index+1)*pp/qq
            if index+1>=hits:tail+=mass
        return min(1.0,max(0.0,float(tail)))

def holm(values):
    if not values or any(type(k) is not str or not isinstance(v,(int,float)) or isinstance(v,bool) or not isfinite(v) or not 0<=v<=1 for k,v in values.items()):
        raise ValueError('INVALID_HOLM_FAMILY')
    running=0.0;result={};size=len(values)
    for index,(key,value) in enumerate(sorted(values.items(),key=lambda pair:(pair[1],pair[0]))):
        running=max(running,(size-index)*value);result[key]=min(1.0,running)
    return result

def legal(nums,count,upper):
    if type(nums) is not list or len(nums)!=count or any(type(v) is not int or not 1<=v<=upper for v in nums) or len(set(nums))!=count:
        raise ValueError('INVALID_D2_OR_DRAW')

def rescore_family(document):
    """Rescore the complete original 12-test family, not a chosen subset."""
    bins={(scenario,game):{} for scenario in NEGATIVES for game in GAMES}
    for row in document['periods']:
        if row['scenario'] not in NEGATIVES:continue
        if row['game'] not in GAMES:raise ValueError('UNKNOWN_NEGATIVE_GAME')
        upper,k=GAMES[row['game']];legal(row['draw_front'],k,upper)
        rep,index=row['replication'],row['index']
        if type(rep) is not int or type(index) is not int or not 0<=rep<12 or not 240<=index<480 or type(row['training_end']) is not int or row['training_end']!=index-1:
            raise ValueError('NEGATIVE_PERIOD_OR_TRAINING_BOUNDARY')
        slot=(rep,index);bucket=bins[(row['scenario'],row['game'])]
        if slot in bucket:raise ValueError('DUPLICATE_NEGATIVE_PERIOD')
        scored={}
        for model in MODELS:
            legal(row['predictions'][model],2,upper)
            hit=int(set(row['predictions'][model])<=set(row['draw_front']))
            if type(row['hits'][model]) is not int or row['hits'][model]!=hit:raise ValueError('WRONG_STORED_NEGATIVE_SCORE')
            scored[model]=hit
        bucket[slot]=scored
    selected=[s for s in document['summaries'] if s['scenario'] in NEGATIVES]
    summaries={(s['scenario'],s['game']):s for s in selected}
    if len(selected)!=6 or set(summaries)!=set(bins):raise ValueError('COMPLETE_NEGATIVE_SUMMARIES_REQUIRED')
    raw={};cells={}
    for (scenario,game),bucket in bins.items():
        if len(bucket)!=2880:raise ValueError('MISSING_NEGATIVE_PERIOD')
        upper,k=GAMES[game];p=Fraction(comb(k,2),comb(upper,2))
        for model in MODELS:
            key='|'.join((scenario,game,model));hits=sum(v[model] for v in bucket.values())
            value=binomial_upper(hits,2880,p);old=summaries[(scenario,game)]['metrics'][model]
            if old['n']!=2880 or old['hits']!=hits or not isclose(old['p_fair_one_sided'],value,rel_tol=0,abs_tol=LEGACY_FLOAT_ABS_TOLERANCE):
                raise ValueError('ORIGINAL_NEGATIVE_SUMMARY_MISMATCH')
            raw[key]=value;cells[key]=dict(n=2880,hits=hits,p0=float(p),p_one_sided=value,
                original_float_p=old['p_fair_one_sided'],absolute_float_error=abs(old['p_fair_one_sided']-value))
    adjusted=holm(raw)
    for key in cells:cells[key]['holm_p']=adjusted[key]
    return dict(status='PASS_ORIGINAL_FAMILY_RECOMPUTED',family_size=12,alpha=0.05,
        cells=cells,rejections=[key for key in sorted(cells) if adjusted[key]<=.05],
        method='DECIMAL_80_DIGIT_PMFS_SUMMED_THEN_ORIGINAL_ONE_SIDED_HOLM',
        legacy_float_absolute_tolerance=LEGACY_FLOAT_ABS_TOLERANCE,
        maximum_absolute_float_error=max(c['absolute_float_error'] for c in cells.values()),new_seeds=0)

def permutation_check(n=6,k=3):
    """Exhaust all tiny permutations for every latent k-subset, no Monte Carlo."""
    if type(n) is not int or type(k) is not int or not 2<=k<n<=6:raise ValueError('TINY_EXHAUSTIVE_SCOPE_REQUIRED')
    labels=tuple(range(1,n+1));expected=comb(n,k);all_perm=tuple(permutations(labels));checked=0
    for latent in combinations(labels,k):
        counts=Counter(tuple(sorted(perm[i-1] for i in latent)) for perm in all_perm)
        if len(counts)!=expected or len(set(counts.values()))!=1:raise ValueError('PERMUTATION_NOT_UNIFORM')
        for pair in combinations(labels,2):
            successes=sum(count for front,count in counts.items() if set(pair)<=set(front))
            if Fraction(successes,len(all_perm))!=Fraction(comb(k,2),comb(n,2)):raise ValueError('PERMUTATION_PAIR_LAW_FAILED')
        checked+=1
    return dict(status='PASS_EXHAUSTIVE_FINITE_MAPPING',n=n,k=k,latent_subsets=checked,
        permutations_per_latent=len(all_perm),mappings=checked*len(all_perm),
        assumption='UNIFORM_PERMUTATION_INDEPENDENT_OF_LATENT_SET_AND_PRIOR_INFORMATION',
        not_proved=['MERSENNE_TWISTER_FINITE_STREAM_INDEPENDENCE','CAUSE_OF_THE_OBSERVED_69_HITS','REAL_LOTTERY_FAIRNESS'])
