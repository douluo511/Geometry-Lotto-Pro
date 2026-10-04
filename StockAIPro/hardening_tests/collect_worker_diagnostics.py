"""Publish a fixed diagnostic allowlist from disposable CI worker receipts.

Raw exception messages, logs, payloads, state, and cache never leave the runtime.
"""
from pathlib import Path
import argparse
import json
import os
import re


def collect(data_root: Path) -> dict:
    report = {"source_commit": os.environ.get("STOCK_SOURCE_SHA"), "workers": {}}
    for action in ("core", "advanced", "repair"):
        receipt = data_root / "evidence" / f"worker_{action}.json"
        if not receipt.is_file():
            continue
        obj = json.loads(receipt.read_text(encoding="utf-8"))
        error = str(obj.get("error", ""))
        error_type = re.match(r"([A-Za-z_][A-Za-z_0-9]*)\(", error)
        frames = re.findall(r'File "([^"\n]+)", line (\d+)', str(obj.get("traceback", "")))
        report["workers"][action] = {
            "status": "FAIL" if obj.get("status") == "FAIL" else "NOT VERIFIED",
            "frozen": obj.get("frozen") is True,
            "exception_type": error_type.group(1) if error_type else "UNKNOWN",
            "frames": [{"module": Path(name).name, "line": int(line)} for name, line in frames],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = collect(Path(args.data_root))
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
