from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable

SHARED_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
REQUIRED_TOP_LEVEL = {".github", "Happy8"}
ALLOWED_TOP_LEVEL = REQUIRED_TOP_LEVEL | {"README.md", "LICENSE", "LICENSE.txt", ".gitignore"}
REQUIRED_PATHS = {
    ".github/workflows/happy8-staging-recovery.yml",
    "Happy8/ARCHITECTURE_SCOPE.json",
    "Happy8/BUSINESS_ACCEPTANCE_BASELINE.json",
    "Happy8/ENGINEERING_ACCEPTANCE_BASELINE.json",
    "Happy8/staging/GeometryLottoProHappy8.spec",
    "Happy8/staging/GeometryLottoProHappy8Updater.spec",
    "Happy8/staging/requirements.txt",
}


def evaluate_repository_independence(
    *,
    repository: str,
    top_level: Iterable[str],
    paths: Iterable[str],
) -> dict:
    repository = str(repository).strip()
    top = {str(x).strip() for x in top_level if str(x).strip()}
    all_paths = {str(x).replace("\\", "/").strip("/") for x in paths if str(x).strip()}
    checks: dict[str, dict] = {}

    checks["dedicated_repository_name"] = {
        "status": "PASS" if repository and repository != SHARED_REPOSITORY else "BLOCKED",
        "repository": repository,
        "shared_repository": SHARED_REPOSITORY,
    }

    missing_top = sorted(REQUIRED_TOP_LEVEL - top)
    unexpected_top = sorted(top - ALLOWED_TOP_LEVEL)
    checks["top_level_inventory"] = {
        "status": "PASS" if not missing_top and not unexpected_top else "FAIL",
        "top_level": sorted(top),
        "missing_required": missing_top,
        "unexpected": unexpected_top,
    }

    missing_paths = sorted(REQUIRED_PATHS - all_paths)
    checks["required_project_paths"] = {
        "status": "PASS" if not missing_paths else "FAIL",
        "missing": missing_paths,
    }

    statuses = [str(x.get("status")) for x in checks.values()]
    # The shared portfolio repository is the external blocker itself.  Record
    # inventory defects, but do not misclassify the known external condition as
    # an implementation FAIL.  Once the repository is dedicated, any mixed
    # inventory becomes a real FAIL.
    if checks["dedicated_repository_name"]["status"] == "BLOCKED":
        status = "BLOCKED"
    elif "FAIL" in statuses:
        status = "FAIL"
    elif statuses and all(x == "PASS" for x in statuses):
        status = "PASS"
    else:
        status = "NOT VERIFIED"

    return {
        "schema": "happy8-repository-independence-v1",
        "status": status,
        "repository": repository,
        "checks": checks,
    }


def git_inventory(repo_root: Path) -> tuple[list[str], list[str]]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git ls-tree failed: {completed.stderr.strip()}")
    paths = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
    top = sorted({path.split("/", 1)[0] for path in paths})
    return top, paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    try:
        top, paths = git_inventory(repo_root)
        report = evaluate_repository_independence(
            repository=args.repository,
            top_level=top,
            paths=paths,
        )
    except Exception as exc:
        report = {
            "schema": "happy8-repository-independence-v1",
            "status": "FAIL",
            "repository": str(args.repository),
            "error": f"{type(exc).__name__}: {exc}",
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # BLOCKED is an expected external state on the shared portfolio repo.
    # FAIL means a purported dedicated repo violates its frozen inventory.
    return 2 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
