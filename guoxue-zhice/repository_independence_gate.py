from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

SHARED_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
REQUIRED_TOP_LEVEL = {".github", "guoxue-zhice"}
ALLOWED_TOP_LEVEL = REQUIRED_TOP_LEVEL | {"README.md", "LICENSE", "LICENSE.txt", ".gitignore"}
REQUIRED_PATHS = {
    ".github/workflows/guoxue-zhice-windows.yml",
    "guoxue-zhice/ENGINEERING_SPEC.md",
    "guoxue-zhice/BUSINESS_SPEC.md",
    "guoxue-zhice/app.py",
    "guoxue-zhice/service.py",
    "guoxue-zhice/core.py",
    "guoxue-zhice/net_client.py",
    "guoxue-zhice/software_update.py",
    "guoxue-zhice/updater.py",
    "guoxue-zhice/updater_entry.py",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    root = Path(args.repo_root).resolve()
    report = {
        "schema": "guoxue-repository-independence-v1",
        "github_sha": (os.environ.get("GUOXUE_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
        "repository": args.repository,
    }
    try:
        proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=root, text=True, capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git ls-tree failed")
        paths = {x.strip().replace("\\", "/") for x in proc.stdout.splitlines() if x.strip()}
        top = {x.split("/", 1)[0] for x in paths}
        missing = sorted(REQUIRED_PATHS - paths)
        unexpected = sorted(top - ALLOWED_TOP_LEVEL)
        checks = {
            "dedicated_repository": {
                "status": "PASS" if args.repository != SHARED_REPOSITORY else "BLOCKED",
                "shared_repository": SHARED_REPOSITORY,
            },
            "top_level_inventory": {
                "status": "PASS" if not (REQUIRED_TOP_LEVEL - top) and not unexpected else "FAIL",
                "top_level": sorted(top),
                "unexpected": unexpected,
            },
            "required_paths": {
                "status": "PASS" if not missing else "FAIL",
                "missing": missing,
            },
        }
        if checks["dedicated_repository"]["status"] == "BLOCKED":
            status = "BLOCKED"
        elif any(v["status"] == "FAIL" for v in checks.values()):
            status = "FAIL"
        else:
            status = "PASS"
        report.update({"status": status, "checks": checks})
    except Exception as exc:
        report.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
