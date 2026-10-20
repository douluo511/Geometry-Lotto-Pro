import argparse,json
from pathlib import Path
from . import protocol

def main(argv=None):
    p=argparse.ArgumentParser(description='Reconstruct the original disclosed negative-control seed, never tune it away.')
    p.add_argument('action',choices=('prepare','execute','verify'));p.add_argument('--output',required=True,type=Path)
    for name in protocol.EXPECTED:p.add_argument('--'+name.replace('_','-'),type=Path)
    args=p.parse_args(argv)
    try:
        if args.action=='prepare':answer=protocol.prepare({name:getattr(args,name) for name in protocol.EXPECTED},args.output)
        elif args.action=='execute':answer=protocol.execute(args.output,progress=lambda value:print(protocol.canonical(value),flush=True))
        else:answer=protocol.verify(args.output)
        print(protocol.canonical(answer));return 0
    except Exception as exc:
        print(protocol.canonical(dict(status='FAIL',reason=protocol.code_reason(exc),error=type(exc).__name__,**protocol.BOUNDARY)));return 2

if __name__=='__main__':raise SystemExit(main())
