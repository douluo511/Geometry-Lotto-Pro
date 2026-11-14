"""Export attributed records, execution traces, lineage and chronological audit.

Hashes reference a separate immutable freeze file (never a self-referential hash).
"""
import argparse
import hashlib
import json
from pathlib import Path

from research.supercompute.v47_models import canonical, validate_ticket
from research.supercompute.v47_registry import REGISTRY


def export_delivery(payload, frozen_dir, output_dir):
    if set(payload.get('games',{})) != {'ssq','dlt'}:
        raise ValueError('delivery requires both games')
    records, executions, lineage, validation = [], {}, {}, {}
    for game, report in payload['games'].items():
        independent = report['independent_11']
        frozen_path = Path(frozen_dir)/f"{game}-{report['target_issue']}-v47-unified.json"
        raw = frozen_path.read_bytes()
        frozen = json.loads(raw)
        if frozen['source'] != report:
            raise ValueError('freeze differs from computed report')
        sha = hashlib.sha256(raw).hexdigest()
        if (len(report['proposed_tickets']) != 11 or len(independent['models']) != 11
                or independent['model_count'] != 11):
            raise ValueError('exactly eleven attributed model outputs required')
        for cls, ticket in zip(REGISTRY,report['proposed_tickets']):
            execution = independent['models'][cls.label]
            if (ticket['model_number'] != cls.number or ticket['model_name'] != cls.label
                    or any(ticket[k] != execution['prediction']['ticket'][k] for k in ('front','back','dan2'))):
                raise ValueError('ticket is not the named model output')
            validate_ticket(ticket,game)
            records.append({'lottery':game,'target_issue':report['target_issue'],
                'model_number':cls.number,'model_name':cls.label,
                'model_identity':f'{cls.__module__}.{cls.__name__}',
                'training_cutoff_issue':report['history_last_issue'],
                'training_data_sha256':report['history_sha256'],
                'front':ticket['front'],'back':ticket['back'],
                'parameters_summary':{k:v for k,v in execution['fit'].items()
                                      if isinstance(v,(str,int,float,bool,type(None)))},
                'calculation_summary':{'fit_sha256':hashlib.sha256(canonical(execution['fit'])).hexdigest(),
                    'prediction_sha256':hashlib.sha256(canonical(execution['prediction'])).hexdigest(),
                    'functions':execution['functions'],'status':execution['status']},
                'seed':report['seed'],'generated_utc':frozen['created_utc'],
                'frozen_file':f'frozen/{frozen_path.name}','frozen_sha256':sha,
                'source_status':report.get('history_status','UNVERIFIED'),
                'forecast_status':'RESEARCH_CANDIDATE_NO_PROVEN_EDGE'})
        executions[game] = independent
        lineage[game] = report['evolution']
        validation[game] = {'M1':report['validation']['M1'],
                           'M2':report['validation']['M2'],
                           'M3':report['validation']['M3'],
                           'chronological_folds':independent['validation_all_11']['fold_evidence'],
                           'predictive_edge':'NO_EDGE',
                           'future_draw_score':'UNVERIFIED_UNTIL_OFFICIAL_PUBLICATION'}
    if len(records) != 22:
        raise ValueError('exactly twenty-two rows required')
    root = Path(output_dir)
    documents = {'22_model_predictions.json':{'schema':'SSQDLT_22_MODEL_RECORDS_V1','record_count':22,'records':records},
                 'model_execution_audit.json':executions,
                 'model_evolution_lineage.json':lineage,
                 'validation_results.json':validation}
    lines = ['# 22条实际模型计算记录', '',
        '研究候选，未证明优于随机基线。物理模型：UNCALIBRATED_PHYSICS_SIMULATION。', '',
        '| 彩种 | 目标期号 | 模型 | 红球/前区 | 蓝球/后区 |',
        '|---|---|---|---|---|']
    for row in records:
        nums = lambda values:' '.join(f'{n:02d}' for n in values)
        lines.append(f"| {row['lottery'].upper()} | {row['target_issue']} | {row['model_number']} {row['model_name']} | {nums(row['front'])} | {nums(row['back'])} |")
    contents = {name:canonical(value) for name,value in documents.items()}
    contents['22_model_predictions.md'] = ('\n'.join(lines)+'\n').encode('utf-8')
    for game,report in payload['games'].items():
        name=f"{game}-{report['target_issue']}-v47-unified.json"
        contents['frozen/'+name]=(Path(frozen_dir)/name).read_bytes()
    if any((root/name).exists() for name in contents):
        raise FileExistsError('refuse to overwrite delivery evidence')
    for name,data in contents.items():
        path=root/name; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:
            f.write(data)
    return {'record_count':len(records),'files':{name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--frozen-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    print(json.dumps(export_delivery(json.loads(args.report.read_bytes()),args.frozen_dir,args.output_dir)))


if __name__ == '__main__':
    main()
