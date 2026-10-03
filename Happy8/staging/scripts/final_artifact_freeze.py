from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from final_artifact_evidence import validate_artifact_files, validate_final_artifact


def load(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"evidence is not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--repository-evidence", required=True)
    parser.add_argument("--real-release", required=True)
    parser.add_argument("--windows", required=True)
    parser.add_argument("--physical-gui", required=True)
    parser.add_argument("--same-hash", required=True)
    parser.add_argument("--main-exe", required=True)
    parser.add_argument("--updater-exe", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    try:
        repo_evidence = load(args.repository_evidence)
        real_release = load(args.real_release)
        windows = load(args.windows)
        physical = load(args.physical_gui)
        same = load(args.same_hash)

        if repo_evidence.get("status") != "PASS":
            raise RuntimeError("repository independence evidence is not PASS")
        if repo_evidence.get("repository") != args.repository:
            raise RuntimeError("repository independence evidence repository mismatch")
        if real_release.get("status") != "PASS":
            raise RuntimeError("real release validation is not PASS")
        if real_release.get("repository") != args.repository:
            raise RuntimeError("real release repository mismatch")
        if str(real_release.get("source_sha") or "").lower() != args.source_sha.lower():
            raise RuntimeError("real release source SHA mismatch")
        if windows.get("status") != "PASS" or windows.get("same_hash") is not True:
            raise RuntimeError("Windows Exact EXE evidence is not PASS")
        if windows.get("updater_same_hash") is not True:
            raise RuntimeError("Windows Updater reproducibility evidence is not PASS")
        if physical.get("status") != "PASS" or physical.get("same_hash") is not True:
            raise RuntimeError("physical GUI evidence is not PASS")
        if same.get("status") != "PASS":
            raise RuntimeError("post-GUI Same Hash evidence is not PASS")

        rr_checks = real_release.get("checks") if isinstance(real_release.get("checks"), dict) else {}
        versions = rr_checks.get("monotonic_versions") if isinstance(rr_checks.get("monotonic_versions"), dict) else {}
        urls = rr_checks.get("release_urls_https") if isinstance(rr_checks.get("release_urls_https"), dict) else {}
        release_ids = rr_checks.get("release_ids") if isinstance(rr_checks.get("release_ids"), dict) else {}
        version = str(versions.get("to_version") or "")
        release_url = str(urls.get("release_n1_url") or "")
        validated_release_id = str(release_ids.get("release_n1_id") or "")
        if not version or not release_url or not validated_release_id:
            raise RuntimeError("validated N+1 release identity/version/URL is missing")
        if str(args.release_id) != validated_release_id:
            raise RuntimeError("requested formal release id does not match validated N+1 release identity")

        main_exe = Path(args.main_exe).resolve()
        updater_exe = Path(args.updater_exe).resolve()
        if not main_exe.is_file() or not updater_exe.is_file():
            raise RuntimeError("final EXE or Updater EXE is missing")

        manifest = {
            "schema": "happy8-final-artifact-v1",
            "status": "PASS",
            "repository": args.repository,
            "source_sha": args.source_sha.lower(),
            "execution_context": {
                "producer": "happy8-final-artifact-freeze-v1",
                "github_run_id": str(args.run_id),
                "github_run_attempt": str(args.run_attempt),
                "head_sha": args.source_sha.lower(),
            },
            "formal_release": {
                "unique": True,
                "release_id": str(args.release_id),
                "release_url": release_url,
                "version": version,
            },
            "exact_exe": {
                "filename": main_exe.name,
                "sha256": sha256_file(main_exe),
                "bytes": main_exe.stat().st_size,
            },
            "updater_exe": {
                "filename": updater_exe.name,
                "sha256": sha256_file(updater_exe),
                "bytes": updater_exe.stat().st_size,
            },
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }

        validation = validate_final_artifact(
            manifest,
            repository=args.repository,
            source_sha=args.source_sha,
            run_id=str(args.run_id),
            run_attempt=str(args.run_attempt),
            windows=windows,
            physical_gui=physical,
            same_hash=same,
            real_release=real_release,
        )
        file_check = validate_artifact_files(
            manifest,
            main_exe=main_exe,
            updater_exe=updater_exe,
        )
        validation["checks"]["physical_artifact_files"] = file_check
        if validation.get("status") != "PASS" or file_check.get("status") != "PASS":
            raise RuntimeError(
                "generated final artifact manifest did not cross-validate: "
                + json.dumps(validation, ensure_ascii=False, sort_keys=True)
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        failure = {
            "schema": "happy8-final-artifact-freeze-v1",
            "status": "FAIL",
            "repository": args.repository,
            "source_sha": args.source_sha.lower(),
            "error": f"{type(exc).__name__}: {exc}",
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
