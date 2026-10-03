from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(exe: Path, *args: str) -> dict:
    try:
        proc = subprocess.run([str(exe), *args], timeout=120)
        return {"status": "PASS" if proc.returncode == 0 else "FAIL", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "exit_code": None, "error": "timeout"}
    except Exception as exc:
        return {"status": "FAIL", "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    exe = Path(a.exe).resolve()
    exists = exe.exists() and exe.is_file()
    digest = sha256(exe) if exists else None
    with tempfile.TemporaryDirectory(prefix="psychology-app-exact-") as td:
        proof_path = Path(td) / "self_test.json"
        self_test = run(exe, "--self-test", "--result-file", str(proof_path)) if exists else {"status": "FAIL", "error": "EXE missing"}
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
            valid = (self_test.get("exit_code") == 0 and proof.get("schema") == "psychology-app-self-test-v1"
                     and proof.get("status") == "PASS" and isinstance(proof.get("process_id"), int)
                     and proof["process_id"] > 0 and proof["process_id"] != os.getpid())
            self_test.update({"status": "PASS" if valid else "FAIL", "result": proof})
        except Exception as exc:
            self_test.update({"status": "FAIL", "error": f"missing or invalid current subprocess result: {exc}"})
    gui_smoke = run(exe, "--gui-smoke") if exists else {"status": "FAIL", "error": "EXE missing"}
    windows = os.name == "nt"

    report = {
        "schema": "psychology-exact-candidate-gate-v1",
        "status": "PASS" if exists and windows and self_test["status"] == "PASS" and gui_smoke["status"] == "PASS" else "FAIL",
        "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "github_sha": (os.environ.get("PSYCHOLOGY_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
        "runner_os": os.environ.get("RUNNER_OS"),
        "exe": exe.name,
        "exe_sha256": digest,
        "windows_build": "PASS" if exists and windows else "FAIL",
        "exact_exe": "PASS" if exists and windows and self_test["status"] == "PASS" else "FAIL",
        "self_test": self_test,
        "gui_smoke": gui_smoke,
    }
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
