"""Pinned offline graph contract. No model, URL or publication authority inputs."""
from copy import deepcopy
from datetime import datetime,timezone
from importlib.metadata import version
from pathlib import Path
import hashlib,re,sys

from .journal import GraphBlocked,digest
from research.ssq_dlt_agent_v1.policy import validate_config

ROOT=Path(__file__).resolve().parents[2]
BOUNDARY=dict(formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0,
              official_next_target='BLOCKED',repository_independence='FAIL',final_gate='FAIL')
STAGES=('source_guard','memory','verify_official_sources','run_frozen_models','audit_experiment','deliver_report','gate')
TOOL_ARGUMENTS={'verify_official_sources':{},'run_frozen_models':{},
                'audit_experiment':{'action':'inspect','hypothesis_json':''},'deliver_report':{}}
EXPECTED={'verify_official_sources':'HISTORY_CHECKED','run_frozen_models':'NON_FORMAL_RESEARCH_UNASSIGNED',
          'audit_experiment':'AUDIT_CHECKED','deliver_report':'REPORT_SAVED'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def aware(value):
    if not isinstance(value,datetime) or value.tzinfo is None:raise GraphBlocked('AWARE_CLOCK_REQUIRED')
    return value.astimezone(timezone.utc)

def validate(value):
    if type(value) is not dict or set(value)-{'root','host','sources','memory_queries','limits'} or not {'root','host','sources'}<=set(value):raise GraphBlocked('INVALID_GRAPH_CONFIG')
    result=deepcopy(value)
    if type(result['root']) is not str or not Path(result['root']).is_absolute():raise GraphBlocked('ABSOLUTE_GRAPH_ROOT_REQUIRED')
    root=Path(result['root']).resolve();result['root']=str(root)
    host=validate_config(result['host'])
    if Path(host['state_dir']).resolve()!=root/'host':raise GraphBlocked('HOST_STATE_MUST_USE_OWN_GRAPH_SUBDIRECTORY')
    if host['live_sources'] or host['recipient'] is not None:raise GraphBlocked('GRAPH_V1_OFFLINE_NO_MAIL_REQUIRED')
    if set(result['sources'])!={'SSQ','DLT'}:raise GraphBlocked('BOTH_RAW_SOURCE_PAIRS_REQUIRED')
    paths=[]
    for specs in result['sources'].values():
        if type(specs) is not list or len(specs)!=2:raise GraphBlocked('EXACTLY_TWO_RAW_SOURCES_REQUIRED')
        for spec in specs:
            if (type(spec) is not dict or set(spec)!={'path','sha256'} or type(spec['path']) is not str
                    or not Path(spec['path']).is_absolute() or type(spec['sha256']) is not str
                    or not re.fullmatch('[a-f0-9]{64}',spec['sha256'])):raise GraphBlocked('INVALID_RAW_SOURCE_PIN')
            paths.append(Path(spec['path']).resolve())
    paths.extend(Path(p['path']).resolve() for p in host['history'].values())
    if any(p.is_relative_to(root) or root.is_relative_to(p.parent) for p in paths):raise GraphBlocked('GRAPH_STATE_MUST_BE_SEPARATE_FROM_INPUTS')
    queries=result.setdefault('memory_queries',[])
    if type(queries) is not list or len(queries)>32:raise GraphBlocked('INVALID_MEMORY_QUERIES')
    for query in queries:
        if (type(query) is not dict or set(query)!={'key','scope'} or type(query['key']) is not str or not 1<=len(query['key'])<=256
                or query['scope'] not in ('FACT','POLICY','FAILURE','HYPOTHESIS')):raise GraphBlocked('INVALID_MEMORY_QUERY')
    limits=result.setdefault('limits',{})
    if type(limits) is not dict or set(limits)-{'max_stage_calls','max_wall_seconds'}:raise GraphBlocked('INVALID_GRAPH_LIMITS')
    for key,default,upper in (('max_stage_calls',12,64),('max_wall_seconds',1800,86400)):
        number=limits.setdefault(key,default)
        if type(number) is not int or not 1<=number<=upper:raise GraphBlocked('INVALID_GRAPH_LIMIT')
    result['host']=host
    return result

def input_manifest(config):
    result={}
    for game in ('SSQ','DLT'):
        for label,spec in [('archive',config['host']['history'][game])]+[(f'raw-{i}',s) for i,s in enumerate(config['sources'][game])]:
            path=Path(spec['path']).resolve()
            if not path.is_file() or sha(path)!=spec['sha256']:raise GraphBlocked('GRAPH_INPUT_PIN_MISMATCH')
            result[game+'|'+label]=dict(path=str(path),sha256=spec['sha256'])
    return result

def source_manifest():
    result={}
    for name in ('ssq_dlt_agent_graph','ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44','ssq_dlt_d2_forensics_evidence','ssq_dlt_d2_forensics','ssq_dlt_d2_next'):
        for path in sorted((ROOT/'research'/name).rglob('*.py')):
            if '__pycache__' not in path.parts:result[path.relative_to(ROOT).as_posix()]=sha(path)
    return result

def identity(config):
    lock=Path(__file__).with_name('requirements.lock')
    expected=dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)',lock.read_text(encoding='utf-8'),re.MULTILINE))
    if not expected:raise GraphBlocked('EMPTY_DEPENDENCY_LOCK')
    actual={name:version(name) for name in expected}
    if actual!=expected:raise GraphBlocked('GRAPH_DEPENDENCY_LOCK_MISMATCH')
    return dict(schema='SSQ_DLT_AGENT_GRAPH_1',config_sha256=digest(config),input_manifest=input_manifest(config),
        source_manifest=source_manifest(),graph_definition=list(STAGES),tool_arguments=TOOL_ARGUMENTS,
        dependency_versions=actual,dependency_lock_sha256=sha(lock),
        python=sys.version,sqlite_runtime=__import__('sqlite3').sqlite_version,
        planning='DETERMINISTIC_NO_MODEL_CALLS',network='DISABLED_IN_GRAPH_V1',**BOUNDARY)
