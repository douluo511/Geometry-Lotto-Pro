from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA = "ssq-software-update-manifest-v1"
APP = "Geometry Lotto Pro SSQ"
REPOSITORY = "douluo511/Geometry-Lotto-Pro-SSQ"
EXPECTED_EXE = "Geometry_Lotto_Pro_SSQ_Windows_Verified.exe"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\+([A-Za-z0-9.-]+))?$")
VERSION_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?(?:\+([A-Za-z0-9.-]+))?$"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_version_key(version: str) -> tuple[int, int, int]:
    match = STABLE_VERSION_RE.fullmatch(version.strip())
    if match is None:
        raise ValueError("version must be stable SemVer MAJOR.MINOR.PATCH with optional build metadata")
    return tuple(int(match.group(i)) for i in (1, 2, 3))


def version_precedence(version: str) -> tuple[Any, ...]:
    match = VERSION_RE.fullmatch(version.strip())
    if match is None:
        raise ValueError("version must be valid SemVer MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return (*core, 1, ())
    identifiers: list[tuple[int, Any]] = []
    for token in prerelease.split("."):
        if not token:
            raise ValueError("empty prerelease identifier")
        identifiers.append((0, int(token)) if token.isdigit() else (1, token))
    return (*core, 0, tuple(identifiers))


def require_forward(base_version: str, candidate_version: str) -> None:
    stable_version_key(candidate_version)
    if version_precedence(candidate_version) <= version_precedence(base_version):
        raise ValueError(
            f"candidate must move forward: base={base_version}, candidate={candidate_version}"
        )


def load_self_test(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"invalid exact-EXE self-test JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("exact-EXE self-test must be a JSON object")
    return value


def build_manifest(
    exe: Path,
    *,
    version: str,
    base_version: str | None,
    baseline: bool,
    tag: str,
    self_test: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    exe = exe.resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"EXE missing: {exe}")
    if exe.name != EXPECTED_EXE:
        raise ValueError(f"unexpected artifact filename: {exe.name}")

    if baseline:
        version_precedence(version)
        if base_version is not None:
            raise ValueError("--baseline cannot be combined with --base-version")
    else:
        stable_version_key(version)
        if base_version is None:
            raise ValueError("--base-version is required for a forward candidate manifest")
        require_forward(base_version, version)

    if tag not in {version, f"v{version}"}:
        raise ValueError("release tag must be exactly VERSION or vVERSION")

    size = exe.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact size outside updater policy")
    digest = sha256_file(exe)

    proof = load_self_test(self_test)
    if proof.get("status") != "PASS":
        raise ValueError("exact-EXE self-test status is not PASS")
    if proof.get("game") != "SSQ":
        raise ValueError("exact-EXE self-test game identity is not SSQ")
    if proof.get("version") != version:
        raise ValueError("exact-EXE self-test version does not match candidate version")
    if proof.get("exe_sha256") != digest:
        raise ValueError("exact-EXE self-test hash does not match artifact bytes")

    artifact_url = (
        f"https://github.com/{REPOSITORY}/releases/download/"
        f"{quote(tag, safe='._-+')}/{quote(exe.name, safe='._-')}"
    )

    manifest = {
        "schema": SCHEMA,
        "app": APP,
        "version": version,
        "artifact_url": artifact_url,
        "artifact_sha256": digest,
        "artifact_bytes": size,
    }
    evidence = {
        "schema": "ssq-release-manifest-preparation-v1",
        "status": "PASS",
        "repository": REPOSITORY,
        "mode": "BASELINE" if baseline else "FORWARD_CANDIDATE",
        "base_version": base_version,
        "candidate_version": version,
        "release_tag": tag,
        "artifact": exe.name,
        "artifact_sha256": digest,
        "artifact_bytes": size,
        "artifact_url": artifact_url,
        "self_test": str(self_test.resolve()),
        "self_test_sha256": sha256_file(self_test.resolve()),
        "checks": {
            "baseline_version_valid": True if baseline else "NOT_APPLICABLE_CANDIDATE",
            "stable_candidate_version": True if not baseline else "NOT_APPLICABLE_BASELINE",
            "strictly_forward_version": True if not baseline else "NOT_APPLICABLE_BASELINE",
            "exact_artifact_filename": True,
            "exact_self_test_pass": True,
            "game_identity": True,
            "version_binding": True,
            "hash_binding": True,
            "trusted_release_repository_url": True,
        },
    }
    return manifest, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--base-version")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--self-test", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest, evidence = build_manifest(
            args.exe,
            version=args.version,
            base_version=args.base_version,
            baseline=args.baseline,
            tag=args.tag,
            self_test=args.self_test,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema": "ssq-release-manifest-preparation-v1",
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=True, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
