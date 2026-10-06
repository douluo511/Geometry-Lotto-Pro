import json, tempfile, shutil
from pathlib import Path
from .training_service import TrainingService
from ..engine.scoring import analyze_text
from ..engine.reversal import compare_variants

def run_self_test(base_dir:Path):
    checks={}
    try:
        r=analyze_text('我朋友每次都说马上到，结果半小时后才出现。后来我发现，马上不是时间，是一种人生理念。')
        checks['scoring_range']=all(0<=v<=100 for v in r.score.as_dict().values())
        checks['analysis_next_task']=bool(r.next_task)
    except Exception: checks['scoring_range']=checks['analysis_next_task']=False
    try:
        svc=TrainingService(base_dir); checks['storage_integrity']=svc.store.integrity()=='ok'; checks['drill_count']=len(svc.engine.drills)>=180; checks['case_count']=len(svc.engine.cases)>=60
        checks['repair']=svc.repair()['ok']; checks['analytics_contract']=set(svc.analytics().keys())=={'count','averages','weakest','strongest'}
    except Exception: checks['storage_integrity']=checks['drill_count']=checks['case_count']=checks['repair']=checks['analytics_contract']=False
    try:
        c=compare_variants('我迟到了。','我本来以为我只迟到五分钟，结果导航告诉我：你不是迟到，你是参加下一场。')
        checks['reversal_contract']=set(c.keys())>= {'original','variant','delta','verdict'}
    except Exception: checks['reversal_contract']=False
    return {'ok':all(checks.values()),'checks':checks}
