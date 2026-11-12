"""Synthetic CI computation or explicit local private historical research."""
import argparse
import json
from pathlib import Path

from research.formula_lab.benchmark import synthetic_rows
from research.formula_lab import private_io,prospective,statistics
from research.formula_lab.search import Config,evaluate
from research.formula_lab.expressions import digest


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self,message):
        # argparse normally includes user-supplied values in error messages.
        raise ValueError('invalid arguments')


def main(argv=None):
    p=PrivateArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('synthetic','private'))
    p.add_argument('--train',type=int,default=60)
    p.add_argument('--validation',type=int,default=20)
    p.add_argument('--holdout',type=int,default=10)
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--authorized-root',type=Path)
    p.add_argument('--input',type=Path)
    p.add_argument('--output',type=Path)
    try:
        opt=p.parse_args(argv)
        cfg=Config(opt.train,opt.validation,opt.holdout,workers=opt.workers)
        size=cfg.train+cfg.validation+cfg.holdout
        if opt.mode=='synthetic':
            if opt.input or opt.output or opt.authorized_root:raise ValueError('synthetic mode has no input/output paths')
            histories={g:synthetic_rows(g,size) for g in ('ssq','dlt')}
            origin='SYNTHETIC_NO_REAL_DRAW_DATA'
        else:
            if not all((opt.input,opt.output,opt.authorized_root)):raise PermissionError('explicit private paths required')
            private_io.checked_path(opt.output,opt.authorized_root)
            obj=private_io.read(opt.input,authorized_root=opt.authorized_root)
            histories=obj['games']
            if set(histories)!={'ssq','dlt'}:raise ValueError('both games required')
            origin='LOCAL_RETROSPECTIVE_UNVERIFIED_PROVENANCE_NOT_PROSPECTIVE'
        games={g:evaluate(histories[g],g,cfg) for g in ('ssq','dlt')}
        report=dict(schema='FORMULA_LAB_V1',origin=origin,input_sha256=digest(histories),
                    games=games,statistics=statistics.summarize(games),admission=prospective.admission(),
                    formal_A=0,edge='NO_EDGE',prospective_scored=0)
        # Hashes of private data and results are themselves private evidence.
        if opt.mode=='private':private_io.write(opt.output,report,authorized_root=opt.authorized_root)
        print(json.dumps(dict(status='SYNTHETIC_COMPLETE' if opt.mode=='synthetic' else 'PRIVATE_RESEARCH_SAVED',
            games=['ssq','dlt'],evaluated_per_mode=cfg.holdout,comparisons=report['statistics']['comparisons'],
            formal_A=0,edge='NO_EDGE',prospective_scored=0)))
        return 0
    except (ValueError,PermissionError,OSError,KeyError,TypeError):
        # Do not leak real values/paths through tracebacks into CI logs.
        print(json.dumps(dict(status='BLOCKED',formal_A=0,edge='NO_EDGE')))
        return 2


if __name__=='__main__':raise SystemExit(main())
