from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import sys

from app.build_info import VERSION
from app.update_runtime import UpdateBlocked, ReleaseNetwork, apply_update, atomic_json, config, digest, release_context


def main() -> int:
    ap = ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--target")
    ap.add_argument("--current-version", default=VERSION)
    ap.add_argument("--current-source")
    ap.add_argument("--wait-pid", type=int)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        cfg = config(root)
        network = ReleaseNetwork(root / "evidence" / "updater_network.jsonl")
        if not args.target or not args.current_source:
            raise ValueError("trusted current Exact EXE target/source required")
        target = Path(args.target).resolve()
        if target.name != "RealMoneyFinance.exe" or not target.is_file():
            raise ValueError("trusted local application target required")
        if args.check:
            manifest = release_context(cfg, args.current_version, network, args.current_source, digest(target), target.stat().st_size)
            result = {"status": "PASS", "stage": "SIGNED_PRODUCTION_RELEASE_AVAILABLE",
                      "version": manifest["version"], "source_sha": manifest["source_sha"]}
        else:
            if not args.wait_pid:
                raise ValueError("trusted app target/source and close-before-replace parent PID required")
            result = apply_update(Path(args.target), root, cfg, args.current_version, args.current_source,
                                  network, parent_pid=args.wait_pid)
        returncode = 0
    except UpdateBlocked as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
        returncode = 3
    except Exception as exc:
        result = {"status": "FAIL", "error": repr(exc)}
        returncode = 1
    atomic_json(root / "evidence" / "updater_result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

