"""Synthetic, allocation-inclusive benchmark; no accuracy or GPU claims."""
import argparse
import cProfile
import json
import platform
import pstats
import random
import statistics
import time

import numpy as np

from research.formula_lab.search import fit, select, Config
from research.supercompute.engine import SPECS


def synthetic_rows(game,n=180,seed=20261112):
    if game not in SPECS or type(n) is not int or not 3<=n<=2500:
        raise ValueError('bounded synthetic history required')
    rng=random.Random(seed);fm,fp,bm,bp=SPECS[game]
    return [dict(issue=str(900000+i),front=sorted(rng.sample(range(1,fm+1),fp)),
                 back=sorted(rng.sample(range(1,bm+1),bp))) for i in range(n)]


def measure(repeats=7,rows=180,parallel=False):
    if type(repeats) is not int or not 3<=repeats<=21 or type(rows) is not int or not 40<=rows<=1000:
        raise ValueError('benchmark limits: repeats 3..21, rows 40..1000')
    datasets={g:synthetic_rows(g,rows) for g in SPECS}
    for g,data in datasets.items():
        if fit(data,g,'reference')!=fit(data,g,'numpy'):raise AssertionError('backend parity failure')
    samples={b:[] for b in ('reference','numpy')}
    # Alternate execution order and include allocation, validation, aggregation.
    for i in range(repeats):
        for backend in (('reference','numpy') if i%2==0 else ('numpy','reference')):
            start=time.perf_counter()
            for game,data in datasets.items():fit(data,game,backend)
            samples[backend].append(time.perf_counter()-start)
    med={k:statistics.median(v) for k,v in samples.items()}
    profile=cProfile.Profile()
    profile.runcall(select,synthetic_rows('ssq',80),'ssq',Config(train=60,validation=20,holdout=10))
    entries=sorted(pstats.Stats(profile).stats.items(),key=lambda x:-x[1][3])[:8]
    top=[dict(function=key[2],calls=v[1],cumulative_seconds=v[3]) for key,v in entries]
    result=dict(synthetic_only=True,parity_verified=True,repeats=repeats,rows=rows,
        reference_seconds=med['reference'],numpy_seconds=med['numpy'],
        speedup=med['reference']/med['numpy'],timings=samples,
        preferred_backend='numpy' if med['numpy']<med['reference'] else 'reference',
        cpu_workers=1,profile_top=top,python=platform.python_version(),numpy=np.__version__,
        platform=platform.system(),jit='NOT_USED_NO_MEASURED_NEED',formal_A=0,edge='NO_EDGE')
    if parallel:
        start=time.perf_counter()
        for g,data in datasets.items():
            if fit(data,g,workers=2)!=fit(data,g):raise AssertionError('process parity failure')
        result['two_worker_seconds_including_startup_and_reference']=time.perf_counter()-start
        result['two_workers_default']=False
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parallel',action='store_true')
    args=p.parse_args()
    print(json.dumps(measure(parallel=args.parallel),sort_keys=True))


if __name__=='__main__':main()
