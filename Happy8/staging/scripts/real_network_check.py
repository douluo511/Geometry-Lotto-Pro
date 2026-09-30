from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.sources import build_official_snapshot
from happy8.storage import Store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()

    report, raw_sources = build_official_snapshot()
    with tempfile.TemporaryDirectory(prefix="happy8-live-store-") as td:
        store = Store(Path(td))
        commit = store.commit_official_snapshot(report, raw_sources)
        integrity = store.integrity_check()
    report["storage_commit"] = commit
    report["storage_integrity"] = integrity

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    console_report = dict(report)
    console_report["draws"] = f"<{len(report.get('draws', []))} canonical draws omitted from console>"
    print(json.dumps(console_report, ensure_ascii=False, indent=2))
    ok = report.get("status") == "PASS" and integrity.get("status") == "PASS"
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
