"""One-shot original-seed replay with immutable files and before/after hashes.

This audit does not open any SQLite database, historical lottery archive or
new seed. It must retain a significant original negative control even when
all reconstruction and scoring checks succeed.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,platform,sys
from .statistics import rescore_family,permutation_check

ROOT=Path(__file__).resolve().parents[2]
EXPECTED={
 'original_plan':'5da88c9690bd288a0a384fd64871079926d7e92cb41ee9c2ccdddde57354287e',
 'original_synthetic':'eb14efbbd3f645535d1e659e3b8143df04e7b8fcecba605f4d42ee41fd75b300',
 'original_decision':'4f2281a3452db40112feade81bb1f6ad7df247018de4dad6c4662d0f73153cb2',
 'science_plan':'704a2962d68d73624757943ea9f1d9308a08bad49239110b408f5edef6563922'}
TARGET='SCRAMBLED_PAIR_STRONG|DLT|R46-REPLICATED-PAIR'
BOUNDARY=dict(formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0,
    new_prediction_candidates=0,new_seeds=0,old_lottery_holdouts_read=False,
    original_sqlite_opened=False,official_next_legal_issue='BLOCKED',
    repository_independence='FAIL',final_gate='FAIL')

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def write_new(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        f.write(canonical(value)+'\n');f.flush();os.fsync(f.fileno())
def read(path):return json.loads(Path(path).read_bytes())
def own_sources():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(Path(__file__).parent.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and (p.suffix in ('.py','.md') or p.name=='.gitattributes')}
def code_reason(exc):
    import re
    text=str(exc)
    return text if re.fullmatch('[A-Z][A-Z0-9_]{1,140}',text) else type(exc).__name__

def snapshot(plan):
    result={}
    for name,spec in plan['inputs'].items():
        p=Path(spec['path']);result['input:'+name]=sha(p) if p.is_file() else None
    for path in plan['science_sources']:
        p=ROOT/path;result['science:'+path]=sha(p) if p.is_file() else None
    for path in plan['audit_sources']:
        p=ROOT/path;result['audit:'+path]=sha(p) if p.is_file() else None
    return result

def prepare(inputs,output):
    output=Path(output)
    if not output.is_absolute() or set(inputs)!=set(EXPECTED) or any(v is None for v in inputs.values()):raise ValueError('ABSOLUTE_OUTPUT_AND_FOUR_INPUTS_REQUIRED')
    pins={}
    for name,path in inputs.items():
        path=Path(path)
        if not path.is_absolute():raise ValueError('ABSOLUTE_INPUT_REQUIRED')
        path=path.resolve()
        if output.resolve().is_relative_to(path.parent) or path.is_relative_to(output.resolve()):raise ValueError('OUTPUT_MUST_BE_SEPARATE_FROM_ORIGINAL_INPUTS')
        if sha(path)!=EXPECTED[name]:raise ValueError('ORIGINAL_INPUT_SHA_MISMATCH')
        pins[name]=dict(path=str(path),sha256=EXPECTED[name])
    science=read(pins['science_plan']['path'])['source_sha256']
    if len(science)!=49:raise ValueError('ORIGINAL_49_SCIENCE_PINS_REQUIRED')
    for path,expected in science.items():
        p=(ROOT/path).resolve()
        if not p.is_relative_to(ROOT.resolve()) or sha(p)!=expected:raise ValueError('FROZEN_SCIENCE_CHANGED')
    original=read(pins['original_plan']['path'])
    from research.ssq_dlt_d2_next.models import registry
    from research.ssq_dlt_d2_next.simulation import SPEC
    if original['new_registry']!=registry() or original['synthetic']!=SPEC:raise ValueError('ORIGINAL_MODEL_OR_GENERATOR_CHANGED')
    plan=dict(schema='D2_ORIGINAL_NEGATIVE_REPLAY_1',created_at=now(),inputs=pins,
        science_sources=science,audit_sources=own_sources(),python=sys.version,implementation=platform.python_implementation(),
        target=TARGET,original_seed=2026101901,replications=12,warmup=240,evaluation_draws=240,
        original_family='12_ORIGINAL_ONE_SIDED_FAIR_NULL_TESTS_HOLM_0_05',
        hypotheses=[
          'Stored draw, prefix forecast and hit must match exact original-seed reconstruction.',
          'Independent Decimal tails and complete original Holm family must reproduce the significant failure.',
          'Uniform independent relabeling maps each fixed-size latent subset to a uniform subset.',
          'Passing replay is not an explanation of why this particular seed has 69 hits.'],
        outcome_policy='KEEP_ORIGINAL_FALSIFIED_CAUSE_UNRESOLVED_UNLESS_SPECIFIC_CAUSAL_DEFECT_IS_IDENTIFIED',
        timestamp='LOCAL_ONLY_NOT_TRUSTED_PRERUN_OR_NEW_CONFIRMATORY_REGISTRATION',**BOUNDARY)
    output.mkdir(parents=True,exist_ok=False)
    write_new(output/'plan.json',plan);write_new(output/'plan-sha.json',dict(sha256=digest(plan)))
    return dict(status='PREPARED_KNOWN_OUTCOME_FORENSIC_AUDIT',plan_sha256=digest(plan),**BOUNDARY)

def load_plan(output):
    output=Path(output);plan=read(output/'plan.json')
    if digest(plan)!=read(output/'plan-sha.json')['sha256']:raise ValueError('AUDIT_PLAN_SHA_MISMATCH')
    if plan['schema']!='D2_ORIGINAL_NEGATIVE_REPLAY_1' or plan['python']!=sys.version:raise ValueError('AUDIT_PLAN_OR_RUNTIME_CHANGED')
    if set(plan['inputs'])!=set(EXPECTED) or any(spec['sha256']!=EXPECTED[name] for name,spec in plan['inputs'].items()):raise ValueError('ORIGINAL_REGISTERED_INPUT_PINS_REQUIRED')
    if plan['target']!=TARGET or plan['original_seed']!=2026101901 or plan['replications']!=12 or plan['warmup']!=240 or plan['evaluation_draws']!=240:raise ValueError('ORIGINAL_AUDIT_SCOPE_CHANGED')
    if own_sources()!=plan['audit_sources']:raise ValueError('AUDIT_SOURCE_CHANGED')
    expected={'input:'+n:s['sha256'] for n,s in plan['inputs'].items()}
    expected.update({'science:'+p:s for p,s in plan['science_sources'].items()})
    expected.update({'audit:'+p:s for p,s in plan['audit_sources'].items()})
    if snapshot(plan)!=expected:raise ValueError('AUDIT_INPUT_OR_SCIENCE_CHANGED')
    if plan['science_sources']!=read(plan['inputs']['science_plan']['path'])['source_sha256'] or len(plan['science_sources'])!=49:raise ValueError('ORIGINAL_49_SCIENCE_PINS_REQUIRED')
    return plan

def execute(output,progress=None):
    output=Path(output);plan=load_plan(output)
    if (output/'STARTED.json').exists():raise ValueError('AUDIT_ALREADY_STARTED_USE_VERIFY_OR_NEW_DIRECTORY')
    write_new(output/'STARTED.json',dict(status='STARTED_NOT_PASS',at=now(),plan_sha256=digest(plan),**BOUNDARY))
    before=snapshot(plan);write_new(output/'before.json',before)
    failure=None;files={}
    try:
        from .replay import replay_target
        original=read(plan['inputs']['original_synthetic']['path'])
        family=rescore_family(original);write_new(output/'family-12.json',family);files['family-12.json']=sha(output/'family-12.json')
        old_failures=read(plan['inputs']['original_decision']['path'])['negative_control_failures']
        old=old_failures[TARGET]
        target=family['cells'][TARGET]
        if target['hits']!=69 or target['n']!=2880 or abs(target['holm_p']-old['holm_p'])>1e-12 or set(family['rejections'])!=set(old_failures):
            raise ValueError('ORIGINAL_NEGATIVE_FAILURE_NOT_REPRODUCED')
        replay=replay_target(original,progress=progress)
        if replay.get('status')!='PASS' or replay.get('n')!=2880 or replay.get('target_hits')!=69 or not replay.get('original_anomaly_reproduced'):
            raise ValueError('EXACT_TARGET_REPLAY_REQUIRED')
        write_new(output/'replay.json',replay);files['replay.json']=sha(output/'replay.json')
        proof=[permutation_check(5,2),permutation_check(6,3)]
        write_new(output/'permutation-proof.json',proof);files['permutation-proof.json']=sha(output/'permutation-proof.json')
    except BaseException as exc:
        failure=dict(error=type(exc).__name__,reason=code_reason(exc))
    try:
        after=snapshot(plan)
        changes={k:dict(before=before.get(k),after=after.get(k)) for k in set(before)|set(after) if before.get(k)!=after.get(k)}
        if own_sources()!=plan['audit_sources']:changes['audit_source_membership_or_content']=dict(before=plan['audit_sources'],after=own_sources())
        write_new(output/'after.json',after);write_new(output/'integrity.json',dict(status='PASS' if not changes else 'FAIL',changes=changes))
    except BaseException as exc:
        changes={'snapshot_failure':dict(error=type(exc).__name__,reason=code_reason(exc))}
    if failure or changes:
        write_new(output/'failure.json',dict(status='FAIL',primary_failure=failure,integrity_changes=changes,finished_at=now(),**BOUNDARY))
        raise ValueError('AUDIT_FAILED_EVIDENCE_RETAINED')
    result=dict(status='PASS_ORIGINAL_SEED_REPLAY_AND_INTEGRITY_ONLY',finished_at=now(),files=files,
        target=family['cells'][TARGET],original_negative_control='FALSIFIED_REPRODUCED_NOT_FIXED',
        identified_causal_defect=None,cause='UNRESOLVED',selected_candidate=None,
        prediction_advantage='NO_PROVEN_IMPROVEMENT',original_science_sources_unchanged=49,**BOUNDARY)
    write_new(output/'result.json',result)
    write_new(output/'result-sha.json',dict(sha256=digest(result)))
    return result

def verify(output):
    output=Path(output);load_plan(output);result=read(output/'result.json')
    if digest(result)!=read(output/'result-sha.json')['sha256']:raise ValueError('AUDIT_RESULT_SHA_MISMATCH')
    if result['status']!='PASS_ORIGINAL_SEED_REPLAY_AND_INTEGRITY_ONLY':raise ValueError('COMPLETED_AUDIT_REQUIRED')
    if read(output/'integrity.json')['status']!='PASS':raise ValueError('AUDIT_INTEGRITY_FAILED')
    if set(result['files'])!={'family-12.json','replay.json','permutation-proof.json'} or any(result.get(k)!=v for k,v in BOUNDARY.items()):raise ValueError('AUDIT_RESULT_SCOPE_CHANGED')
    for name,expected in result['files'].items():
        if not (output/name).resolve().is_relative_to(output.resolve()) or sha(output/name)!=expected:raise ValueError('AUDIT_RESULT_FILE_SHA_MISMATCH')
    if read(output/'before.json')!=read(output/'after.json'):raise ValueError('AUDIT_INPUTS_CHANGED')
    family=read(output/'family-12.json');replay=read(output/'replay.json')
    if result['target']!=family['cells'][TARGET] or result['target']['hits']!=69 or result['target']['n']!=2880 or TARGET not in family['rejections'] or replay['n']!=2880 or replay['target_hits']!=69:raise ValueError('ORIGINAL_FAILURE_RESULT_MISMATCH')
    return dict(status='PASS_READONLY_RECEIPT_VERIFICATION_NOT_MODEL_RERUN',original_failure='FALSIFIED',cause='UNRESOLVED',**BOUNDARY)
