from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from gate_common import current_report, gate_status, run_identity
from physical_gui_evidence import validate_physical


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"status": "FAIL"}
    except Exception as exc:
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def validate(reports, hashes, source_sha):
    repo, release, exact, gui, updater = (reports[key] for key in ("repository", "release", "exact", "gui", "updater"))
    main_hash, final_main_hash, updater_hash, final_updater_hash = hashes
    accepted = release.get("accepted") or {}
    checks = {
        "current_source_and_run": "PASS" if all(current_report(row, source_sha) for row in reports.values()) else "FAIL",
        "repository": gate_status(repo, source_sha),
        "real_release": gate_status(release, source_sha),
        "main_exact_hash": "PASS" if main_hash and main_hash == final_main_hash == exact.get("exe_sha256") == gui.get("exe_sha256") else "FAIL",
        "updater_exact_hash": "PASS" if updater_hash and updater_hash == final_updater_hash == updater.get("updater_exe_sha256") else "FAIL",
        "physical_gui": "PASS" if validate_physical(gui, source_sha) else "FAIL",
        "updater_windows": "PASS" if updater.get("status") == "PASS" and updater.get("same_hash") is True and updater.get("exit_code") == 0 and (updater.get("self_test") or {}).get("status") == "PASS" else "FAIL",
    }
    if release.get("status") == "BLOCKED" and current_report(release, source_sha):
        checks["accepted_release_hash"] = "BLOCKED"
        checks["configured_gui_update"] = "BLOCKED" if validate_physical(gui, source_sha) else "FAIL"
    else:
        checks["configured_gui_update"] = "PASS" if validate_physical(gui, source_sha, require_configured=True) else "FAIL"
        checks["accepted_release_hash"] = "PASS" if (
            main_hash and main_hash == accepted.get("new_exe_sha256")
            and updater_hash == accepted.get("updater_exe_sha256")
            and repo.get("repository") == release.get("repository")
        ) else "FAIL"
    # Internal failures take precedence over external blockers.
    status = "FAIL" if "FAIL" in checks.values() else "BLOCKED" if "BLOCKED" in checks.values() else "PASS" if all(value == "PASS" for value in checks.values()) else "NOT VERIFIED"
    return {"status": status, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("main-exe", "final-main-exe", "updater-exe", "final-updater-exe",
                 "exact-evidence", "physical-gui", "updater-windows", "repository-evidence",
                 "software-release-evidence", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    source_sha = os.environ.get("ENGLISH_ROOT_SOURCE_SHA") or os.environ.get("GITHUB_SHA")
    reports = {"repository": load(args.repository_evidence), "release": load(args.software_release_evidence),
               "exact": load(args.exact_evidence), "gui": load(args.physical_gui), "updater": load(args.updater_windows)}
    hashes = [sha256(Path(path)) for path in (args.main_exe, args.final_main_exe, args.updater_exe, args.final_updater_exe)]
    result = {"schema": "english-root-final-artifact-v1", "github_sha": source_sha, **run_identity(),
              "repository": reports["repository"].get("repository"),
              "main_exe_sha256": hashes[1], "updater_exe_sha256": hashes[3],
              **validate(reports, hashes, source_sha)}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
