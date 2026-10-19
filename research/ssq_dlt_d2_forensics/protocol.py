"""Frozen follow-up diagnostics. No lottery archives, model tuning or promotion."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
from datetime import datetime, timezone
import hashlib
import html
from itertools import combinations
import json
import math
from pathlib import Path
import sqlite3
import platform
import sys

from research.ssq_dlt_v45 import models as original
from research.ssq_dlt_v45 import study_stats as stats
from research.ssq_dlt_v45.store import Store, canonical, digest, parse
from research.ssq_dlt_d2_next import models as frozen
from research.ssq_dlt_d2_next.inference import common_metrics
from research.ssq_dlt_d2_next.simulation import full_hit, pair_brier
from . import calibration, generators

NEGATIVE = ('MT_DIRECT', 'SHA256_DIRECT', 'SPLIT_SCRAMBLED_PAIR', 'LEGACY_SHARED_SCRAMBLE')
POSITIVE = ('MARGINAL_STRONG', 'PAIR_STRONG', 'RING_PERSISTENT')
GAMES = ('SSQ', 'DLT')
MODELS = (*frozen.MODEL_IDS, original.NULL_MODEL)
SPEC = dict(schema='D2_FORENSICS_PROTOCOL_1', root_seed=2026101931,
    warmup=240, evaluation_draws=240, negative_replications=24, positive_replications=8,
    negative_scenarios=list(NEGATIVE), positive_scenarios=list(POSITIVE),
    models=list(MODELS), model_registry=frozen.registry(), null_seed=original.DEFAULT_SEED,
    null_domain='FORENSICS_V1:{scenario}:{replication}:{index}',
    negative_family_size=24, negative_test='min(1,2*min(inclusive_lower,inclusive_upper))',
    negative_adjustment='HOLM_ALL_24_TWO_SIDED', family_alpha=.05,
    negative_margin_tolerance=.01, negative_margin_method='SIMULTANEOUS_CP_1_MINUS_0.05_DIV_24_CONSTANT_BINOMIAL_LAW_ONLY',
    fixed_total_evaluations=57600, negative_evaluations=46080, positive_evaluations=11520,
    snapshot_indices=[0,60,120,180,239], moment_fit_maxiter=200, moment_fit_tol=1e-9,
    identity_abs_tolerance=1e-12,
    shrink_alpha=.5, shrink_d2_policy='COPY_FROZEN_D2_NO_RERANKING_OR_NEW_CANDIDATE',
    future_perturbation_indices=[0,120,239],
    planning_alternative_absolute_delta=.01, planning_target_power=.8,
    stopping_rule='ALL_REGISTERED_STREAMS_FIXED_N_NO_INTERIM_SELECTION_OR_REPLACEMENT',
    old_failure_policy='RETAIN_ORIGINAL_FALSIFIED_AND_CAUSE_UNRESOLVED_REGARDLESS_OF_NEW_RESULTS',
    old_archives='NOT_READ_OR_RESCORED', new_lottery_holdout=False,
    formal_A=0, decision='NO_EDGE')
ROOT = Path(__file__).resolve().parents[2]
PRIOR_NEGATIVE_KEY = 'SCRAMBLED_PAIR_STRONG|DLT|R46-REPLICATED-PAIR'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(canonical(value) + '\n')


def source_manifest():
    result = {}
    for name in ('ssq_dlt_d2_forensics', 'ssq_dlt_d2_next', 'ssq_dlt_v45'):
        for path in sorted((ROOT / 'research' / name).rglob('*.py')):
            result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def expected_streams():
    return [(scenario, game, rep)
            for scenario in NEGATIVE + POSITIVE for game in GAMES
            for rep in range(SPEC['negative_replications'] if scenario in NEGATIVE else SPEC['positive_replications'])]


def stream_key(scenario, game, rep):
    return f'{scenario}|{game}|{rep:02}'


def readonly_events(directory):
    path = Path(directory) / 'research.sqlite3'
    # The writer closes every transaction. Never instantiate Store on cached verification.
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return [(rowid, kind, key, Store.checked((payload, checksum)))
                for rowid, kind, key, payload, checksum in conn.execute(
                    'SELECT rowid,kind,key,payload,sha256 FROM events ORDER BY rowid')]
    finally:
        conn.close()


def two_sided_binomial(hits, n, p0):
    upper = stats.binomial_upper_tail(hits, n, p0)
    lower = stats.binomial_upper_tail(n-hits, n, 1-p0)
    return min(1.0, 2*min(upper, lower))


def exact_negative_power(game):
    n = SPEC['negative_replications'] * SPEC['evaluation_draws']
    upper, count, _, _ = original.RULES[game]
    p0 = count*(count-1)/(upper*(upper-1))
    alpha_tail = SPEC['family_alpha']/SPEC['negative_family_size']/2
    hi = next(h for h in range(n+1) if stats.binomial_upper_tail(h,n,p0) <= alpha_tail)
    lo = -1
    while lo+1 <= n and stats.binomial_upper_tail(n-(lo+1),n,1-p0) <= alpha_tail:
        lo += 1
    p1 = p0 + SPEC['planning_alternative_absolute_delta']
    power = stats.binomial_upper_tail(hi,n,p1)
    if lo >= 0:
        power += stats.binomial_upper_tail(n-lo,n,1-p1)
    return dict(n=n,p0=p0,p1=p1,critical_low=lo,critical_high=hi,
        bonferroni_two_sided_power=power,target_power=SPEC['planning_target_power'],
        scope='FIXED_IID_CONDITIONAL_UNIFORM_HIT_LAW_ONLY_NOT_MODEL_SKILL')


def prepare(directory, prior_decision):
    directory, prior_decision = Path(directory).resolve(), Path(prior_decision).resolve()
    prior = parse(prior_decision.read_bytes())
    failure = prior['negative_control_failures'][PRIOR_NEGATIVE_KEY]
    if prior.get('status') != 'DO_NOT_PROMOTE' or not math.isclose(failure['holm_p'],.03414134606736723,rel_tol=1e-12):
        raise ValueError('PRIOR_FAILURE_MUST_REMAIN_ANCHOR')
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(created_at=datetime.now(timezone.utc).isoformat(), spec=copy.deepcopy(SPEC),
        source_sha256=source_manifest(),python_runtime=sys.version,python_implementation=platform.python_implementation(),
        prior_decision_path=str(prior_decision), prior_decision_sha256=sha(prior_decision),
        prior_failure=copy.deepcopy(failure), stream_ids=[stream_key(*row) for row in expected_streams()],
        planned_negative_power={game: exact_negative_power(game) for game in GAMES},
        timestamp_status='LOCAL_ONLY_NOT_EXTERNAL_TSA', formal_A=0, decision='NO_EDGE')
    write_new(directory/'plan.json',plan)
    (directory/'plan.sha256').write_text(sha(directory/'plan.json')+'\n',encoding='ascii')
    Store(directory/'research.sqlite3').append('forensics_plan','v1',plan)
    return dict(status='PREPARED_LOCAL_ONLY',plan_sha256=sha(directory/'plan.json'),streams=len(plan['stream_ids']),planned_evaluations=SPEC['fixed_total_evaluations'])


def load_plan(directory):
    directory = Path(directory)
    plan = parse((directory/'plan.json').read_bytes())
    if sha(directory/'plan.json') != (directory/'plan.sha256').read_text(encoding='ascii').strip():
        raise ValueError('PLAN_SHA_MISMATCH')
    if plan['spec'] != SPEC or plan['source_sha256'] != source_manifest():
        raise ValueError('SOURCE_OR_PROTOCOL_DRIFT')
    if plan['python_runtime']!=sys.version or plan['python_implementation']!=platform.python_implementation():
        raise ValueError('RUNTIME_DRIFT')
    if sha(plan['prior_decision_path']) != plan['prior_decision_sha256']:
        raise ValueError('PRIOR_FAILURE_CHANGED')
    rows = readonly_events(directory)
    plans = [payload for _,kind,key,payload in rows if kind=='forensics_plan' and key=='v1']
    if plans != [plan] or plan['stream_ids'] != [stream_key(*row) for row in expected_streams()]:
        raise ValueError('PLAN_LEDGER_OR_STREAM_RECTANGLE_MISMATCH')
    return plan


def predict_at(game, rows, index):
    if type(index) is not int or index < SPEC['warmup'] or index >= len(rows):
        raise ValueError('LEGAL_PREFIX_INDEX_REQUIRED')
    prefix = rows[:index]
    original.validate_history(game, rows[index]['issue'], prefix)
    if any(a['draw_date'] >= b['draw_date'] for a,b in zip(prefix,prefix[1:])) or prefix[-1]['draw_date'] >= rows[index]['draw_date']:
        raise ValueError('F01_NONINCREASING_OR_TARGET_DATE_IN_PREFIX')
    return frozen.predict_candidates(game,prefix)


def components(game, prefix):
    upper,count,_,_ = original.RULES[game]
    base=prefix[-240:]; marg=Counter(x for row in base for x in row['front'])
    target=[(marg[i]+200*count/upper)/440 for i in range(1,upper+1)]
    prior=frozen.conditional_pair_probabilities([p/(1-p) for p in target],count)
    pairs=Counter(pair for row in prefix[-60:] for pair in combinations(row['front'],2))
    empirical={pair:pairs[pair]/60 for pair in prior}
    return empirical,prior,target


def execute(directory):
    directory=Path(directory).resolve();plan=load_plan(directory)
    if (directory/'result.json').exists():
        proof=verify(directory)
        return dict(status='REUSED_VERIFIED_RESULT',reused=True,verification=proof)
    events=readonly_events(directory)
    if any(kind=='forensics_claim' for _,kind,_,_ in events):
        raise ValueError('UNKNOWN_PRIOR_EXECUTION_CLAIM_NO_REPLACEMENT_RUN')
    store=Store(directory/'research.sqlite3')
    store.append('forensics_claim','v1',dict(at=datetime.now(timezone.utc).isoformat(),plan_sha256=sha(directory/'plan.json')))
    period_file=directory/'periods.csv'
    summaries=[];snapshot_rows=[];structural_fits=[];invariance_count=0;quarter_checks=0
    cells=defaultdict(list)
    with period_file.open('x',encoding='utf-8',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['scenario','game','replication','index','draw_front','cb_d2','replicated_d2','null_d2','cb_hit','replicated_hit','null_hit','cb_true_hit_probability','replicated_true_hit_probability','null_true_hit_probability','cb_oracle_regret','replicated_oracle_regret','cb_brier','shrunk_brier','cb_mse','shrunk_mse'])
        writer.writeheader()
        for scenario,game,replication in expected_streams():
            rows,meta=generators.synthetic_history(game,scenario,replication,
                warmup=SPEC['warmup'],evaluation_draws=SPEC['evaluation_draws'],root_seed=SPEC['root_seed'])
            upper,count,_,_=original.RULES[game];p0=count*(count-1)/(upper*(upper-1))
            truth=calibration.true_pair_probabilities(meta['law'],upper,count,
                favoured_pair=meta.get('favoured_pair',(1,2)),ring=meta.get('ring'),
                marginal_weight=meta.get('marginal_weight',3.),odds_ratio=meta.get('odds_ratio',8.),rho=meta.get('rho',.25))
            if scenario in POSITIVE:
                true_marginals=[math.fsum(prob for pair,prob in truth.items() if i in pair)/(count-1) for i in range(1,upper+1)]
                structural=calibration.fit_moment_matched_cb(true_marginals,count,maxiter=SPEC['moment_fit_maxiter'],tol=SPEC['moment_fit_tol'])
                structural_fits.append(dict(scenario=scenario,game=game,replication=replication,
                    converged=structural['converged'],iterations=structural['iterations'],max_abs_error=structural['max_abs_error'],
                    oracle_marginal_fitted_cb_mse=math.fsum((structural['pair_probabilities'][pair]-truth[pair])**2 for pair in truth)/len(truth),
                    scope='KNOWN_GENERATOR_POPULATION_STRUCTURE_NOT_DEPLOYABLE_FORECAST'))
            meta['complete_generated_rows_sha256']=digest(rows)
            key=stream_key(scenario,game,replication);forecasts=[];outcomes=[]
            prepared=[]
            for index in range(SPEC['warmup'],len(rows)):
                evaluation=index-SPEC['warmup'];target=rows[index];pred=predict_at(game,rows,index)
                null=sorted(original._sample(SPEC['null_seed'],game,f'FORENSICS_V1:{scenario}:{replication}:{index}',original.NULL_MODEL,'dan',2,upper))
                predictions={model:pred[model]['d2'] for model in frozen.MODEL_IDS};predictions[original.NULL_MODEL]=null
                q=pred[frozen.MODEL_IDS[0]]['pair_probabilities']
                if evaluation in SPEC['future_perturbation_indices']:
                    changed=copy.deepcopy(rows)
                    for row in changed[index:]:row['front']=list(range(1,count+1))
                    if predict_at(game,changed,index) != pred:raise ValueError('F01_FUTURE_PERTURBATION_CHANGED_PREDICTION')
                    invariance_count+=1
                forecast=dict(index=index,training_end=index-1,predictions=predictions,
                    probability_sha256=digest([[*pair,value] for pair,value in sorted(q.items())]))
                forecasts.append(forecast)
                prepared.append((index,pred,null,predictions,q))
            # Persist all predictable pairs before the scoring loop. Synthetic
            # rows already exist; this is not an external pre-draw timestamp.
            store.append('forensics_forecasts',key,dict(metadata=meta,forecasts=forecasts))
            for index,pred,null,predictions,q in prepared:
                evaluation=index-SPEC['warmup'];target=rows[index]
                hits={model:full_hit(pair,target['front']) for model,pair in predictions.items()}
                shrunk=calibration.uniform_shrink(q,upper,count,alpha=SPEC['shrink_alpha'])
                mse=math.fsum((q[pair]-probability)**2 for pair,probability in truth.items())/len(truth)
                shrunk_mse=math.fsum((shrunk[pair]-probability)**2 for pair,probability in truth.items())/len(truth)
                if scenario in NEGATIVE:
                    if not math.isclose(shrunk_mse,.25*mse,rel_tol=1e-10,abs_tol=2e-16):raise ValueError('FAIR_SHRINK_EXPECTED_LOSS_IDENTITY_FAILED')
                    quarter_checks+=1
                diagnostics=dict(cb_mse=mse,shrunk_mse=shrunk_mse,
                    cb_brier=pair_brier(q,target['front'],upper,count),
                    shrunk_brier=pair_brier(shrunk,target['front'],upper,count),
                    true_hit_probability={model:truth[tuple(pair)] for model,pair in predictions.items()},
                    oracle_regret={model:max(truth.values())-truth[tuple(pair)] for model,pair in predictions.items()})
                if scenario in POSITIVE:
                    empirical,prior,marginal_target=components(game,rows[:index])
                    if any(not math.isclose(q[pair],(60*empirical[pair]+200*prior[pair])/260,abs_tol=2e-14) for pair in q):raise ValueError('FROZEN_MIX_COMPONENT_MISMATCH')
                    decomp=calibration.brier_decomposition(empirical,prior,truth,target['front'])
                    if any(abs(decomp[field])>SPEC['identity_abs_tolerance'] for field in ('mix_mse_identity_residual','mix_oracle_identity_residual','mix_uniform_identity_residual')):
                        raise ValueError('CALIBRATION_IDENTITY_FAILED')
                    diagnostics['decomposition']=decomp
                    if evaluation in SPEC['snapshot_indices']:
                        fit=calibration.fit_moment_matched_cb(marginal_target,count,maxiter=SPEC['moment_fit_maxiter'],tol=SPEC['moment_fit_tol'])
                        fitted=fit['pair_probabilities']
                        fitted_mix={pair:(60*empirical[pair]+200*fitted[pair])/260 for pair in q}
                        snapshot_rows.append(dict(scenario=scenario,game=game,replication=replication,index=index,
                            converged=fit['converged'],iterations=fit['iterations'],max_abs_error=fit['max_abs_error'],
                            surrogate_marginal_error=pred[frozen.MODEL_IDS[0]]['diagnostics']['max_abs_conditional_vs_input_marginal'],
                            surrogate_prior_mse=decomp['prior_mse'],
                            fitted_prior_mse=math.fsum((fitted[pair]-truth[pair])**2 for pair in truth)/len(truth),
                            original_mix_mse=mse,fitted_mix_mse=math.fsum((fitted_mix[pair]-truth[pair])**2 for pair in truth)/len(truth),
                            scope='FIXED_SNAPSHOT_ABLATION_NOT_NEW_D2_CANDIDATE_NO_HIT_SELECTION'))
                outcome=dict(index=index,front=target['front'],hits=hits,diagnostics=diagnostics)
                outcomes.append(outcome);cells[scenario,game].append(outcome)
                writer.writerow(dict(scenario=scenario,game=game,replication=replication,index=index,
                    draw_front=' '.join(map(str,target['front'])),cb_d2=' '.join(map(str,predictions[frozen.MODEL_IDS[0]])),
                    replicated_d2=' '.join(map(str,predictions[frozen.MODEL_IDS[1]])),null_d2=' '.join(map(str,null)),
                    cb_hit=hits[frozen.MODEL_IDS[0]],replicated_hit=hits[frozen.MODEL_IDS[1]],null_hit=hits[original.NULL_MODEL],
                    cb_true_hit_probability=diagnostics['true_hit_probability'][frozen.MODEL_IDS[0]],
                    replicated_true_hit_probability=diagnostics['true_hit_probability'][frozen.MODEL_IDS[1]],null_true_hit_probability=diagnostics['true_hit_probability'][original.NULL_MODEL],
                    cb_oracle_regret=diagnostics['oracle_regret'][frozen.MODEL_IDS[0]],replicated_oracle_regret=diagnostics['oracle_regret'][frozen.MODEL_IDS[1]],
                    cb_brier=diagnostics['cb_brier'],shrunk_brier=diagnostics['shrunk_brier'],cb_mse=mse,shrunk_mse=shrunk_mse))
            store.append('forensics_outcomes',key,dict(outcomes=outcomes))
            print(canonical(dict(stage='stream',scenario=scenario,game=game,replication=replication,evaluations=len(outcomes))),flush=True)
    negative_tests={};negative_margins={}
    for (scenario,game),values in cells.items():
        model_summaries={}
        for model in MODELS:
            metrics=common_metrics(game,[row['hits'][model] for row in values],[row['hits'][original.NULL_MODEL] for row in values])
            metrics['scope']='SYNTHETIC_DIAGNOSTIC_NOT_LOTTERY_EVIDENCE';metrics['confirmation_gate']='NOT_A_LOTTERY_CONFIRMATION'
            metrics['mean_true_hit_probability']=math.fsum(row['diagnostics']['true_hit_probability'][model] for row in values)/len(values)
            metrics['mean_oracle_regret']=math.fsum(row['diagnostics']['oracle_regret'][model] for row in values)/len(values)
            model_summaries[model]=metrics
            if scenario in NEGATIVE:
                hypothesis=f'{scenario}|{game}|{model}'
                negative_tests[hypothesis]=two_sided_binomial(metrics['hits'],metrics['n'],metrics['fair_d2_p0'])
                bounds=stats._cp_bounds(metrics['hits'],metrics['n'],SPEC['family_alpha']/SPEC['negative_family_size']/2)
                covered=bounds[0]>=metrics['fair_d2_p0']-SPEC['negative_margin_tolerance'] and bounds[1]<=metrics['fair_d2_p0']+SPEC['negative_margin_tolerance']
                negative_margins[hypothesis]=dict(simultaneous_interval=bounds,delta_interval=[bound-metrics['fair_d2_p0'] for bound in bounds],
                    status='WITHIN_FIXED_1PP_MARGIN_UNDER_CONSTANT_BINOMIAL_LAW' if covered else 'INCONCLUSIVE_MARGIN',
                    scope='NOT_PROOF_OF_EXACT_FAIRNESS_OR_EXPLANATION_OF_PRIOR_FAILURE')
        aggregate={field:math.fsum(row['diagnostics'][field] for row in values)/len(values) for field in ('cb_mse','shrunk_mse','cb_brier','shrunk_brier')}
        if scenario in POSITIVE:
            aggregate['decomposition']={field:math.fsum(row['diagnostics']['decomposition'][field] for row in values)/len(values) for field in values[0]['diagnostics']['decomposition']}
        summaries.append(dict(scenario=scenario,game=game,n=len(values),models=model_summaries,calibration=aggregate))
    if len(negative_tests)!=24:raise ValueError('INCOMPLETE_24_HYPOTHESIS_FAMILY')
    adjusted=stats.holm_adjust(negative_tests)
    rejected=[key for key,value in adjusted.items() if value<=SPEC['family_alpha']]
    result=dict(status='COMPLETED_SYNTHETIC_FORENSICS_NOT_LOTTERY_IMPROVEMENT',spec=SPEC,
        completed_at=datetime.now(timezone.utc).isoformat(),evaluations=sum(len(v) for v in cells.values()),
        summaries=summaries,negative_raw_two_sided_p=negative_tests,negative_holm24_p=adjusted,negative_margin_intervals=negative_margins,
        negative_rejections=rejected,original_failure_still_retained=True,original_failure_cause='UNRESOLVED',
        future_perturbation_checks=invariance_count,fair_quarter_mse_identity_checks=quarter_checks,
        moment_fit_snapshots=snapshot_rows,population_structural_fits=structural_fits,shrink_d2_changes=0,
        no_new_lottery_holdout=True,qualified_prospective_samples=0,formal_A=0,decision='NO_EDGE',selected_candidate=None)
    write_new(directory/'result.json',result)
    write_new(directory/'result-manifest.json',{'result.json':sha(directory/'result.json'),'periods.csv':sha(period_file)})
    store.append('forensics_result','v1',dict(manifest=parse((directory/'result-manifest.json').read_bytes()),evaluations=result['evaluations']))
    (directory/'report.html').write_text(render(result),encoding='utf-8')
    return dict(status=result['status'],evaluations=result['evaluations'],negative_rejections=rejected,original_failure_cause='UNRESOLVED',formal_A=0,decision='NO_EDGE')


def verify(directory):
    directory=Path(directory);load_plan(directory)
    manifest=parse((directory/'result-manifest.json').read_bytes())
    if set(manifest)!={'result.json','periods.csv'} or any(sha(directory/name)!=value for name,value in manifest.items()):raise ValueError('RESULT_SHA_MISMATCH')
    result=parse((directory/'result.json').read_bytes());events=readonly_events(directory)
    final=[value for _,kind,key,value in events if kind=='forensics_result' and key=='v1']
    if final != [dict(manifest=manifest,evaluations=SPEC['fixed_total_evaluations'])]:raise ValueError('RESULT_LEDGER_MISMATCH')
    forecasts={key:(rowid,value) for rowid,kind,key,value in events if kind=='forensics_forecasts'}
    outcomes={key:(rowid,value) for rowid,kind,key,value in events if kind=='forensics_outcomes'}
    expected={stream_key(*row) for row in expected_streams()}
    if set(forecasts)!=expected or set(outcomes)!=expected or sum(kind=='forensics_forecasts' for _,kind,_,_ in events)!=len(expected) or sum(kind=='forensics_outcomes' for _,kind,_,_ in events)!=len(expected):raise ValueError('STREAM_RECTANGLE_MISMATCH')
    n=0;all_outcomes=defaultdict(list);csv_expected={};sampled_replays=0
    for scenario,game,rep in expected_streams():
        key=stream_key(scenario,game,rep)
        f_id,f=forecasts[key];o_id,o=outcomes[key]
        if f_id>=o_id:raise ValueError('FORECAST_AFTER_OUTCOME')
        if len(f['forecasts'])!=240 or len(o['outcomes'])!=240:raise ValueError('MISSING_STREAM_PERIODS')
        generated,metadata=generators.synthetic_history(game,scenario,rep,warmup=SPEC['warmup'],evaluation_draws=SPEC['evaluation_draws'],root_seed=SPEC['root_seed'])
        metadata['complete_generated_rows_sha256']=digest(generated)
        if metadata!=f['metadata']:raise ValueError('GENERATOR_METADATA_OR_ROWS_SHA_MISMATCH')
        upper,count,_,_=original.RULES[game]
        for index,(fc,oc) in enumerate(zip(f['forecasts'],o['outcomes']),240):
            if fc['index']!=index or oc['index']!=index or fc['training_end']!=index-1 or set(fc['predictions'])!=set(MODELS) or set(oc['hits'])!=set(MODELS):raise ValueError('MODEL_PERIOD_RECTANGLE_MISMATCH')
            if any(full_hit(fc['predictions'][m],oc['front'])!=oc['hits'][m] for m in MODELS):raise ValueError('HIT_SCORE_MISMATCH')
            if oc['front']!=generated[index]['front']:raise ValueError('GENERATOR_OUTCOME_MISMATCH')
            for pair in fc['predictions'].values():original.validate_numbers(pair,2,upper)
            if index-240 in SPEC['future_perturbation_indices']:
                again=predict_at(game,generated,index)
                if any(again[m]['d2']!=fc['predictions'][m] for m in frozen.MODEL_IDS):raise ValueError('SAMPLED_FROZEN_MODEL_REPLAY_MISMATCH')
                q=again[frozen.MODEL_IDS[0]]['pair_probabilities']
                if digest([[*pair,value] for pair,value in sorted(q.items())])!=fc['probability_sha256']:raise ValueError('SAMPLED_PROBABILITY_REPLAY_MISMATCH')
                sampled_replays+=1
            decomp=oc['diagnostics'].get('decomposition')
            if decomp and any(abs(decomp[field])>SPEC['identity_abs_tolerance'] for field in ('mix_mse_identity_residual','mix_oracle_identity_residual','mix_uniform_identity_residual')):raise ValueError('STORED_CALIBRATION_IDENTITY_FAILED')
            all_outcomes[scenario,game].append(oc)
            csv_expected[scenario,game,rep,index]=(fc,oc)
            n+=1
    with (directory/'periods.csv').open(encoding='utf-8',newline='') as file:
        csv_count=0;seen=set()
        for row in csv.DictReader(file):
            key=(row['scenario'],row['game'],int(row['replication']),int(row['index']))
            if key in seen or key not in csv_expected:raise ValueError('CSV_DUPLICATE_OR_UNKNOWN_PERIOD')
            seen.add(key);fc,oc=csv_expected[key];diag=oc['diagnostics']
            if [int(x) for x in row['draw_front'].split()]!=oc['front']:raise ValueError('CSV_DRAW_MISMATCH')
            for prefix,model in zip(('cb','replicated','null'),MODELS):
                if [int(x) for x in row[prefix+'_d2'].split()]!=fc['predictions'][model] or int(row[prefix+'_hit'])!=oc['hits'][model]:raise ValueError('CSV_PREDICTION_OR_HIT_MISMATCH')
                if not math.isclose(float(row[prefix+'_true_hit_probability']),diag['true_hit_probability'][model],abs_tol=1e-14):raise ValueError('CSV_TRUE_PROBABILITY_MISMATCH')
            for prefix,model in zip(('cb','replicated'),frozen.MODEL_IDS):
                if not math.isclose(float(row[prefix+'_oracle_regret']),diag['oracle_regret'][model],abs_tol=1e-14):raise ValueError('CSV_REGRET_MISMATCH')
            for field in ('cb_brier','shrunk_brier','cb_mse','shrunk_mse'):
                if not math.isclose(float(row[field]),diag[field],abs_tol=1e-14):raise ValueError('CSV_CALIBRATION_MISMATCH')
            csv_count+=1
    if n!=SPEC['fixed_total_evaluations'] or csv_count!=n or result['evaluations']!=n or result['spec']!=SPEC:raise ValueError('EVALUATION_COUNT_MISMATCH')
    if (directory/'report.html').read_text(encoding='utf-8')!=render(result):raise ValueError('REPORT_RESULT_MISMATCH')
    rebuilt_tests={}
    expected_cells={(scenario,game) for scenario in NEGATIVE+POSITIVE for game in GAMES}
    if len(result['summaries'])!=len(expected_cells) or {(cell['scenario'],cell['game']) for cell in result['summaries']}!=expected_cells:raise ValueError('SUMMARY_CELL_RECTANGLE_MISMATCH')
    for cell in result['summaries']:
        values=all_outcomes[cell['scenario'],cell['game']]
        if len(values)!=cell['n'] or set(cell['models'])!=set(MODELS):raise ValueError('SUMMARY_RECTANGLE_MISMATCH')
        for model,metric in cell['models'].items():
            hits=[value['hits'][model] for value in values];nullhits=[value['hits'][original.NULL_MODEL] for value in values]
            recomputed=common_metrics(cell['game'],hits,nullhits)
            for field in ('n','hits','rate','paired_delta','paired_delta_ci','p_iut'):
                if metric[field]!=recomputed[field]:raise ValueError('SUMMARY_METRIC_MISMATCH')
            for field,source_field in [('mean_true_hit_probability','true_hit_probability'),('mean_oracle_regret','oracle_regret')]:
                expected_mean=math.fsum(value['diagnostics'][source_field][model] for value in values)/len(values)
                if not math.isclose(metric[field],expected_mean,abs_tol=1e-14):raise ValueError('SUMMARY_ORACLE_MISMATCH')
            if cell['scenario'] in NEGATIVE:
                hypothesis=f"{cell['scenario']}|{cell['game']}|{model}"
                rebuilt_tests[hypothesis]=two_sided_binomial(sum(hits),len(hits),recomputed['fair_d2_p0'])
                bounds=stats._cp_bounds(sum(hits),len(hits),SPEC['family_alpha']/SPEC['negative_family_size']/2)
                if bounds!=result['negative_margin_intervals'][hypothesis]['simultaneous_interval']:raise ValueError('NEGATIVE_MARGIN_INTERVAL_MISMATCH')
        for field in ('cb_mse','shrunk_mse','cb_brier','shrunk_brier'):
            if not math.isclose(cell['calibration'][field],math.fsum(v['diagnostics'][field] for v in values)/len(values),abs_tol=1e-14):raise ValueError('SUMMARY_CALIBRATION_MISMATCH')
        if cell['scenario'] in POSITIVE:
            for field,mean in cell['calibration']['decomposition'].items():
                if not math.isclose(mean,math.fsum(v['diagnostics']['decomposition'][field] for v in values)/len(values),abs_tol=1e-14):raise ValueError('SUMMARY_DECOMPOSITION_MISMATCH')
    adjusted=stats.holm_adjust(rebuilt_tests)
    if len(rebuilt_tests)!=24 or rebuilt_tests!=result['negative_raw_two_sided_p'] or adjusted!=result['negative_holm24_p'] or [key for key,value in adjusted.items() if value<=SPEC['family_alpha']]!=result['negative_rejections']:raise ValueError('NEGATIVE_FAMILY_MISMATCH')
    expected_snapshots={(s,g,r,240+i) for s,g,r in expected_streams() if s in POSITIVE for i in SPEC['snapshot_indices']}
    if {(v['scenario'],v['game'],v['replication'],v['index']) for v in result['moment_fit_snapshots']}!=expected_snapshots or len(result['moment_fit_snapshots'])!=len(expected_snapshots):raise ValueError('SNAPSHOT_RECTANGLE_MISMATCH')
    expected_structures={(s,g,r) for s,g,r in expected_streams() if s in POSITIVE}
    if len(result['population_structural_fits'])!=len(expected_structures) or {(v['scenario'],v['game'],v['replication']) for v in result['population_structural_fits']}!=expected_structures:raise ValueError('STRUCTURAL_RECTANGLE_MISMATCH')
    if result['future_perturbation_checks']!=720 or result['fair_quarter_mse_identity_checks']!=46080:raise ValueError('INVARIANCE_COUNT_MISMATCH')
    if not result['original_failure_still_retained'] or result['original_failure_cause']!='UNRESOLVED' or result['selected_candidate'] is not None or result['formal_A']!=0 or result['decision']!='NO_EDGE' or result['qualified_prospective_samples']!=0 or result['shrink_d2_changes']!=0:raise ValueError('RESEARCH_PROMOTION_OR_FAILURE_ERASURE')
    return dict(status='PASS_STORED_INTEGRITY_AND_SAMPLED_REPLAY_NOT_SCIENTIFIC_SUCCESS',evaluations=n,streams=len(expected),sampled_model_probability_replays=sampled_replays,formal_A=0,decision='NO_EDGE')


def render(result):
    rows=[]
    for cell in result['summaries']:
        for model,metric in cell['models'].items():
            key=f"{cell['scenario']}|{cell['game']}|{model}"
            values=[cell['scenario'],cell['game'],model,f"{metric['hits']}/{metric['n']}",f"{metric['rate']:.4%}",f"{metric['paired_delta']*100:+.4f} pp",str(metric['paired_delta_ci']),str(result['negative_holm24_p'].get(key,'正控制／不作公平null檢驗')),f"{metric['mean_true_hit_probability']:.5%}",f"{metric['mean_oracle_regret']:.6f}"]
            rows.append('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in values)+'</tr>')
    return ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>D2機制與異常追查</title><style>body{font:16px system-ui;max-width:1350px;margin:30px auto;padding:0 18px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:7px}pre{white-space:pre-wrap;overflow-wrap:anywhere}strong{color:#9c2d24}</style>'
        '<h1>SSQ＋DLT：異常追查與機率分解</h1><p><strong>沒有新增真實彩票命中率提升證據；A=0、NO_EDGE。原負控制FAIL永久保留，原因仍未解。</strong></p>'
        '<p>新資料全部是合成控制：46080個負控制期＋11520個正控制期。固定四種生成路徑（含原共享RNG路徑的新seed）、兩個凍結候選與同期NULL。固定樣本，24項雙尾Holm；未換種子補考，未讀舊validation/test。</p>'
        '<p>機率收縮診斷直接攜帶原D2，沒有重新排序：即使Brier改善，也不算膽碼能力提升。真實joint probability與oracle regret僅因人工生成律已知才可計算，不是部署可得的資訊。</p>'
        '<p>合成配對差值CI仍附IID假設限制；正控制不與公平p0做優勢證明。無新holdout，無正式期號准入或可信TSA。本輪沒有出新號或改舊主單。</p>'
        '<p>本輪24項負控制拒絕：'+html.escape(str(result['negative_rejections']))+'。未拒絕僅表示本輪未偵測偏離；不證明原異常來自運氣。另報同時CP區間與固定±1pp界限，不能用來覆蓋原FAIL。</p>'
        '<p><a href="plan.json">事前本地方案</a> · <a href="result.json">完整結果／校準分解／固定快照</a> · <a href="periods.csv">全部逐期資料</a> · <a href="result-manifest.json">結果SHA</a></p>'
        '<table><tr><th>情境</th><th>彩種</th><th>模型</th><th>全中／期數</th><th>命中率</th><th>與NULL差值</th><th>配對95%CI（比例）</th><th>負控制Holm24 p</th><th>生成律下真成功率均值</th><th>Oracle regret</th></tr>'+''.join(rows)+'</table>'
        '<h2>機率誤差與固定快照（診斷，不是新候選）</h2><pre>'+html.escape(json.dumps([dict(scenario=x['scenario'],game=x['game'],calibration=x['calibration']) for x in result['summaries']],ensure_ascii=False,indent=2))+'</pre></html>')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','execute','verify'))
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--prior-decision',type=Path)
    args=parser.parse_args(argv)
    if args.action=='prepare':
        if not args.prior_decision:parser.error('--prior-decision required')
        answer=prepare(args.output,args.prior_decision)
    else:answer=(execute if args.action=='execute' else verify)(args.output)
    print(canonical(answer),flush=True)
    return 0
