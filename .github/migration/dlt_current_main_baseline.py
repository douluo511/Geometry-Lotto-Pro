#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

CURRENT_VERSION = "2.1.2"
BASELINE_VERSION = "2.1.1"
CURRENT_MAIN = "c2b0db6876d2aae874f8cf4d08f52455c8eaf152"
TARGET_REPOSITORY = "douluo511/Geometry-Lotto-Pro-DLT"
EXPECTED_FILE_COUNT = 38
CONSTANTS_PATH = Path("DLT/src/glp/constants.py")
CURRENT_BYTES = f'APP_VERSION = "{CURRENT_VERSION}"'.encode("utf-8")
BASELINE_BYTES = f'APP_VERSION = "{BASELINE_VERSION}"'.encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def payload_files(root: Path) -> list[Path]:
    skip = {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt", "BASELINE_MANIFEST.json", "BASELINE_SHA256SUMS.txt"}
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.name not in skip),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def snapshot(root: Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for p in payload_files(root):
        rel = p.relative_to(root).as_posix()
        out[rel] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected-export-commit", required=True)
    ap.add_argument("--current-seed", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    current = Path(args.current_seed).resolve()
    out = Path(args.out).resolve()
    if not current.is_dir():
        raise SystemExit("current seed directory missing")

    migration_manifest = current / "MIGRATION_MANIFEST.json"
    migration_sums = current / "MIGRATION_SHA256SUMS.txt"
    if not migration_manifest.is_file() or not migration_sums.is_file():
        raise SystemExit("current seed migration evidence missing")

    source = json.loads(migration_manifest.read_text(encoding="utf-8"))
    if source.get("schema") != "dlt-independent-export-v4":
        raise SystemExit("current seed schema mismatch")
    if source.get("source_commit") != CURRENT_MAIN:
        raise SystemExit("current seed is not bound to current main")
    if source.get("target_repository") != TARGET_REPOSITORY:
        raise SystemExit("current seed target mismatch")
    if source.get("layout") != "preserve-dlt-root":
        raise SystemExit("current seed layout mismatch")
    if source.get("prospective_research_authority") != "EXCLUDED_NOT_ON_CURRENT_MAIN":
        raise SystemExit("current seed prospective authority mismatch")

    # FAIL-CLOSED: prevent a stale or tampered seed from earning a fresh baseline PASS.
    if source.get("candidate_head") != CURRENT_MAIN:
        raise SystemExit("seed candidate identity is stale")
    if (len(args.expected_export_commit) != 40
            or any(c not in "0123456789abcdef" for c in args.expected_export_commit)):
        raise SystemExit("expected exact export commit must be lowercase full SHA")
    if source.get("export_commit") != args.expected_export_commit:
        raise SystemExit("seed export authority is stale")
    if source.get("file_count") != EXPECTED_FILE_COUNT:
        raise SystemExit("seed file count differs from current verified product")
    rows = source.get("files", [])
    if len(rows) != EXPECTED_FILE_COUNT:
        raise SystemExit("seed manifest row count differs from declared count")
    actual_sum_lines = migration_sums.read_text(encoding="utf-8").splitlines()
    expected_sum_lines = [f'{row["sha256"]}  {row["path"]}' for row in rows]
    if actual_sum_lines != expected_sum_lines:
        raise SystemExit("seed checksum lines differ from the manifest")
    for row in rows:
        rel = str(row["path"])
        if rel.startswith("/") or chr(92) in rel or ".." in Path(rel).parts or ":" in rel or rel.startswith(".git/"):
            raise SystemExit(f"unsafe seed manifest path: {rel}")
        payload = current / rel
        if not payload.is_file():
            raise SystemExit(f"seed payload missing: {rel}")
        if payload.stat().st_size != row["bytes"] or sha256_file(payload) != row["sha256"]:
            raise SystemExit(f"seed payload hash/size mismatch: {rel}")

    current_snapshot = snapshot(current)
    manifest_paths = {str(row["path"]) for row in source.get("files", [])}
    if set(current_snapshot) != manifest_paths:
        raise SystemExit("current seed payload differs from migration manifest")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(current, out)
    for name in ("MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"):
        (out / name).unlink()

    constants = out / CONSTANTS_PATH
    if not constants.is_file():
        raise SystemExit("constants.py missing")
    before = constants.read_bytes()
    if before.count(CURRENT_BYTES) != 1:
        raise SystemExit("expected current APP_VERSION byte sequence exactly once")
    if BASELINE_BYTES in before:
        raise SystemExit("baseline version already present")
    expected = before.replace(CURRENT_BYTES, BASELINE_BYTES, 1)
    constants.write_bytes(expected)
    if constants.read_bytes() != expected:
        raise SystemExit("byte-exact version replacement failed")

    baseline_snapshot = snapshot(out)
    if set(current_snapshot) != set(baseline_snapshot):
        raise SystemExit("baseline file set changed")

    changed = sorted(
        path for path in current_snapshot
        if current_snapshot[path] != baseline_snapshot[path]
    )
    if changed != [CONSTANTS_PATH.as_posix()]:
        raise SystemExit(f"unexpected controlled changes: {changed}")

    if constants.read_bytes() != before.replace(CURRENT_BYTES, BASELINE_BYTES, 1):
        raise SystemExit("constants.py differs beyond controlled replacement")

    rows = [
        {"path": path, **baseline_snapshot[path]}
        for path in sorted(baseline_snapshot)
    ]
    manifest = {
        "schema": "dlt-current-main-release-baseline-v2",
        "purpose": "release-n-to-n-plus-1-acceptance-only",
        "source_repository": "douluo511/Geometry-Lotto-Pro",
        "source_product_commit": CURRENT_MAIN,
        "target_repository": TARGET_REPOSITORY,
        "current_version": CURRENT_VERSION,
        "baseline_version": BASELINE_VERSION,
        "controlled_changes": [CONSTANTS_PATH.as_posix()],
        "required_workflows": [".github/workflows/dlt-windows-build-acceptance.yml"],
        "prospective_research_authority": "EXCLUDED_NOT_ON_CURRENT_MAIN",
        "file_count": len(rows),
        "repository_independence": "NOT VERIFIED",
        "baseline_release_state": "NOT PUBLISHED",
        "final_eligible": False,
        "source_migration_manifest_sha256": sha256_file(migration_manifest),
        "source_migration_sums_sha256": sha256_file(migration_sums),
        "files": rows,
    }

    manifest_path = out / "BASELINE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sums_path = out / "BASELINE_SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f'{row["sha256"]}  {row["path"]}\n' for row in rows),
        encoding="utf-8",
    )

    print(json.dumps({
        "schema": manifest["schema"],
        "source_product_commit": CURRENT_MAIN,
        "baseline_version": BASELINE_VERSION,
        "current_version": CURRENT_VERSION,
        "controlled_changes": manifest["controlled_changes"],
        "file_count": len(rows),
        "manifest_sha256": sha256_file(manifest_path),
        "sums_sha256": sha256_file(sums_path),
        "final_eligible": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
