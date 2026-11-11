from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

SCHEMA = "portfolio-independent-repo-export-v1"
SOURCE_REPOSITORY = "douluo511/Geometry-Lotto-Pro"

PROJECTS = {
    "dlt": {
        "project_dir": "DLT",
        "workflow": ".github/workflows/dlt-windows-build-acceptance.yml",
        "target_repository": "douluo511/Geometry-Lotto-Pro-DLT",
    },
    "english-root": {
        "project_dir": "english-root-intelligence",
        "workflow": ".github/workflows/english-root-intelligence-windows.yml",
        "target_repository": "douluo511/English-Root-Intelligence",
    },
    "guoxue-zhice": {
        "project_dir": "guoxue-zhice",
        "workflow": ".github/workflows/guoxue-zhice-windows.yml",
        "target_repository": "douluo511/Guoxue-Zhice",
    },
    "head-intelligence": {
        "project_dir": "head_intelligence",
        "workflow": ".github/workflows/head-intelligence-windows.yml",
        "target_repository": "douluo511/Head-Intelligence",
    },
    "investment-finance": {
        "project_dir": "investment_finance_pro",
        "workflow": ".github/workflows/investment-finance-pro-build.yml",
        "target_repository": "douluo511/Investment-Finance-Pro",
    },
    "psychology-insight": {
        "project_dir": "psychology_insight_pro",
        "workflow": ".github/workflows/psychology-insight-pro-windows.yml",
        "target_repository": "douluo511/Psychology-Insight-Pro",
    },
}

KNOWN_PROJECT_DIRS = {
    "SSQ",
    "DLT",
    "english-root-intelligence",
    "guoxue-zhice",
    "head_intelligence",
    "investment_finance_pro",
    "psychology_insight_pro",
    "Human-Nature-Pro",
    "TalkCraft-Pro",
    "Happy8",
}
EXCLUDED_PARTS = {
    "dist",
    "build",
    "evidence",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
SCRIPT_PATTERN = re.compile(r"\.github/scripts/[A-Za-z0-9_.-]+")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_commit(root: Path) -> str:
    env_sha = str(os.environ.get("GITHUB_SHA") or "").strip()
    if len(env_sha) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in env_sha):
        return env_sha.lower()
    try:
        value = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        value = ""
    if len(value) != 40 or not all(ch in "0123456789abcdefABCDEF" for ch in value):
        raise RuntimeError("source commit SHA is unavailable")
    return value.lower()


def _safe_files(root: Path, project_dir: str) -> Iterable[Path]:
    project = root / project_dir
    if not project.is_dir():
        raise FileNotFoundError(f"project directory missing: {project_dir}")
    for path in sorted(p for p in project.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield rel


def _copy(root: Path, destination: Path, rel: Path) -> None:
    source = (root / rel).resolve()
    try:
        source.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"source escaped repository root: {rel}") from exc
    if not source.is_file():
        raise FileNotFoundError(f"required export file missing: {rel}")
    target = destination / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _workflow_scripts(root: Path, workflow: Path) -> list[Path]:
    workflow_path = root / workflow
    if not workflow_path.is_file():
        raise FileNotFoundError(f"workflow missing: {workflow}")
    text = workflow_path.read_text(encoding="utf-8")
    return sorted({Path(match) for match in SCRIPT_PATTERN.findall(text)})


def _manifest_for(
    destination: Path,
    *,
    project_key: str,
    project_dir: str,
    workflow: str,
    target_repository: str,
    source_commit: str,
    required_scripts: list[str],
) -> dict:
    files = []
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        rel = path.relative_to(destination).as_posix()
        if rel in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}:
            continue
        files.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "schema": SCHEMA,
        "source_repository": SOURCE_REPOSITORY,
        "project_key": project_key,
        "project_dir": project_dir,
        "workflow": workflow,
        "target_repository": target_repository,
        "source_commit": source_commit,
        "required_scripts": required_scripts,
        "layout": "selected project only plus exact workflow dependencies and governance files",
        "files": files,
    }


def export_repository(
    root: Path,
    destination: Path,
    project_key: str,
    source_commit: str | None = None,
) -> dict:
    if project_key not in PROJECTS:
        raise ValueError(f"unknown project: {project_key}")
    config = PROJECTS[project_key]
    project_dir = str(config["project_dir"])
    workflow = Path(str(config["workflow"]))
    target_repository = str(config["target_repository"])

    root = root.resolve()
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("destination must be outside the source repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)

    for rel in _safe_files(root, project_dir):
        _copy(root, destination, rel)

    _copy(root, destination, workflow)
    scripts = _workflow_scripts(root, workflow)
    for rel in scripts:
        _copy(root, destination, rel)

    for shared in (Path(".gitignore"), Path("PORTFOLIO_GOVERNANCE.md")):
        if (root / shared).is_file():
            _copy(root, destination, shared)

    project = root / project_dir
    for readme_name in ("README.md", "README_GITHUB.md", "README_GITHUB_VALIDATION.md"):
        candidate = project / readme_name
        if candidate.is_file():
            (destination / "README.md").write_bytes(candidate.read_bytes())
            break

    commit = source_commit or _source_commit(root)
    commit = commit.lower()
    if len(commit) != 40 or not all(ch in "0123456789abcdef" for ch in commit):
        raise ValueError("source_commit must be a full 40-character SHA")

    manifest = _manifest_for(
        destination,
        project_key=project_key,
        project_dir=project_dir,
        workflow=workflow.as_posix(),
        target_repository=target_repository,
        source_commit=commit,
        required_scripts=[p.as_posix() for p in scripts],
    )
    manifest_path = destination / "MIGRATION_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "MIGRATION_SHA256SUMS.txt").write_text(
        "".join(f'{row["sha256"]}  {row["path"]}\n' for row in manifest["files"]),
        encoding="utf-8",
    )

    proof = verify_export(destination)
    if proof.get("status") != "PASS":
        raise RuntimeError(f"export verification failed: {proof}")
    return proof


def verify_export(destination: Path) -> dict:
    destination = destination.resolve()
    manifest_path = destination / "MIGRATION_MANIFEST.json"
    if not manifest_path.is_file():
        return {"status": "FAIL", "error": "MIGRATION_MANIFEST.json missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "error": f"invalid manifest: {exc}"}

    project_key = str(manifest.get("project_key") or "")
    config = PROJECTS.get(project_key)
    checks = {
        "schema": manifest.get("schema") == SCHEMA,
        "source_repository": manifest.get("source_repository") == SOURCE_REPOSITORY,
        "known_project": config is not None,
    }
    if config is None:
        return {"status": "FAIL", "checks": checks, "error": "unknown project in manifest"}

    project_dir = str(config["project_dir"])
    expected_workflow = str(config["workflow"])
    expected_target = str(config["target_repository"])
    checks.update(
        {
            "project_dir": manifest.get("project_dir") == project_dir,
            "workflow": manifest.get("workflow") == expected_workflow,
            "target_repository": manifest.get("target_repository") == expected_target,
            "source_commit": isinstance(manifest.get("source_commit"), str)
            and len(manifest["source_commit"]) == 40
            and all(ch in "0123456789abcdef" for ch in manifest["source_commit"]),
        }
    )

    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        checks["file_manifest"] = False
        return {"status": "FAIL", "checks": checks, "error": "empty file manifest"}

    expected: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            checks["file_manifest"] = False
            return {"status": "FAIL", "checks": checks, "error": "invalid manifest row"}
        rel = str(row.get("path") or "")
        path = (destination / rel).resolve()
        try:
            path.relative_to(destination)
        except ValueError:
            checks["file_manifest"] = False
            return {"status": "FAIL", "checks": checks, "error": "manifest path escape"}
        expected[rel] = row

    actual_paths = {
        p.relative_to(destination).as_posix()
        for p in destination.rglob("*")
        if p.is_file() and p.name not in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}
    }
    checks["no_unmanifested_files"] = actual_paths == set(expected)
    checks["selected_project_present"] = any(rel.startswith(project_dir + "/") for rel in actual_paths)
    checks["required_workflow"] = expected_workflow in actual_paths

    required_scripts = manifest.get("required_scripts")
    checks["required_scripts_schema"] = isinstance(required_scripts, list)
    checks["required_scripts_present"] = isinstance(required_scripts, list) and all(
        str(rel) in actual_paths for rel in required_scripts
    )

    forbidden = KNOWN_PROJECT_DIRS - {project_dir}
    checks["no_other_projects"] = not any(
        rel.split("/", 1)[0] in forbidden for rel in actual_paths
    )
    checks["no_generated_artifacts"] = not any(
        any(part in EXCLUDED_PARTS for part in Path(rel).parts)
        or Path(rel).suffix.lower() in EXCLUDED_SUFFIXES
        for rel in actual_paths
    )

    mismatches = []
    for rel, row in expected.items():
        path = destination / rel
        if not path.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        digest = sha256_file(path)
        size = path.stat().st_size
        if digest != row.get("sha256") or size != row.get("bytes"):
            mismatches.append(
                {
                    "path": rel,
                    "expected_sha256": row.get("sha256"),
                    "actual_sha256": digest,
                    "expected_bytes": row.get("bytes"),
                    "actual_bytes": size,
                }
            )
    checks["all_hashes_match"] = not mismatches

    status = "PASS" if checks and all(checks.values()) else "FAIL"
    return {
        "status": status,
        "schema": SCHEMA,
        "project_key": project_key,
        "target_repository": expected_target,
        "source_commit": manifest.get("source_commit"),
        "file_count": len(expected),
        "checks": checks,
        "mismatches": mismatches,
        "manifest_sha256": sha256_file(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=sorted(PROJECTS), required=False)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        proof = verify_export(args.destination)
    else:
        if not args.project:
            parser.error("--project is required unless --verify-only is used")
        root = Path(__file__).resolve().parents[1]
        proof = export_repository(root, args.destination, args.project, args.source_commit)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0 if proof.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
