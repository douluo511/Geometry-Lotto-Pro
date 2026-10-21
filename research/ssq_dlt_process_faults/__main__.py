import argparse
import json
from pathlib import Path
from .harness import execute

def main():
    parser=argparse.ArgumentParser(description="Synthetic state, actual process/loopback fault laboratory only")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--cases",nargs="*")
    parser.add_argument("--verify",action="store_true")
    args=parser.parse_args()
    if args.verify:
        from .verify import verify
        print(json.dumps(verify(args.output),ensure_ascii=False));return 0
    result=execute(args.output,args.cases)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False))
    print(json.dumps([dict(case=x['case'],status=x['status']) for x in result['cases']]))
    return 0 if result['status'].startswith('DIAGNOSTIC_COMPLETE') else 1

if __name__=='__main__': raise SystemExit(main())
