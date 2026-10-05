from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SCHEMA = "rmf-independent-repository-export-v5"
SOURCE_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
PROJECT_DIR = "RealMoneyFinance"
ACCEPTANCE_WORKFLOW = ".github/workflows/real-money-finance-reauthored.yml"
EXCLUDED_PARTS = {
    "dist", "build", "evidence", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def full_sha(value: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("full 40-character commit SHA required")
    return value


def git_head(root: Path) -> str:
    return full_sha(subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip())


def assert_product_unchanged(root: Path, product_base: str) -> None:
    product_base = full_sha(product_base)
    if subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", product_base, "HEAD"],
        check=False,
    ).returncode != 0:
        raise RuntimeError("product base is not an ancestor of migration head")
    changed = subprocess.check_output(
        [
            "git", "-C", str(root), "diff", "--name-only",
            f"{product_base}..HEAD", "--", PROJECT_DIR, ACCEPTANCE_WORKFLOW,
        ],
        text=True,
    ).splitlines()
    if changed:
        raise RuntimeError(
            "migration branch changed product bytes or acceptance workflow: "
            + ", ".join(changed)
        )


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


def build_manifest(dest: Path, migration_head: str, product_base: str) -> dict:
    rows = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file()):
        rel = path.relative_to(dest).as_posix()
        if rel in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}:
            continue
        rows.append({
            "path": rel,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    return {
        "schema": SCHEMA,
        "source_repository": SOURCE_REPOSITORY,
        "migration_head_commit": full_sha(migration_head),
        "product_base_commit": full_sha(product_base),
        "product_tree_identity": "BYTE_IDENTICAL_TO_PRODUCT_BASE",
        "project_dir": PROJECT_DIR,
        "acceptance_workflow": ACCEPTANCE_WORKFLOW,
        "repository_independence_status": "NOT VERIFIED",
        "real_release_n_to_n_plus_1": "NOT VERIFIED",
        "final_gate": "FAIL",
        "files": rows,
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
        "acceptance_workflow": manifest.get("acceptance_workflow") == ACCEPTANCE_WORKFLOW,
        "product_tree_identity": manifest.get("product_tree_identity") == "BYTE_IDENTICAL_TO_PRODUCT_BASE",
        "repository_not_claimed_independent": manifest.get("repository_independence_status") == "NOT VERIFIED",
        "release_not_claimed": manifest.get("real_release_n_to_n_plus_1") == "NOT VERIFIED",
        "final_not_claimed": manifest.get("final_gate") == "FAIL",
    }
    try:
        full_sha(manifest.get("migration_head_commit"))
        full_sha(manifest.get("product_base_commit"))
        checks["commit_identities"] = True
    except Exception:
        checks["commit_identities"] = False

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
        path.relative_to(dest).as_posix()
        for path in dest.rglob("*")
        if path.is_file()
        and path.name not in {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}
    }
    checks["no_unmanifested_files"] = actual == set(expected)
    checks["project_present"] = any(x.startswith(PROJECT_DIR + "/") for x in actual)
    checks["workflow_present"] = ACCEPTANCE_WORKFLOW in actual
    checks["no_generated_artifacts"] = not any(
        any(part in EXCLUDED_PARTS for part in Path(rel).parts)
        or Path(rel).suffix.lower() in EXCLUDED_SUFFIXES
        for rel in actual
    )
    checks["only_allowed_roots"] = all(
        rel.startswith(PROJECT_DIR + "/") or rel == ACCEPTANCE_WORKFLOW
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
        "migration_head_commit": manifest.get("migration_head_commit"),
        "product_base_commit": manifest.get("product_base_commit"),
        "file_count": len(expected),
        "checks": checks,
        "mismatches": mismatches,
        "manifest_sha256": sha256_file(manifest_path),
        "repository_independence": "NOT VERIFIED",
        "final_gate": "FAIL",
    }


def export(root: Path, dest: Path, product_base: str) -> dict:
    root = root.resolve()
    dest = dest.resolve()
    if dest == root or root in dest.parents:
        raise ValueError("destination must be outside source repository")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("destination must be empty")
    dest.mkdir(parents=True, exist_ok=True)

    assert_product_unchanged(root, product_base)
    migration_head = git_head(root)
    for rel in safe_project_files(root):
        copy_checked(root, dest, rel)
    copy_checked(root, dest, Path(ACCEPTANCE_WORKFLOW))

    manifest = build_manifest(dest, migration_head, product_base)
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
    parser.add_argument("--product-base")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        proof = verify(args.destination)
    else:
        if not args.product_base:
            raise ValueError("--product-base is required for export")
        proof = export(Path(__file__).resolve().parents[2], args.destination, args.product_base)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0 if proof.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
