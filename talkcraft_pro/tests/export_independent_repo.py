from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SCHEMA = "talkcraft-independent-repository-export-v1"
SOURCE_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
PROJECT_DIR = "talkcraft_pro"
SUPPORT_FILES = [".github/workflows/talkcraft-pro-windows.yml"]
EXCLUDED_PARTS = {"dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"}
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
    value = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip().lower()
    if len(value) != 40 or not all(c in "0123456789abcdef" for c in value):
        raise RuntimeError("source commit SHA unavailable")
    return value

def project_files(root: Path):
    project = root / PROJECT_DIR
    if not project.is_dir():
        raise FileNotFoundError(PROJECT_DIR)
    for path in sorted(p for p in project.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix.lower() in EXCLUDED_SUFFIXES:
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

def manifest_for(dest: Path, commit: str) -> dict:
    rows = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = path.relative_to(dest).as_posix()
        if rel in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}:
            continue
        rows.append({"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {
        "schema": SCHEMA,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "project_dir": PROJECT_DIR,
        "support_files": SUPPORT_FILES,
        "repository_independence_status": "NOT VERIFIED",
        "files": rows,
    }

def verify(dest: Path) -> dict:
    mp = dest / "MIGRATION_MANIFEST.json"
    if not mp.is_file():
        return {"status": "FAIL", "error": "manifest missing"}
    m = json.loads(mp.read_text(encoding="utf-8"))
    checks = {
        "schema": m.get("schema") == SCHEMA,
        "source_repository": m.get("source_repository") == SOURCE_REPOSITORY,
        "project_dir": m.get("project_dir") == PROJECT_DIR,
        "support_files": m.get("support_files") == SUPPORT_FILES,
        "repository_not_claimed_independent": m.get("repository_independence_status") == "NOT VERIFIED",
        "source_commit": isinstance(m.get("source_commit"), str) and len(m["source_commit"]) == 40 and all(c in "0123456789abcdef" for c in m["source_commit"]),
    }
    rows = m.get("files")
    if not isinstance(rows, list) or not rows:
        return {"status": "FAIL", "checks": checks, "error": "empty file manifest"}
    expected = {str(row.get("path") or ""): row for row in rows if isinstance(row, dict)}
    if len(expected) != len(rows):
        return {"status": "FAIL", "checks": checks, "error": "invalid/duplicate manifest row"}
    actual = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and p.name not in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}}
    checks["no_unmanifested_files"] = actual == set(expected)
    checks["project_present"] = any(x.startswith(PROJECT_DIR + "/") for x in actual)
    checks["support_present"] = all(x in actual for x in SUPPORT_FILES)
    checks["only_allowed_roots"] = all(x.startswith(PROJECT_DIR + "/") or x in SUPPORT_FILES for x in actual)
    mismatches = []
    for rel, row in expected.items():
        path = (dest / rel).resolve()
        try:
            path.relative_to(dest.resolve())
        except ValueError:
            mismatches.append({"path": rel, "reason": "path escape"})
            continue
        if not path.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        if sha256_file(path) != row.get("sha256") or path.stat().st_size != row.get("bytes"):
            mismatches.append({"path": rel, "reason": "hash-or-size"})
    checks["all_hashes_match"] = not mismatches
    status = "PASS" if all(checks.values()) else "FAIL"
    return {"status": status, "schema": SCHEMA, "source_commit": m.get("source_commit"), "file_count": len(expected), "checks": checks, "mismatches": mismatches, "manifest_sha256": sha256_file(mp), "repository_independence": "NOT VERIFIED"}

def export(root: Path, dest: Path, commit: str | None) -> dict:
    root, dest = root.resolve(), dest.resolve()
    if dest == root or root in dest.parents:
        raise ValueError("destination must be outside source repository")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("destination must be empty")
    dest.mkdir(parents=True, exist_ok=True)
    for rel in project_files(root):
        copy_checked(root, dest, rel)
    for item in SUPPORT_FILES:
        copy_checked(root, dest, Path(item))
    commit = (commit or source_commit(root)).lower()
    if len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        raise ValueError("source commit must be full SHA")
    m = manifest_for(dest, commit)
    (dest / "MIGRATION_MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (dest / "MIGRATION_SHA256SUMS.txt").write_text("".join(f'{r["sha256"]}  {r["path"]}\n' for r in m["files"]), encoding="utf-8")
    proof = verify(dest)
    if proof["status"] != "PASS":
        raise RuntimeError(proof)
    return proof

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--destination", required=True, type=Path)
    p.add_argument("--source-commit")
    p.add_argument("--verify-only", action="store_true")
    a = p.parse_args()
    proof = verify(a.destination) if a.verify_only else export(Path(__file__).resolve().parents[2], a.destination, a.source_commit)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0 if proof.get("status") == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
