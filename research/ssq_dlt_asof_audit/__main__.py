"""Exclusive fixture execution or read-only evidence verification."""
import argparse
from pathlib import Path

from .audit import canonical, execute, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("execute")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    check = subs.add_parser("verify")
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(args.protocol, args.output) if args.command == "execute" else verify(args.output)
        print(canonical(result))
        return 0 if result["status"].startswith("PASS") else 1
    except Exception as exc:
        print(canonical(dict(status="FAIL", error=type(exc).__name__, reason=str(exc),
                             formal_A=0, decision="NO_EDGE")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
