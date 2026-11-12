"""Causal selection with frozen fitted parameters and bounded NumPy fitting."""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
import math
import random

import numpy as np

from research.formula_lab import expressions as ex
from research.supercompute.engine import SPECS, check_balls, derive_seed, ticket


@dataclass(frozen=True)
class Config:
    train: int = 180
    validation: int = 60
    holdout: int = 120
    penalty: float = 0.005
    workers: int = 1

    def __post_init__(self):
        for value, lo, hi in ((self.train,40,2000), (self.validation,10,150),
                              (self.holdout,1,300), (self.workers,1,2)):
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError('bounded integer resource configuration required')
        if isinstance(self.penalty, bool) or not math.isfinite(self.penalty) or not 0 <= self.penalty <= 10:
            raise ValueError('finite nonnegative complexity penalty required')


def validate(rows, game):
    if game not in SPECS or not isinstance(rows, list) or not 3 <= len(rows) <= 2500:
        raise ValueError('bounded history and known game required')
    fm, fp, bm, bp = SPECS[game]
    previous = -1
    for row in rows:
        issue = row.get('issue')
        if not isinstance(issue, str) or not issue.isascii() or not issue.isdigit() or len(issue) > 9 or int(issue) <= previous:
            raise ValueError('strictly increasing unique numeric issue identities required')
        previous = int(issue)
        check_balls(row.get('front'), fp, fm)
        check_balls(row.get('back'), bp, bm)


def _fit_area(args):
    rows, area, maximum, count, backend = args
    n = len(rows)
    if backend == 'reference':
        return [[ex.learn_offset(e, rows, n, area, p, maximum) for p in range(count)] for e in ex.GRAMMAR]
    if backend != 'numpy':
        raise ValueError('unknown computation backend')
    start = max(3, n-max(ex.WINDOWS))
    js = np.arange(start,n)
    balls = np.asarray([r[area] for r in rows], dtype=np.int64)-1
    atoms = {f'LAG{k}': balls[js-k] for k in (1,2,3)}
    atoms['ISSUE'] = np.broadcast_to(np.asarray([int(rows[j-1]['issue'])+1 for j in js])[:,None], (len(js),count))
    values = []
    for e in ex.GRAMMAR:
        a, op = atoms[e['left']], e['op']
        if op == 'ATOM': v = a
        elif op == 'DOUBLE': v = 2*a
        else:
            b = atoms[e['right']]
            # Reduce before multiplication to prevent large issue products.
            if op == 'ADD': v = a+b
            elif op == 'SUB': v = a-b
            else: v = (a % maximum)*(b % maximum)
        values.append(v % maximum)
    residuals = (balls[js][None,:,:] - np.stack(values)) % maximum
    active = js[None,:] >= (n-np.asarray([e['window'] for e in ex.GRAMMAR]))[:,None]
    counts = ((residuals[:,:,:,None] == np.arange(maximum)[None,None,None,:])
              & active[:,:,None,None]).sum(axis=1)
    return counts.argmax(axis=-1).tolist()  # deterministic smallest-residual tie


def fit(rows, game, backend='numpy', workers=1):
    validate(rows, game)
    if len(rows)<40 or type(workers) is not int or workers not in (1,2):
        raise ValueError('fit requires 40 draws, 1..2 workers')
    fm, fp, bm, bp = SPECS[game]
    tasks = [(rows,'front',fm,fp,backend), (rows,'back',bm,bp,backend)]
    if workers == 2:
        with ProcessPoolExecutor(max_workers=2) as pool:
            front, back = list(pool.map(_fit_area,tasks))
    else:
        front, back = map(_fit_area,tasks)
    return [dict(expr=dict(e), offsets=dict(front=f,back=b)) for e,f,b in zip(ex.GRAMMAR,front,back)]


def predict_one(history, game, fitted):
    n = len(history)
    fm, fp, bm, bp = SPECS[game]
    expr = fitted['expr']
    result = {}
    for area, maximum, count in (('front',fm,fp),('back',bm,bp)):
        raw = [1+(ex.evaluate_expr(expr,history,n,area,p,maximum)+fitted['offsets'][area][p])%maximum for p in range(count)]
        ordered = ex.complete_balls(raw,maximum,count,game=game,asof=history[-1]['issue'],formula_id=expr['id'],area=area)
        result[area] = sorted(ordered)
        if area == 'front': result['d2_pair'] = sorted(ordered[:2])
    return result


def select(development, game, cfg, backend='numpy'):
    validate(development,game)
    if len(development) < cfg.train+cfg.validation:
        raise ValueError('training and validation must precede the target')
    cut = len(development)-cfg.validation
    fitted = fit(development[:cut],game,backend,cfg.workers)
    fm, fp, bm, bp = SPECS[game]
    for item in fitted:
        predictions = [predict_one(development[:j],game,item) for j in range(cut,len(development))]
        scores = [ex.hit_counts(p,r) for p,r in zip(predictions,development[cut:])]
        coverage = sum(s['front_hits']/fp+s['back_hits']/bp for s in scores)/len(scores)-fp/fm-bp/bm
        nodes = 1 if item['expr']['op']=='ATOM' else (2 if item['expr']['op']=='DOUBLE' else 3)
        complexity = nodes + math.log2(item['expr']['window']) + 1
        item.update(coverage=coverage,complexity=complexity,
                    penalized_score=coverage-cfg.penalty*complexity,
                    behavior=ex.digest(predictions),weight=1.0)
    fitted.sort(key=lambda x:(-x['penalized_score'],x['expr']['id']))
    selected, seen, families = [],set(),Counter()
    for item in fitted:
        family = item['expr']['family']
        if item['behavior'] in seen or families[family]>=2: continue
        selected.append(item)
        seen.add(item['behavior']); families[family]+=1
        if len(selected)==8: break
    if not selected: raise ValueError('empty model')
    model = dict(game=game,selected=selected,config=asdict(cfg),candidate_count=len(fitted),
                 fit_last_issue=development[cut-1]['issue'],asof_issue=development[-1]['issue'],
                 grammar_sha256=ex.digest(ex.GRAMMAR),formal_A=0,edge='NO_EDGE')
    model['sha256'] = ex.digest(model)
    return model


def predict(history, game, model):
    if (model['game']!=game or ex.digest({k:v for k,v in model.items() if k!='sha256'})!=model['sha256']
            or int(history[-1]['issue'])<int(model['asof_issue'])):
        raise ValueError('frozen model identity, hash or as-of invalid')
    fm, fp, bm, bp = SPECS[game]
    votes = {a:defaultdict(float) for a in ('front','back')}
    for fitted in model['selected']:
        p = predict_one(history,game,fitted)
        for area in votes:
            for ball in p[area]: votes[area][ball]+=fitted['weight']
    ranks = {a:sorted(range(1,m+1),key=lambda v:(-votes[a][v],derive_seed('AUTO_VOTE_TIE_V1',game,history[-1]['issue'],a,v)))
             for a,m in (('front',fm),('back',bm))}
    return dict(front=sorted(ranks['front'][:fp]),back=sorted(ranks['back'][:bp]),d2_pair=sorted(ranks['front'][:2]))


def _negative(game,issue,stream):
    fm,fp,bm,bp=SPECS[game]
    rng=random.Random(derive_seed('FORMULA_LAB_IID_NEGATIVE_V1',game,issue,stream))
    front=rng.sample(range(1,fm+1),fp)
    return dict(front=sorted(front),back=sorted(rng.sample(range(1,bm+1),bp)),d2_pair=sorted(front[:2]))


def _score(p, actual, game):
    score=ex.hit_counts(p,actual)
    score.update(front_full=int(score['front_hits']==SPECS[game][1]),back_full=int(score['back_hits']==SPECS[game][3]))
    return score


def evaluate(rows,game,cfg):
    validate(rows,game)
    if len(rows)!=cfg.train+cfg.validation+cfg.holdout:
        raise ValueError('exact predeclared cohort length required; no silently discarded periods')
    start=cfg.train+cfg.validation
    frozen=select(rows[:start],game,cfg)
    # Destroy time/label relationship only inside the already observed development set.
    perm=list(range(start)); random.Random(derive_seed('PERMUTE_TRAIN_V1',game)).shuffle(perm)
    scrambled=[dict(r,front=rows[k]['front'],back=rows[k]['back']) for r,k in zip(rows[:start],perm)]
    placebo=select(scrambled,game,cfg)
    result={mode:dict(model=frozen if mode=='frozen' else None,rows=[]) for mode in ('frozen','rolling')}
    for i in range(start,len(rows)):
        past,actual=rows[:i],rows[i]
        controls={'RANDOM_NULL':ex.research_null(game,actual['issue']),
                  'PERMUTED_TRAIN':predict(past,game,placebo)}
        for name in ('HOT60','EWMA30'):
            t=ticket(past,game,name)
            controls[name]=dict(front=t['front'],back=t['back'],d2_pair=t['dan2'])
        for stream in range(4): controls[f'IID_{stream}']=_negative(game,actual['issue'],stream)
        rolling=select(past,game,cfg)
        for mode,model in (('frozen',frozen),('rolling',rolling)):
            predictions=dict(FORMULA=predict(past,game,model),**controls)
            result[mode]['rows'].append(dict(issue=actual['issue'],asof_issue=past[-1]['issue'],
                model_sha256=model['sha256'],predictions=predictions,
                scores={name:_score(p,actual,game) for name,p in predictions.items()}))
    result.update(game=game,formal_A=0,edge='NO_EDGE',prospective_scored=0,
                  research_null='AUTO_DISCOVERY_RESEARCH_NULL_V1_NOT_FORMAL_V47',
                  config=asdict(cfg),negative_training_model=placebo)
    return result
