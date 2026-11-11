from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from bind_physical_gui import validate_gui


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"status": "FAIL", "error": "not an object"}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--main-exe", required=True)
    p.add_argument("--final-main-exe", required=True)
    p.add_argument("--updater-exe", required=True)
    p.add_argument("--final-updater-exe", required=True)
    p.add_argument("--exact-evidence", required=True)
    p.add_argument("--physical-gui", required=True)
    p.add_argument("--updater-windows", required=True)
    p.add_argument("--repository-evidence", required=True)
    p.add_argument("--software-release-evidence", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    repo = load(args.repository_evidence)
    release = load(args.software_release_evidence)
    exact = load(args.exact_evidence)
    gui = load(args.physical_gui)
    updater_windows = load(args.updater_windows)

    main_hash = sha256(Path(args.main_exe))
    final_main_hash = sha256(Path(args.final_main_exe))
    updater_hash = sha256(Path(args.updater_exe))
    final_updater_hash = sha256(Path(args.final_updater_exe))

    checks = {
        "repository": repo.get("status"),
        "real_release": release.get("status"),
        "main_exact_hash": "PASS" if main_hash and main_hash == final_main_hash == exact.get("exe_sha256") == gui.get("exe_sha256") else "FAIL",
        "updater_exact_hash": "PASS" if updater_hash and updater_hash == final_updater_hash == updater_windows.get("updater_exe_sha256") else "FAIL",
        "physical_gui": "PASS" if main_hash and validate_gui(gui, main_hash, full_release=True) else "FAIL",
        "updater_windows": "PASS" if updater_windows.get("status") == "PASS" and updater_windows.get("same_hash") is True else "FAIL",
    }

    if repo.get("status") == "BLOCKED" or release.get("status") == "BLOCKED":
        status = "BLOCKED"
    elif any(v == "FAIL" for v in checks.values()):
        status = "FAIL"
    elif all(v == "PASS" for v in checks.values()):
        status = "PASS"
    else:
        status = "NOT VERIFIED"

    report = {
        "schema": "guoxue-final-artifact-v1",
        "status": status,
        "github_sha": (os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
        "repository": repo.get("repository"),
        "main_exe": Path(args.final_main_exe).name,
        "main_exe_sha256": final_main_hash,
        "updater_exe": Path(args.final_updater_exe).name,
        "updater_exe_sha256": final_updater_hash,
        "checks": checks,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
