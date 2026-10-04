from __future__ import annotations

import argparse
import json
from pathlib import Path

from updater_runtime import (
    ReleaseNetwork, UpdateBlocked, apply_update, atomic_json, load_config, self_test,
)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--root")
    ap.add_argument("--target")
    ap.add_argument("--current-version", default="0.4.0")
    ap.add_argument("--current-source")
    ap.add_argument("--wait-pid", type=int)
    args = ap.parse_args()

    if args.self_test:
        result = self_test()
        if args.report:
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1

    if not args.root:
        raise SystemExit("--root is required outside --self-test")
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        cfg = load_config(root)
        if not args.target or not args.current_source:
            raise ValueError("trusted current target/source required")
        network = ReleaseNetwork(root / "evidence" / "updater_network.jsonl")
        result = apply_update(
            Path(args.target), root, cfg, args.current_version, args.current_source,
            network, parent_pid=args.wait_pid,
        )
        rc = 0
    except UpdateBlocked as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
        rc = 3
    except Exception as exc:
        result = {"status": "FAIL", "error": repr(exc)}
        rc = 1
    atomic_json(root / "evidence" / "updater_result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
