from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

if os.name != "nt":
    raise SystemExit("Native Windows updater build required")
if sys.version_info[:2] != (3, 11):
    raise SystemExit(f"Python 3.11 required, got {sys.version}")

root = Path(__file__).resolve().parents[1]
project = root / "SSQ"
dist = root / "dist"
evidence = root / "evidence" / "SSQ"
work = root / "updater_build" / "work"
spec = root / "updater_build" / "spec"
for p in (dist, evidence, work, spec):
    p.mkdir(parents=True, exist_ok=True)

name = "Geometry_Lotto_Pro_SSQ_Updater"
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", name,
    "--paths", str(project),
    "--add-data", str(project / "resources") + ";resources",
    "--collect-all", "certifi",
    "--hidden-import", "glp.service",
    "--hidden-import", "glp.storage",
    "--hidden-import", "glp.sources",
    "--distpath", str(dist),
    "--workpath", str(work),
    "--specpath", str(spec),
    str(root / "updater.py"),
]
subprocess.run(cmd, cwd=root, check=True)
exe = dist / f"{name}.exe"
if not exe.is_file():
    raise SystemExit("Updater Exact EXE missing")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

exe_hash = sha256(exe)
checks = {}
env = os.environ.copy()
env["GLP_UPDATER_PARENT_PID"] = str(os.getpid())

for mode in ("software-self-test", "offline-failclosed", "self-test"):
    result_path = evidence / f"updater-{mode}.json"
    proc = subprocess.run(
        [str(exe), "--mode", mode, "--result-file", str(result_path)],
        env=env,
        timeout=1200,
    )
    payload = json.loads(result_path.read_text(encoding="utf-8-sig")) if result_path.is_file() else {}
    ok = bool(
        proc.returncode == 0
        and payload.get("schema") == "ssq-independent-updater-v2"
        and payload.get("mode") == mode
        and payload.get("status") == "PASS"
        and payload.get("updater_exe_sha256") == exe_hash
        and payload.get("parent_pid_match") is True
        and payload.get("github_sha") == os.environ.get("GITHUB_SHA")
        and payload.get("github_run_id") == os.environ.get("GITHUB_RUN_ID")
    )
    checks[mode] = {
        "status": "PASS" if ok else "FAIL",
        "exit_code": proc.returncode,
        "reported_updater_sha256": payload.get("updater_exe_sha256"),
        "parent_pid_match": payload.get("parent_pid_match"),
        "service_status": (payload.get("service_result") or {}).get("status")
        if isinstance(payload.get("service_result"), dict) else None,
        "result_file": result_path.name,
        "result_sha256": sha256(result_path) if result_path.is_file() else "",
    }

hard_failures = [name for name, row in checks.items() if row["status"] != "PASS"]
report = {
    "schema": "ssq-updater-exact-exe-acceptance-v3",
    "status": "PASS" if not hard_failures else "FAIL",
    "artifact": exe.name,
    "sha256": exe_hash,
    "bytes": exe.stat().st_size,
    "github_sha": os.environ.get("GITHUB_SHA"),
    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    "runner_os": os.environ.get("RUNNER_OS"),
    "python": sys.version,
    "checks": checks,
    "hard_failures": hard_failures,
    "hard_fail_count": len(hard_failures),
    "real_release_n_to_n_plus_1": "BLOCKED_PENDING_INDEPENDENT_REPOSITORY",
    "repository_independence": "FAIL",
    "final_gate": "FAIL",
}
report_path = evidence / "UPDATER_EXACT_EXE_ACCEPTANCE.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(evidence / "UPDATER_SHA256SUMS.txt").write_text(f"{exe_hash}  {exe.name}\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=True, sort_keys=True), flush=True)
if hard_failures:
    raise SystemExit("Updater Exact EXE acceptance failed: " + ", ".join(hard_failures))
