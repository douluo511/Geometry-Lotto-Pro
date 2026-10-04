from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SCHEMA = "rmf-independent-repository-export-v1"
SOURCE_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
PROJECT_DIR = "RealMoneyFinance"
WORKFLOW = ".github/workflows/real-money-finance-reauthored.yml"
EXCLUDED_PARTS = {
    "dist", "build", "evidence", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_commit(root: Path) -> str:
    env = str(os.environ.get("GITHUB_SHA") or "").strip().lower()
    if len(env) == 40 and all(c in "0123456789abcdef" for c in env):
        return env
    value = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip().lower()
    if len(value) != 40 or not all(c in "0123456789abcdef" for c in value):
        raise RuntimeError("source commit SHA unavailable")
    return value


def safe_project_files(root: Path):
    project = root / PROJECT_DIR
    if not project.is_dir():
        raise FileNotFoundError(PROJECT_DIR)
    for path in sorted(p for p in project.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield rel


def copy_checked(root: Path, dest: Path, rel: Path) -> None:
    src = (root / rel).resolve()
    src.relative_to(root.resolve())
    if not src.is_file():
        raise FileNotFoundError(rel.as_posix())
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)


def build_manifest(dest: Path, commit: str) -> dict:
    files = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = path.relative_to(dest).as_posix()
        if rel in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}:
            continue
        files.append({
            "path": rel,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    return {
        "schema": SCHEMA,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "project_dir": PROJECT_DIR,
        "workflow": WORKFLOW,
        "repository_independence_status": "NOT VERIFIED",
        "destination_requirement": "dedicated independent repository; exact repository name is not frozen by this export",
        "layout": "RealMoneyFinance source plus exact acceptance workflow; generated artifacts excluded",
        "files": files,
    }


def verify(dest: Path) -> dict:
    manifest_path = dest / "MIGRATION_MANIFEST.json"
    if not manifest_path.is_file():
        return {"status": "FAIL", "error": "manifest missing"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = {
        "schema": manifest.get("schema") == SCHEMA,
        "source_repository": manifest.get("source_repository") == SOURCE_REPOSITORY,
        "project_dir": manifest.get("project_dir") == PROJECT_DIR,
        "workflow": manifest.get("workflow") == WORKFLOW,
        "repository_not_claimed_independent": manifest.get("repository_independence_status") == "NOT VERIFIED",
        "source_commit": isinstance(manifest.get("source_commit"), str)
            and len(manifest["source_commit"]) == 40
            and all(c in "0123456789abcdef" for c in manifest["source_commit"]),
    }
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        return {"status": "FAIL", "checks": checks, "error": "empty file manifest"}

    expected = {}
    for row in rows:
        if not isinstance(row, dict):
            return {"status": "FAIL", "checks": checks, "error": "invalid manifest row"}
        rel = str(row.get("path") or "")
        path = (dest / rel).resolve()
        try:
            path.relative_to(dest.resolve())
        except ValueError:
            return {"status": "FAIL", "checks": checks, "error": "manifest path escape"}
        expected[rel] = row

    actual = {
        p.relative_to(dest).as_posix()
        for p in dest.rglob("*")
        if p.is_file() and p.name not in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}
    }
    checks["no_unmanifested_files"] = actual == set(expected)
    checks["project_present"] = any(x.startswith(PROJECT_DIR + "/") for x in actual)
    checks["workflow_present"] = WORKFLOW in actual
    checks["no_generated_artifacts"] = not any(
        any(part in EXCLUDED_PARTS for part in Path(rel).parts)
        or Path(rel).suffix.lower() in EXCLUDED_SUFFIXES
        for rel in actual
    )
    checks["only_allowed_roots"] = all(
        rel.startswith(PROJECT_DIR + "/") or rel == WORKFLOW
        for rel in actual
    )

    mismatches = []
    for rel, row in expected.items():
        path = dest / rel
        if not path.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        got_hash = sha256_file(path)
        got_size = path.stat().st_size
        if got_hash != row.get("sha256") or got_size != row.get("bytes"):
            mismatches.append({
                "path": rel,
                "expected_sha256": row.get("sha256"),
                "actual_sha256": got_hash,
                "expected_bytes": row.get("bytes"),
                "actual_bytes": got_size,
            })
    checks["all_hashes_match"] = not mismatches
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "status": status,
        "schema": SCHEMA,
        "source_commit": manifest.get("source_commit"),
        "file_count": len(expected),
        "checks": checks,
        "mismatches": mismatches,
        "manifest_sha256": sha256_file(manifest_path),
        "repository_independence": "NOT VERIFIED",
    }


def export(root: Path, dest: Path, commit: str | None = None) -> dict:
    root = root.resolve()
    dest = dest.resolve()
    if dest == root or root in dest.parents:
        raise ValueError("destination must be outside source repository")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("destination must be empty")
    dest.mkdir(parents=True, exist_ok=True)

    for rel in safe_project_files(root):
        copy_checked(root, dest, rel)
    copy_checked(root, dest, Path(WORKFLOW))

    commit = (commit or source_commit(root)).lower()
    if len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        raise ValueError("source commit must be full SHA")
    manifest = build_manifest(dest, commit)
    (dest / "MIGRATION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (dest / "MIGRATION_SHA256SUMS.txt").write_text(
        "".join(f'{row["sha256"]}  {row["path"]}\n' for row in manifest["files"]),
        encoding="utf-8",
    )
    proof = verify(dest)
    if proof["status"] != "PASS":
        raise RuntimeError(proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        proof = verify(args.destination)
    else:
        proof = export(Path(__file__).resolve().parents[2], args.destination, args.source_commit)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0 if proof.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
