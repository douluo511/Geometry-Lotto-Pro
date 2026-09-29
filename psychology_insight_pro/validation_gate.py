from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
MODES = {
    "unit": "test_core.py",
    "contract": "test_contracts.py",
    "fault": "test_fault_injection.py",
    "integration": "test_integration.py",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=sorted(MODES), required=True)
    a = p.parse_args()
    proc = subprocess.run(
        [sys.executable, str(TESTS / MODES[a.mode])],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    report = {
        "schema": "psychology-validation-gate-v1",
        "mode": a.mode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "python": sys.version,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }
    out = ROOT / f"{a.mode}_gate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"stdout", "stderr"}}, ensure_ascii=False))
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
