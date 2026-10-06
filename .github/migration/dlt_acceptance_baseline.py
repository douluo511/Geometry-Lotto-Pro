#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

CURRENT_VERSION = "2.1.2"
BASELINE_VERSION = "2.1.1"
CANDIDATE_HEAD = "289f6bf0146e5e0149940a5411943d844d8f03ea"
CONSTANTS_PATH = Path("DLT/src/glp/constants.py")
CURRENT_LINE = f'APP_VERSION = "{CURRENT_VERSION}"'
BASELINE_LINE = f'APP_VERSION = "{BASELINE_VERSION}"'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def snapshot(root: Path) -> dict[str, dict[str, int | str]]:
    rows: dict[str, dict[str, int | str]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        rows[rel] = {"size": p.stat().st_size, "sha256": sha256_file(p)}
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-seed", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    current = Path(args.current_seed).resolve()
    out = Path(args.out).resolve()
    if not current.is_dir():
        raise SystemExit("current seed directory missing")

    manifest_path = current / "MIGRATION_MANIFEST.json"
    if not manifest_path.is_file():
        raise SystemExit("current seed MIGRATION_MANIFEST.json missing")
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("schema") != "dlt-independent-export-v3":
        raise SystemExit("unexpected current seed schema")
    if source_manifest.get("candidate_head") != CANDIDATE_HEAD:
        raise SystemExit("current seed is not bound to the frozen candidate head")
    if source_manifest.get("layout") != "preserve-dlt-root":
        raise SystemExit("current seed layout is not preserve-dlt-root")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(current, out)
    (out / "MIGRATION_MANIFEST.json").unlink()

    constants = out / CONSTANTS_PATH
    if not constants.is_file():
        raise SystemExit("DLT constants.py missing from current seed")
    before = constants.read_text(encoding="utf-8")
    if before.count(CURRENT_LINE) != 1:
        raise SystemExit("current APP_VERSION declaration is not exactly one expected line")
    if BASELINE_LINE in before:
        raise SystemExit("baseline APP_VERSION already present before patch")
    after = before.replace(CURRENT_LINE, BASELINE_LINE, 1)
    constants.write_text(after, encoding="utf-8", newline="\n")

    current_files = {
        k: v for k, v in snapshot(current).items()
        if k != "MIGRATION_MANIFEST.json"
    }
    baseline_files = snapshot(out)

    current_paths = set(current_files)
    baseline_paths = set(baseline_files)
    if current_paths != baseline_paths:
        raise SystemExit("baseline file set differs from current candidate file set")

    changed = sorted(
        path for path in current_paths
        if current_files[path]["sha256"] != baseline_files[path]["sha256"]
        or current_files[path]["size"] != baseline_files[path]["size"]
    )
    if changed != [CONSTANTS_PATH.as_posix()]:
        raise SystemExit(f"baseline must change only constants.py, got: {changed}")

    baseline_text = constants.read_text(encoding="utf-8")
    if baseline_text.count(BASELINE_LINE) != 1 or CURRENT_LINE in baseline_text:
        raise SystemExit("baseline APP_VERSION patch did not apply exactly")

    rows = [
        {"path": path, **baseline_files[path]}
        for path in sorted(baseline_files)
    ]
    manifest = {
        "schema": "dlt-release-acceptance-baseline-v1",
        "purpose": "release-n-to-n-plus-1-acceptance-only",
        "final_eligible": False,
        "candidate_head": CANDIDATE_HEAD,
        "current_version": CURRENT_VERSION,
        "baseline_version": BASELINE_VERSION,
        "controlled_changes": [CONSTANTS_PATH.as_posix()],
        "source_manifest_sha256": sha256_file(manifest_path),
        "file_count": len(rows),
        "repository_independence": "NOT VERIFIED",
        "baseline_release_state": "NOT PUBLISHED",
        "files": rows,
    }
    out_manifest = out / "BASELINE_MANIFEST.json"
    out_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "candidate_head": CANDIDATE_HEAD,
                "current_version": CURRENT_VERSION,
                "baseline_version": BASELINE_VERSION,
                "controlled_changes": manifest["controlled_changes"],
                "file_count": manifest["file_count"],
                "baseline_manifest_sha256": sha256_file(out_manifest),
                "final_eligible": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
