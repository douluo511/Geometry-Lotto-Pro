#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "DLT"
TARGET = "douluo511/Geometry-Lotto-Pro-DLT"
WORKFLOWS = (
    ROOT / ".github/workflows/dlt-windows-build-acceptance.yml",
    ROOT / ".github/workflows/dlt-rho-zero-contract.yml",
)
EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "runtime",
    "dist",
    "build",
    "reproducible_build",
    "artifacts",
    "evidence",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
SHARED_SCRIPT_PATTERN = re.compile(r"\.github/scripts/[A-Za-z0-9_./-]+")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def keep_project_file(path: Path) -> bool:
    rel = path.relative_to(PROJECT)
    return (
        path.is_file()
        and not any(part in EXCLUDE_PARTS for part in rel.parts)
        and path.suffix.lower() not in EXCLUDE_SUFFIXES
    )


def require_exact_sha(name: str, fallback: str = "") -> str:
    value = (os.environ.get(name) or fallback).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise SystemExit(f"{name} must be an exact 40-hex Git commit")
    return value


def collect_sources() -> list[Path]:
    if not PROJECT.is_dir():
        raise SystemExit("DLT project directory missing")
    for workflow in WORKFLOWS:
        if not workflow.is_file():
            raise SystemExit(f"required workflow missing: {workflow.relative_to(ROOT)}")

    sources = [p for p in PROJECT.rglob("*") if keep_project_file(p)]
    sources.extend(WORKFLOWS)

    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for match in sorted(set(SHARED_SCRIPT_PATTERN.findall(text))):
            path = ROOT / match
            if not path.is_file():
                raise SystemExit(f"referenced shared script missing: {match}")
            sources.append(path)

    return sorted(set(sources), key=lambda p: p.as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    export_sha = require_exact_sha("SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    candidate_sha = require_exact_sha("CANDIDATE_SHA")
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    rows: list[dict[str, object]] = []
    for src in collect_sources():
        # Preserve the monorepo DLT root so the exact workflows remain runnable
        # without rewriting working-directory/path contracts in the target repo.
        rel = src.relative_to(ROOT)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rows.append(
            {
                "path": rel.as_posix(),
                "bytes": dst.stat().st_size,
                "sha256": sha256_file(dst),
            }
        )

    manifest = {
        "schema": "dlt-independent-export-v5-rho-zero",
        "source_repository": "douluo511/Geometry-Lotto-Pro",
        "source_commit": candidate_sha,
        "candidate_head": candidate_sha,
        "export_commit": export_sha,
        "target_repository": TARGET,
        "layout": "preserve-dlt-root",
        "required_workflows": [
            ".github/workflows/dlt-windows-build-acceptance.yml",
            ".github/workflows/dlt-rho-zero-contract.yml",
        ],
        "prospective_research_authority": "EXCLUDED_NOT_ON_CURRENT_MAIN",
        "file_count": len(rows),
        "repository_independence": "NOT VERIFIED",
        "release_context": "NOT VERIFIED",
        "files": rows,
    }
    manifest_path = out / "MIGRATION_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sums_path = out / "MIGRATION_SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f'{row["sha256"]}  {row["path"]}\n' for row in rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "source_commit": candidate_sha,
                "candidate_head": candidate_sha,
                "export_commit": export_sha,
                "file_count": len(rows),
                "manifest_sha256": sha256_file(manifest_path),
                "sums_sha256": sha256_file(sums_path),
                "layout": manifest["layout"],
                "repository_independence": "NOT VERIFIED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
