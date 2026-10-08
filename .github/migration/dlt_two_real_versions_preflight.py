#!/usr/bin/env python3
"""Strict provenance preflight for TWO REAL, behavior-different DLT builds.

This only proves version/source correspondence; it does not issue a GitHub Release,
make a remote repository independent, or claim Updater HTTPS N->N+1 PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = "douluo511/Geometry-Lotto-Pro-DLT"
OLD = {
    "version": "2.1.5",
    "source": "6e4497ede87fb5dc0673e53aa0e993ef4674694c",
    "export": "3711ddc778caa9592227a571ff877aca662b769c",
    "manifest": "6ac810f8e54ff6b597692684c3110d85420733380e7811477b097477d05b7547",
    "sums": "3c2eeaf79f9da4037c6860e6dcb6d133d0e5c133b5980c5b835da8a0372d03ac",
}
NEW = {
    "version": "2.1.6",
    "source": "b1051e320691a7b9798092f797751a2f13a4b1cc",
    "export": "825e4fc8b0a661a7ad5a42b77122965a1146b803",
    "manifest": "ce23206a29bfbe727eb7b88f2fa188349987b72f5cbd20cb8e1ca868bb4135fe",
    "sums": "54b6e7488c1e7fd8560d6757cdaa6c5216eb8dd9b64faba309b05278b46e3fb1",
}
EXPECTED_CHANGED = {
    "DLT/src/glp/constants.py",
    "DLT/src/glp/storage.py",
    "DLT/tests/test_no_edge_uniform_production.py",
    "DLT/tests/test_prospective_hit_rate_truth.py",
}
SCHEMA = "dlt-independent-export-v7-dual-hit-rate"
SKIP = {"MIGRATION_MANIFEST.json", "MIGRATION_SHA256SUMS.txt"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect(root: Path, expected: dict[str, str]) -> dict[str, str]:
    manifest_path = root / "MIGRATION_MANIFEST.json"
    sums_path = root / "MIGRATION_SHA256SUMS.txt"
    if not manifest_path.is_file() or not sums_path.is_file():
        raise ValueError("export manifest or sums missing")
    if sha(manifest_path.read_bytes()) != expected["manifest"]:
        raise ValueError("exact archived migration manifest identity mismatch")
    if sha(sums_path.read_bytes()) != expected["sums"]:
        raise ValueError("exact archived checksum identity mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key, value in {
        "schema": SCHEMA,
        "source_commit": expected["source"],
        "candidate_head": expected["source"],
        "export_commit": expected["export"],
        "target_repository": REPO,
        "layout": "preserve-dlt-root",
        "repository_independence": "NOT VERIFIED",
        "release_context": "NOT VERIFIED",
        "file_count": 44,
    }.items():
        if manifest.get(key) != value:
            raise ValueError(f"invalid {expected['version']} manifest field {key}")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != 44:
        raise ValueError("manifest must describe exactly 44 real DLT files")
    names: set[str] = set()
    hashes: dict[str, str] = {}
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("malformed manifest row")
        rel = row["path"]
        if (not isinstance(rel, str) or rel.startswith("/") or "\\" in rel
                or not (rel.startswith("DLT/") or rel.startswith(".github/"))
                or ".." in Path(rel).parts or ":" in rel or rel in names):
            raise ValueError("unsafe or duplicate migration path")
        names.add(rel)
        raw = (root / rel)
        if (not raw.is_file() or type(row["bytes"]) is not int
                or raw.stat().st_size != row["bytes"]
                or sha(raw.read_bytes()) != row["sha256"]):
            raise ValueError(f"tampered or absent payload {rel}")
        hashes[rel] = row["sha256"]
        lines.append(f"{row['sha256']}  {rel}")
    if sums_path.read_text(encoding="utf-8").splitlines() != lines:
        raise ValueError("checksum order/content mismatch")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != names | SKIP:
        raise ValueError("extra, omitted, or unexpected independent seed file")
    constants = (root / "DLT/src/glp/constants.py").read_text(encoding="utf-8")
    if f'APP_VERSION = "{expected["version"]}"' not in constants:
        raise ValueError("export version is not the actual product version")
    return hashes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--previous", required=True, type=Path)
    p.add_argument("--current", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    a = p.parse_args()
    previous = inspect(a.previous, OLD)
    current = inspect(a.current, NEW)
    if set(previous) != set(current):
        raise ValueError("N->N+1 missing or extra project files")
    changed = {name for name in previous if previous[name] != current[name]}
    if changed != EXPECTED_CHANGED:
        raise ValueError(f"historical source transition differs from real four-file repair: {sorted(changed)}")
    old_storage = (a.previous / "DLT/src/glp/storage.py").read_text(encoding="utf-8")
    new_storage = (a.current / "DLT/src/glp/storage.py").read_text(encoding="utf-8")
    if "freeze_time.date() >= draw_date" not in old_storage:
        raise ValueError("previous source not the known vulnerable v2.1.5")
    if "freeze_china_day >= draw_date" not in new_storage or "timezone(timedelta(hours=8))" not in new_storage:
        raise ValueError("current source lacks repaired China-draw-day gate")
    if not re.fullmatch(r"[0-9a-f]{64}", NEW["manifest"]):
        raise ValueError("invalid current manifest identity")
    report = {
        "schema": "dlt-real-two-version-source-preflight-v1",
        "status": "PASS",
        "previous_version": OLD["version"], "current_version": NEW["version"],
        "previous_source": OLD["source"], "current_source": NEW["source"],
        "previous_export": OLD["export"], "current_export": NEW["export"],
        "previous_manifest_sha256": OLD["manifest"], "current_manifest_sha256": NEW["manifest"],
        "file_count_each": 44, "exact_changed_files": sorted(changed),
        "previous_is_a_real_historical_source": True,
        "current_corrects_china_draw_day": True,
        "independent_repository": "NOT VERIFIED",
        "software_release_network_n_to_n_plus_1": "NOT VERIFIED",
        "windows_binary_transition": "NOT VERIFIED",
        "final_gate": "FAIL",
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
