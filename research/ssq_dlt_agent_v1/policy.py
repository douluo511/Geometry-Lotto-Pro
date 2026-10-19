"""Strict operator configuration and a small, non-extensible tool surface."""
from copy import deepcopy
from pathlib import Path
import math
import re

from research.ssq_dlt_v45.discovery import _native as native
from research.ssq_dlt_v45.store import canonical,digest,parse

TOOLS=('discover_sources','verify_official_sources','run_frozen_models','audit_experiment','deliver_report')
BOUNDARY=dict(formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0,
              official_next_target='BLOCKED',repository_independence='FAIL',final_gate='FAIL')
DEFAULT_SDK=dict(max_turns=10,max_model_calls=8,max_input_tokens=20000,max_output_tokens=1000,
                 max_seconds=120,max_estimated_usd=0.20,input_usd_per_million=None,output_usd_per_million=None)

class AgentBlocked(ValueError): pass

def validate_config(value):
    allowed={'state_dir','history','live_sources','discovery','recipient','limits','sdk'}
    if type(value) is not dict or set(value)-allowed or not {'state_dir','history'}<=set(value):
        raise AgentBlocked('INVALID_CONFIG_FIELDS')
    result=deepcopy(value)
    if type(result['state_dir']) is not str or not Path(result['state_dir']).is_absolute():
        raise AgentBlocked('ABSOLUTE_NEW_AGENT_STATE_REQUIRED')
    root=Path(result['state_dir']).resolve()
    if type(result['history']) is not dict or set(result['history'])!={'SSQ','DLT'}:
        raise AgentBlocked('BOTH_PINNED_HISTORIES_REQUIRED')
    for spec in result['history'].values():
        if (type(spec) is not dict or set(spec)!={'path','sha256'} or type(spec['path']) is not str
                or not Path(spec['path']).is_absolute() or type(spec['sha256']) is not str
                or not re.fullmatch('[a-f0-9]{64}',spec['sha256'])):
            raise AgentBlocked('INVALID_HISTORY_PIN')
        source=Path(spec['path']).resolve()
        if root==source.parent or root.is_relative_to(source.parent) or source.is_relative_to(root):
            raise AgentBlocked('STATE_MUST_BE_SEPARATE_FROM_INPUTS')
    result['state_dir']=str(root)
    result.setdefault('live_sources',True)
    if type(result['live_sources']) is not bool: raise AgentBlocked('BOOLEAN_LIVE_SOURCES_REQUIRED')
    result.setdefault('discovery',{'transport':'rest','attempts':2,'timeout_seconds':5})
    if type(result['discovery']) is not dict or set(result['discovery'])-{'transport','attempts','timeout_seconds'}:
        raise AgentBlocked('FIXED_DISCOVERY_CONFIGURATION_REQUIRED')
    if result['discovery'].get('transport','rest') not in ('rest','mcp'):
        raise AgentBlocked('INVALID_DISCOVERY_TRANSPORT')
    for k,upper in (('attempts',3),('timeout_seconds',10)):
        x=result['discovery'].get(k,2 if k=='attempts' else 5)
        if type(x) is not int or not 1<=x<=upper: raise AgentBlocked('INVALID_DISCOVERY_LIMIT')
    recipient=result.setdefault('recipient',None)
    if recipient is not None and (type(recipient) is not str or not re.fullmatch(r'[^\s<>@,;\r\n]+@[^\s<>@,;\r\n]+\.[^\s<>@,;\r\n]+',recipient)):
        raise AgentBlocked('INVALID_RECIPIENT')
    lim=result.setdefault('limits',{})
    if type(lim) is not dict or set(lim)-{'max_tool_calls','max_attempts_per_tool','max_seconds'}:
        raise AgentBlocked('INVALID_LIMIT_FIELDS')
    for k,default,upper in (('max_tool_calls',12,24),('max_attempts_per_tool',2,3),('max_seconds',120,600)):
        x=lim.setdefault(k,default)
        if type(x) is not int or not 1<=x<=upper: raise AgentBlocked('INVALID_TOOL_LIMIT')
    sdk=result.setdefault('sdk',{})
    if type(sdk) is not dict or set(sdk)-set(DEFAULT_SDK): raise AgentBlocked('INVALID_SDK_FIELDS')
    for k,default in DEFAULT_SDK.items(): sdk.setdefault(k,default)
    for k,upper in (('max_turns',20),('max_model_calls',16),('max_input_tokens',100000),('max_output_tokens',4000),('max_seconds',600)):
        if type(sdk[k]) is not int or not 1<=sdk[k]<=upper: raise AgentBlocked('INVALID_SDK_LIMIT')
    for k in ('max_estimated_usd','input_usd_per_million','output_usd_per_million'):
        x=sdk[k]
        if x is None and k!='max_estimated_usd': continue
        if type(x) not in (int,float) or not math.isfinite(x) or x<=0 or x>1000:
            raise AgentBlocked('INVALID_COST_LIMIT')
    return result

def validate_call(name,args):
    if type(name) is not str or name not in TOOLS or type(args) is not dict:
        raise AgentBlocked('TOOL_NOT_ALLOWED')
    if name!='audit_experiment':
        if args: raise AgentBlocked('UNEXPECTED_TOOL_ARGUMENTS')
        return {}
    if set(args)-{'action','hypothesis_json'}: raise AgentBlocked('UNEXPECTED_AUDIT_ARGUMENTS')
    action=args.get('action','inspect'); text=args.get('hypothesis_json','')
    if action not in ('inspect','register_hypothesis','run_registered_experiment') or type(text) is not str or len(text.encode('utf-8'))>8000:
        raise AgentBlocked('INVALID_AUDIT_ACTION')
    if action!='register_hypothesis':
        if text: raise AgentBlocked('NO_HYPOTHESIS_ARGUMENT_FOR_THIS_ACTION')
        return dict(action=action,hypothesis_json='')
    try: hypothesis=parse(text)
    except (ValueError,TypeError): raise AgentBlocked('INVALID_HYPOTHESIS_JSON') from None
    if type(hypothesis) is not dict or set(hypothesis)!={'question','falsification','kind','parameters'}:
        raise AgentBlocked('INVALID_HYPOTHESIS_FIELDS')
    if any(type(hypothesis[k]) is not str or not 5<=len(hypothesis[k])<=1000 for k in ('question','falsification')):
        raise AgentBlocked('FALSIFIABLE_QUESTION_REQUIRED')
    from .experiments import SYNTHETIC_PARAMETERS
    kind=hypothesis['kind']; params=hypothesis['parameters']
    if kind not in ('synthetic_pair_shrink','prospective_d2') or type(params) is not dict:
        raise AgentBlocked('UNAPPROVED_EXPERIMENT_KIND')
    expected=dict(SYNTHETIC_PARAMETERS) if kind=='synthetic_pair_shrink' else {}
    if canonical(params)!=canonical(expected): raise AgentBlocked('UNREGISTERED_EXPERIMENT_PARAMETERS')
    return dict(action=action,hypothesis_json=canonical(hypothesis))
