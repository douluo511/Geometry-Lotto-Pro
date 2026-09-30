from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

SCHEMA = "ssq-independent-repo-export-v1"
SOURCE_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
TARGET_REPOSITORY = "douluo511/Geometry-Lotto-Pro-SSQ"

COPY_FILES = (
    Path(".github/workflows/ssq-windows-build-acceptance.yml"),
    Path(".github/scripts/ssq_physical_gui_click_smoke.ps1"),
    Path(".gitignore"),
    Path("PORTFOLIO_GOVERNANCE.md"),
)

EXCLUDED_PARTS = {
    "dist", "evidence", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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


def _safe_ssq_files(root: Path) -> Iterable[Path]:
    ssq = root / "SSQ"
    if not ssq.is_dir():
        raise FileNotFoundError("SSQ project directory missing")
    for path in sorted(p for p in ssq.rglob("*") if p.is_file()):
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


def _manifest_for(destination: Path, source_commit: str) -> dict:
    files = []
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        rel = path.relative_to(destination).as_posix()
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
        "target_repository": TARGET_REPOSITORY,
        "source_commit": source_commit,
        "layout": "preserve SSQ/ plus exact GitHub workflow/script paths",
        "files": files,
    }


def export_repository(root: Path, destination: Path, source_commit: str | None = None) -> dict:
    root = root.resolve()
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("destination must be outside the source repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)

    for rel in _safe_ssq_files(root):
        _copy(root, destination, rel)
    for rel in COPY_FILES:
        _copy(root, destination, rel)

    readme_source = root / "SSQ" / "README_GITHUB.md"
    if readme_source.is_file():
        (destination / "README.md").write_bytes(readme_source.read_bytes())

    commit = source_commit or _source_commit(root)
    if len(commit) != 40 or not all(ch in "0123456789abcdef" for ch in commit.lower()):
        raise ValueError("source_commit must be a full 40-character SHA")
    commit = commit.lower()

    manifest = _manifest_for(destination, commit)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    (destination / "MIGRATION_MANIFEST.json").write_bytes(manifest_bytes)
    sums = "".join(f'{row["sha256"]}  {row["path"]}\n' for row in manifest["files"])
    (destination / "MIGRATION_SHA256SUMS.txt").write_text(sums, encoding="utf-8")

    proof = verify_export(destination)
    if proof["status"] != "PASS":
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

    checks = {
        "schema": manifest.get("schema") == SCHEMA,
        "source_repository": manifest.get("source_repository") == SOURCE_REPOSITORY,
        "target_repository": manifest.get("target_repository") == TARGET_REPOSITORY,
        "source_commit": isinstance(manifest.get("source_commit"), str)
        and len(manifest["source_commit"]) == 40
        and all(ch in "0123456789abcdef" for ch in manifest["source_commit"]),
    }
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        checks["file_manifest"] = False
        return {"status": "FAIL", "checks": checks}

    expected = {}
    for row in rows:
        if not isinstance(row, dict):
            checks["file_manifest"] = False
            return {"status": "FAIL", "checks": checks}
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
    checks["no_other_projects"] = not any(
        rel.split("/", 1)[0] in {
            "DLT", "english-root-intelligence", "guoxue-zhice",
            "head_intelligence", "investment_finance_pro", "psychology_insight_pro",
            "Human-Nature-Pro", "TalkCraft-Pro", "Happy8",
        }
        for rel in actual_paths
    )
    checks["required_workflow"] = ".github/workflows/ssq-windows-build-acceptance.yml" in actual_paths
    checks["required_gui_script"] = ".github/scripts/ssq_physical_gui_click_smoke.ps1" in actual_paths
    checks["ssq_project"] = any(rel.startswith("SSQ/") for rel in actual_paths)

    mismatches = []
    for rel, row in expected.items():
        path = destination / rel
        if not path.is_file():
            mismatches.append({"path": rel, "reason": "missing"})
            continue
        digest = sha256_file(path)
        size = path.stat().st_size
        if digest != row.get("sha256") or size != row.get("bytes"):
            mismatches.append({
                "path": rel,
                "expected_sha256": row.get("sha256"),
                "actual_sha256": digest,
                "expected_bytes": row.get("bytes"),
                "actual_bytes": size,
            })
    checks["all_hashes_match"] = not mismatches
    status = "PASS" if checks and all(checks.values()) else "FAIL"
    return {
        "status": status,
        "schema": SCHEMA,
        "target_repository": TARGET_REPOSITORY,
        "source_commit": manifest.get("source_commit"),
        "file_count": len(expected),
        "checks": checks,
        "mismatches": mismatches,
        "manifest_sha256": sha256_file(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--source-commit")
    args = parser.parse_args()

    if args.verify_only:
        proof = verify_export(args.destination)
    else:
        root = Path(__file__).resolve().parents[2]
        proof = export_repository(root, args.destination, args.source_commit)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0 if proof.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
