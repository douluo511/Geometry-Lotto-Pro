"""Frozen mechanism study: synthetic controls and OLD DEVELOPMENT PREFIX ONLY.

This module cannot read the old validation/test outcomes for scoring. Historical
date order is not proof of publication availability. It never enrolls a future
lottery issue, changes a producer, or grants an edge.
"""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import sys

from research.ssq_dlt_v45 import sources,workflow,models as original
from research.ssq_dlt_v45.store import Store,canonical,digest,parse
from research.ssq_dlt_v45.study_engine import _D2State,MODEL_IDS as OLD_IDS

LEGACY_PLAN_SHA='ce4545aa00941cda7fe2868d63d5900432779a50ec1d7a4f3f8edff8ff9c0720'
LIMITS={
 'SSQ':dict(rows=1293,last_issue='2021088',input_sha256='df90b133a5ae00cc8a70606800f44350b8c87630560c818c8408996f7692fa57'),
 'DLT':dict(rows=1809,last_issue='19027',input_sha256='8a9227232750078fc61ed5e6d13382c7e480413756f7d1857d94fbb9faca730b')}
BOUNDARY=dict(formal_A=0,decision='NO_EDGE',scope='DEVELOPMENT_ONLY_AND_SYNTHETIC_NOT_NEW_HOLDOUT',
    qualified_prospective_samples=0,official_next_legal_issue='BLOCKED',
    trusted_prerun_timestamp='BLOCKED_LOCAL_SHA_ONLY',repository_independence='FAIL',final_gate='FAIL')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def write_new(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(raw)


def source_manifest():
    base=Path(__file__).resolve().parent.parent
    return {p.relative_to(base).as_posix():sha(p.read_bytes()) for name in
       ('ssq_dlt_d2_next','ssq_dlt_v45','ssq_dlt_d2_v44') for p in sorted((base/name).rglob('*.py'))
       if not {'tests','__pycache__','evidence'}.intersection(p.relative_to(base/name).parts)}


def validate_development(game,document,*,expected_n=None,expected_last=None):
    if type(document) is not dict or set(document)!={'game','draws'} or document['game']!=game:
        raise ValueError('STRICT_DEVELOPMENT_DOCUMENT_REQUIRED')
    rows=sources.validate_history(game,document['draws'],datetime.now(timezone.utc))
    workflow.validate_issue_sequence(game,rows)
    if any(a['draw_date']>=b['draw_date'] for a,b in zip(rows,rows[1:])):
        raise ValueError('DUPLICATE_OR_NONINCREASING_DRAW_DATE')
    if expected_n is not None and len(rows)!=expected_n:raise ValueError('DEVELOPMENT_ROW_COUNT_MISMATCH')
    if expected_last is not None and rows[-1]['issue']!=expected_last:raise ValueError('DEVELOPMENT_CUTOFF_MISMATCH')
    return rows


def prepare(legacy_plan,history_config,output):
    from .models import registry
    from .simulation import SPEC
    from .inference import future_protocol
    output=Path(output)
    if not output.is_absolute():raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
    raw=Path(legacy_plan).read_bytes()
    if sha(raw)!=LEGACY_PLAN_SHA:raise ValueError('UNRECOGNIZED_EXPOSED_STUDY_PLAN')
    old=parse(raw);config=parse(Path(history_config).read_bytes());export={};games={}
    for game,limit in LIMITS.items():
        if old['games'][game]['stages']['development']['stop']!=limit['rows']:
            raise ValueError('IMMUTABLE_DEVELOPMENT_BOUNDARY_MISMATCH')
        spec=config['history'][game];source=Path(spec['path'])
        if not source.is_absolute() or spec['sha256']!=limit['input_sha256']:
            raise ValueError('ONLY_ORIGINAL_PINNED_ARCHIVE_ALLOWED')
        archive=source.read_bytes()
        if sha(archive)!=limit['input_sha256']:raise ValueError('ORIGINAL_INPUT_SHA_MISMATCH')
        doc=parse(archive)
        if doc.get('game')!=game:raise ValueError('INPUT_GAME_MISMATCH')
        # SHA/prefix extraction may read the old archive; the model executor
        # receives only this physically separate development file.
        prefix=validate_development(game,dict(game=game,draws=doc['draws'][:limit['rows']]),
                                    expected_n=limit['rows'],expected_last=limit['last_issue'])
        data=(canonical(dict(game=game,draws=prefix))+'\n').encode('utf-8');export[game]=data
        games[game]=dict(file=f'dev-inputs/{game}.json',sha256=sha(data),rows=len(prefix),
            warmup=240,evaluation_n=len(prefix)-240,first_target=prefix[240]['issue'],last_target=prefix[-1]['issue'],
            first_date=prefix[240]['draw_date'],last_date=prefix[-1]['draw_date'],
            expected_issues=[r['issue'] for r in prefix[240:]],original_input_sha256=limit['input_sha256'])
    plan=dict(schema='V45_D2_MECHANISM_PLAN_1',created_at=datetime.now(timezone.utc).isoformat(),
        legacy_plan_sha256=LEGACY_PLAN_SHA,legacy_partitions_allowed=['development'],
        legacy_validation_and_test='FORBIDDEN_RESCORING',old_model_ids=list(OLD_IDS),new_registry=registry(),
        synthetic=SPEC,future_protocol=future_protocol(),games=games,code_sha256=source_manifest(),
        synthetic_control_rules=dict(
            negative_scenarios=['FAIR','SCRAMBLED_PAIR_STRONG','RING_SCRAMBLED'],
            negative_family='2 new models x 2 games x 3 negative scenarios = 12 analytic fair-null exact-binomial p values, Holm alpha=.05',
            negative_falsification='Any adjusted p<=.05 falsifies that specified negative-control check; nonrejection is NOT_FALSIFIED, not proof of correctness.',
            positive_scenarios=['MARGINAL_STRONG','PAIR_STRONG','RING_PERSISTENT'],
            positive_point_diagnostic='PASS_POINT_DIAGNOSTIC if observed D2 delta versus NULL>0; CBPAIR additionally requires mean Brier<uniform. Otherwise FAIL_POINT_DIAGNOSTIC. This is a fixed descriptive mechanism check, not statistical proof.',
            weak_and_reversal='Stress results retained regardless of success; never retune from them.',
            reference_pair='Generator knowledge is not supplied to forecasts; one specified ring edge is not the total number of optimal ring edges.'),
        fixed_primary_model=original.PRIMARY_MODEL,random_null_model=original.NULL_MODEL,
        random_null_seed=original.DEFAULT_SEED,d2_per_model_per_issue=1,d2_size=2,
        hyperparameter_search=False,post_result_model_changes_forbidden=True,
        selection='NO_SELECTION_FROM_DEVELOPMENT_RESULTS',
        falsification=[
          'CB joint-only D2 is identical to the top-two weight rule; reject it as a selection improvement.',
          'A candidate that cannot recover a persistent strong synthetic bias has failed its stated mechanism control.',
          'A synthetic pass without independent prospective superiority is not a lottery hit-rate improvement.',
          'No candidate may claim improvement from an exposed historical development/validation/test partition.'],
        **BOUNDARY)
    output.mkdir(parents=True,exist_ok=False)
    for game,data in export.items():write_new(output/games[game]['file'],data)
    raw=(canonical(plan)+'\n').encode('utf-8');write_new(output/'plan.json',raw)
    write_new(output/'plan.sha256',(sha(raw)+'\n').encode())
    Store(output/'research.sqlite3').append('mechanism_plan',sha(raw),plan)
    return dict(status='PREPARED_DEVELOPMENT_ONLY',plan_sha256=sha(raw),games=games,**BOUNDARY)


def load_plan(output):
    from .models import registry
    from .simulation import SPEC
    output=Path(output);raw=(output/'plan.json').read_bytes()
    if sha(raw)!=(output/'plan.sha256').read_text('ascii').strip():raise ValueError('PLAN_SHA_MISMATCH')
    plan=parse(raw)
    if plan['code_sha256']!=source_manifest():raise ValueError('CODE_CHANGED_AFTER_REGISTRATION')
    if plan['new_registry']!=registry() or plan['synthetic']!=SPEC:raise ValueError('REGISTERED_PARAMETERS_CHANGED')
    if plan['legacy_plan_sha256']!=LEGACY_PLAN_SHA or plan['legacy_partitions_allowed']!=['development']:
        raise ValueError('FORBIDDEN_DATA_PARTITION')
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect((output/'research.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT payload,sha256 FROM events WHERE kind='mechanism_plan' AND key=?",(sha(raw),)).fetchone()
        if row is None or Store.checked(row)!=plan:raise ValueError('PLAN_NOT_IN_IMMUTABLE_REGISTRY')
    games={}
    for game,limit in LIMITS.items():
        spec=plan['games'][game]
        if spec['file']!=f'dev-inputs/{game}.json' or spec['rows']!=limit['rows']:
            raise ValueError('DEVELOPMENT_INPUT_LOCATION_OR_BOUNDARY_CHANGED')
        data=(output/spec['file']).read_bytes()
        if sha(data)!=spec['sha256']:raise ValueError('DEVELOPMENT_INPUT_SHA_MISMATCH')
        rows=validate_development(game,parse(data),expected_n=limit['rows'],expected_last=limit['last_issue'])
        if [r['issue'] for r in rows[240:]]!=spec['expected_issues']:raise ValueError('MISSING_OR_ADDED_DEVELOPMENT_PERIOD')
        games[game]=rows
    return plan,games,sha(raw)


def development(plan,games,store,progress=None):
    from .models import MODEL_IDS,predict_candidates
    from .inference import common_metrics,descriptive_family
    from .simulation import full_hit,pair_brier
    periods=[];summaries={};checks=[]
    for game,rows in games.items():
        state=_D2State(game,len(rows));hits={m:[] for m in (*OLD_IDS,*MODEL_IDS)};losses=[];changed={m:0 for m in MODEL_IDS}
        n,k,_,_=original.RULES[game]
        for index,row in enumerate(rows):
            if index>=240:
                if rows[index-1]['draw_date']>=row['draw_date']:raise ValueError('TRAIN_DATE_NOT_BEFORE_TARGET')
                predictions=state.predict(row['issue'],original.DEFAULT_SEED)
                new=predict_candidates(game,rows[:index])
                predictions.update({m:new[m]['d2'] for m in MODEL_IDS})
                for pair in predictions.values():original.validate_numbers(pair,2,n)
                forecast=dict(game=game,issue=row['issue'],training_size=index,training_end_issue=rows[index-1]['issue'],
                    training_end_date=rows[index-1]['draw_date'],target_date=row['draw_date'],predictions=predictions,
                    target_label='HISTORICAL_DEVELOPMENT_ONLY',**BOUNDARY)
                store.append('development_forecast',game+':'+row['issue'],forecast)
                scored={m:full_hit(pair,row['front']) for m,pair in predictions.items()}
                record=dict(forecast,draw_front=row['front'],hits=scored,
                    cbpair_brier=pair_brier(new[MODEL_IDS[0]]['pair_probabilities'],row['front'],n,k))
                store.append('development_outcome',game+':'+row['issue'],record);periods.append(record)
                for m,h in scored.items():hits[m].append(h)
                for m in MODEL_IDS:changed[m]+=int(predictions[m]!=predictions[original.PRIMARY_MODEL])
                losses.append(record['cbpair_brier'])
            state.append(row)
        for m,values in hits.items():
            metric=common_metrics(game,values,hits[original.NULL_MODEL])
            summaries[game+'|'+m]=dict(metric,game=game,model=m,comparison_scope='EXPOSED_OLD_DEVELOPMENT_ONLY')
        p0=k*(k-1)/(n*(n-1))
        checks.append(dict(game=game,n=len(losses),changed_from_original_primary=changed,
            mean_cbpair_brier=sum(losses)/len(losses),uniform_pair_brier=p0*(1-p0),
            mean_brier_delta=sum(losses)/len(losses)-p0*(1-p0),observation_unit='DRAW_NOT_PAIR',
            calibration_scope='SECONDARY_DIAGNOSTIC_NOT_D2_SUPERIORITY'))
        if progress:progress(dict(stage='development',game=game,n=len(losses),done=True))
    nonnull={k:v for k,v in summaries.items() if not k.endswith('|'+original.NULL_MODEL)}
    adjustment=descriptive_family(nonnull)
    return dict(metrics=summaries,multiplicity=adjustment,diagnostics=checks,periods=periods,**BOUNDARY)


def execute(output,progress=None):
    from .simulation import run_controls
    from .inference import simulate_protocol
    output=Path(output);plan,games,identity=load_plan(output);store=Store(output/'research.sqlite3')
    old=store.read('mechanism_result',identity)
    if old:
        verify(output)
        return dict(old,reused_execution=True)
    try:
        claimed=store.append('mechanism_execution_claim',identity,dict(plan_sha256=identity,at=datetime.now(timezone.utc).isoformat()))
    except ValueError as exc:
        if str(exc)=='IMMUTABLE_CONFLICT':raise ValueError('UNKNOWN_EXECUTION_REQUIRES_RECONCILIATION') from None
        raise
    if not claimed:raise ValueError('UNKNOWN_EXECUTION_REQUIRES_RECONCILIATION')
    try:
        controls=run_controls(progress)
        power=simulate_protocol()
        dev=development(plan,games,store,progress)
        # Confirm sources/inputs/parameters again before completing any result.
        load_plan(output)
        outputs={'synthetic.json':controls,'power-simulation.json':power,'development.json':dev}
        hashes={}
        for name,value in outputs.items():
            data=(canonical(value)+'\n').encode('utf-8');write_new(output/name,data);hashes[name]=sha(data)
        buffer=io.StringIO(newline='');writer=csv.writer(buffer)
        writer.writerow(['game','issue','date','training_size','training_end_issue','training_end_date','model','d2_a','d2_b','d2_full_hit','null_d2_full_hit','draw_front','scope'])
        for row in dev['periods']:
            for model,pair in row['predictions'].items():
                writer.writerow([row['game'],row['issue'],row['target_date'],row['training_size'],row['training_end_issue'],row['training_end_date'],model,*pair,row['hits'][model],row['hits'][original.NULL_MODEL],' '.join(map(str,row['draw_front'])),'EXPOSED_OLD_DEVELOPMENT_ONLY'])
        data=buffer.getvalue().encode('utf-8');write_new(output/'development-periods.csv',data);hashes['development-periods.csv']=sha(data)
        result=dict(status='COMPLETED_RESEARCH_ONLY',plan_sha256=identity,files=hashes,
                    development_n={g:s['evaluation_n'] for g,s in plan['games'].items()},
                    synthetic_periods=len(controls['periods']),finished_at=datetime.now(timezone.utc).isoformat(),
                    conclusion='NO_PROVEN_D2_IMPROVEMENT',selected_candidate=None,**BOUNDARY)
        store.append('mechanism_result',identity,result);write_new(output/'execution-receipt.json',(canonical(result)+'\n').encode())
        return result
    except BaseException as exc:
        store.append('mechanism_failed',identity,dict(plan_sha256=identity,error=type(exc).__name__,reason=str(exc),
                     observed_at=datetime.now(timezone.utc).isoformat(),**BOUNDARY))
        raise


def verify(output):
    output=Path(output);plan,games,identity=load_plan(output)
    # Read-only check: no Store initialization or SQLite metadata writes.
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect((output/'research.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLITE_INTEGRITY_FAILED')
        checked=[]
        for kind,key,payload,value_sha in db.execute('SELECT kind,key,payload,sha256 FROM events'):
            value=Store.checked((payload,value_sha));checked.append((kind,key,value))
        results=[value for kind,key,value in checked if kind=='mechanism_result' and key==identity]
        if len(results)!=1:raise ValueError('COMPLETE_RESEARCH_RESULT_REQUIRED')
        result=results[0]
    for name,expected in result['files'].items():
        if sha((output/name).read_bytes())!=expected:raise ValueError('RESULT_SHA_MISMATCH')
    forecasts={key:value for kind,key,value in checked if kind=='development_forecast'}
    outcomes={key:value for kind,key,value in checked if kind=='development_outcome'}
    expected={g+':'+issue for g,spec in plan['games'].items() for issue in spec['expected_issues']}
    if set(forecasts)!=expected or set(outcomes)!=expected:raise ValueError('MISSING_OR_DUPLICATE_PERIOD')
    for key,forecast in forecasts.items():
        outcome=outcomes[key]
        if forecast['predictions']!=outcome['predictions']:raise ValueError('M05_POSTHOC_PREDICTION_REPLACEMENT')
        if forecast['training_end_date']>=forecast['target_date']:raise ValueError('TEMPORAL_LEAKAGE')
        for model,pair in forecast['predictions'].items():
            if outcome['hits'][model]!=int(set(pair)<=set(outcome['draw_front'])):raise ValueError('INCORRECT_D2_SCORING')
    return dict(BOUNDARY,status='PASS',scope='LOCAL_PLAN_SOURCE_RESULTS_AND_COMPLETE_DEVELOPMENT_LEDGER_NOT_TSA',
                forecast_periods=len(forecasts),model_periods=len(forecasts)*8)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=('prepare','execute','verify'))
    ap.add_argument('--output',required=True);ap.add_argument('--legacy-plan');ap.add_argument('--history-config');args=ap.parse_args(argv)
    try:
        if args.action=='prepare':result=prepare(args.legacy_plan,args.history_config,args.output)
        elif args.action=='execute':result=execute(args.output,lambda v:print(canonical(v),flush=True))
        else:result=verify(args.output)
        print(canonical(result));return 0
    except Exception as exc:
        print(canonical(dict(status='FAIL',error=type(exc).__name__,reason=str(exc),**BOUNDARY)));return 2

if __name__=='__main__':raise SystemExit(main())
