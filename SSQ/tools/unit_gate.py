from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    report = {
        "schema": "ssq-unit-gate-v1",
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "python": sys.version,
        "tested_code": {
            "net_client_sha256": _sha(ROOT / "SSQ" / "glp" / "net_client.py"),
            "sources_sha256": _sha(ROOT / "SSQ" / "glp" / "sources.py"),
            "service_sha256": _sha(ROOT / "SSQ" / "glp" / "service.py"),
        },
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }
    out = ROOT / "evidence" / "SSQ" / "UNIT_GATE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"stdout", "stderr"}}, ensure_ascii=False))
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
