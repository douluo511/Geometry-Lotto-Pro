from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import sys


def main() -> int:
    ap = ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    cfg_path = root / "updater.json"
    if not cfg_path.exists():
        print(json.dumps({"status": "BLOCKED", "reason": "production updater config missing"}))
        return 3
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": repr(exc)}), file=sys.stderr)
        return 1
    if not cfg.get("manifest_url") or not cfg.get("enabled"):
        print(json.dumps({"status": "BLOCKED", "reason": "signed production release endpoint is not configured"}))
        return 3
    print(json.dumps({"status": "BLOCKED", "reason": "real N->N+1 updater implementation not yet accepted"}))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
