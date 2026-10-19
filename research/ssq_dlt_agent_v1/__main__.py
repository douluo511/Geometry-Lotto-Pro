"""Explicit live, offline SDK fixture, or real-tool smoke execution."""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from research.ssq_dlt_v45.workflow import active_slot
from .core import AgentContext, exclusive
from .policy import AgentBlocked, BOUNDARY, canonical, native, parse


def smoke(context):
    from .experiments import SYNTHETIC_PARAMETERS
    calls=[]
    for name in ('discover_sources','verify_official_sources','run_frozen_models'):
        calls.append(context.call_tool(name,{}))
    calls.append(context.call_tool('audit_experiment',{'action':'inspect'}))
    hypothesis=dict(question='Does uniform pair shrinkage preserve every pair rank and the selected D2?',
        falsification='Any full-rank or selected-pair mismatch in a fixed synthetic case falsifies rank invariance.',
        kind='synthetic_pair_shrink',parameters=dict(SYNTHETIC_PARAMETERS))
    calls.append(context.call_tool('audit_experiment',{'action':'register_hypothesis','hypothesis_json':canonical(hypothesis)}))
    calls.append(context.call_tool('audit_experiment',{'action':'run_registered_experiment'}))
    return dict(status='TOOLS_SMOKE_COMPLETED' if all(not r['status'].startswith('BLOCKED') for r in calls) else 'TOOLS_SMOKE_WITH_BLOCKS',
                mode=context.mode,paid_api_calls=0,model_calls=0,tool_statuses=[r['status'] for r in calls])


def execute(config,mode,run_key):
    mapped={'live':'SDK_LIVE_MODEL','sdk-fixture':'SDK_SIMULATED_MODEL','tools-smoke':'TOOLS_SMOKE_NO_MODEL'}
    context=AgentContext(config,run_key,mode=mapped[mode])
    old=context.claim_execution()
    if old is None:
        try:
            if mode=='tools-smoke': result=smoke(context)
            else:
                from .sdk_runner import run_agent
                fixture=None
                if mode=='sdk-fixture':
                    from .sdk_fixture import make_fixture_model
                    fixture=make_fixture_model()
                result=asyncio.run(run_agent(context,context.config,fixture_model=fixture))
        except Exception as exc:
            from .core import _error_code
            context.mark_model_call_unknown()
            result=dict(status='BLOCKED_HOST_EXECUTION',mode=context.mode,reason=_error_code(exc),error=type(exc).__name__)
        context.finish_execution(result)
    else: result=old['result']
    # Final reporting is mandatory host work, not a model-authored verdict.
    delivery=context.finalize_report()
    saved=context.ledger.read('report',delivery.get('report_id',''))
    receipt=dict(schema='GLP_AGENT_EXECUTION_RECEIPT_1',run_id=context.run_id,execution_mode=context.mode,
                 runtime={k:v for k,v in result.items() if k!='model_message'},
                 delivery=delivery,report_dir=saved.get('report_dir') if saved else None,
                 ledger_integrity=context.ledger.integrity(),reused_execution=old is not None,**BOUNDARY)
    # A retry receipt has a new name; the first receipt and prediction stay fixed.
    from .policy import digest
    target=context.run_root/('receipt-'+digest(receipt)[:16]+'.json')
    exclusive(target,(canonical(receipt)+'\n').encode('utf-8'))
    return receipt


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',required=True); ap.add_argument('--mode',choices=('live','sdk-fixture','tools-smoke'),default='live')
    ap.add_argument('--run-key'); args=ap.parse_args(argv)
    try:
        path=Path(args.config)
        if not path.is_absolute(): raise AgentBlocked('ABSOLUTE_CONFIG_REQUIRED')
        config=parse(native(path).read_bytes())
        run_key=args.run_key or active_slot(datetime.now(timezone.utc)).isoformat()
        receipt=execute(config,args.mode,run_key)
        print(canonical(receipt))
        status=receipt['runtime']['status']
        return 0 if status in ('SDK_COMPLETED','TOOLS_SMOKE_COMPLETED') and receipt['delivery']['status']=='REPORT_SAVED' else 2
    except Exception as exc:
        # Do not echo secrets or local paths from dependency exception strings.
        from .core import _error_code
        print(canonical(dict(status='BLOCKED',reason=_error_code(exc),error=type(exc).__name__,**BOUNDARY)))
        return 2

if __name__=='__main__': raise SystemExit(main())
