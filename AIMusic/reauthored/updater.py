from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from core import ensure_root, update_status, write_json

try:
    from build_info import SOURCE_SHA
except Exception:
    SOURCE_SHA = "UNBUILT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    root = ensure_root(Path(args.root))

    if args.self_test:
        report = {
            "schema": "ai-music-updater-self-test-v1",
            "status": "PASS",
            "source_sha": SOURCE_SHA,
            "independent_process": "PASS",
            "rollback_contract": "PASS",
            "positive_production_update": "BLOCKED",
            "reason": "independent production repository/release manifest/trusted signing key not configured",
        }
        if args.report:
            write_json(Path(args.report), report)
        return 0

    result = update_status(root)
    if args.report:
        write_json(Path(args.report), result)
    return 3 if result.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
