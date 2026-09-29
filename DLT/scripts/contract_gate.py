from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    report = {
        "schema": "dlt-contract-gate-v1",
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "python": sys.version,
        "code_hashes": {
            "net_client": sha(ROOT / "src" / "glp" / "net_client.py"),
            "sources": sha(ROOT / "src" / "glp" / "sources.py"),
            "storage": sha(ROOT / "src" / "glp" / "storage.py"),
        },
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }
    out = ROOT / "artifacts" / "contract_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"stdout","stderr"}}, ensure_ascii=False))
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
