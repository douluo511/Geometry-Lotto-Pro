from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

SHARED_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
MAIN_EXE = "Geometry_Lotto_Pro_Happy8.exe"
UPDATER_EXE = "Geometry_Lotto_Pro_Happy8_Updater.exe"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha(value: object) -> str:
    return str(value or "").strip().lower()


def _https(value: object) -> bool:
    parsed = urlsplit(str(value or ""))
    return parsed.scheme.lower() == "https" and bool(parsed.hostname)


def _iso(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_final_artifact(
    value: object,
    *,
    repository: str,
    source_sha: str,
    run_id: str,
    run_attempt: str,
    windows: object,
    physical_gui: object,
    same_hash: object,
    real_release: object,
) -> dict:
    checks: dict[str, dict] = {}

    def put(name: str, ok: bool, **evidence: object) -> None:
        checks[name] = {"status": "PASS" if ok else "FAIL", **evidence}

    if not isinstance(value, dict):
        return {
            "schema": "happy8-final-artifact-validation-v1",
            "status": "FAIL",
            "checks": {"document": {"status": "FAIL", "detail": "final artifact manifest is not an object"}},
        }

    source_sha = str(source_sha or "").strip().lower()
    put("schema", value.get("schema") == "happy8-final-artifact-v1", actual=value.get("schema"))
    put("declared_status", value.get("status") == "PASS", actual=value.get("status"))
    put(
        "dedicated_repository_binding",
        bool(repository)
        and repository != SHARED_REPOSITORY
        and value.get("repository") == repository,
        repository=repository,
        manifest_repository=value.get("repository"),
    )
    put(
        "source_binding",
        bool(COMMIT_RE.fullmatch(source_sha))
        and str(value.get("source_sha") or "").lower() == source_sha,
        source_sha=source_sha,
        manifest_source_sha=value.get("source_sha"),
    )

    context = value.get("execution_context") if isinstance(value.get("execution_context"), dict) else {}
    put(
        "current_run_binding",
        context.get("producer") == "happy8-final-artifact-freeze-v1"
        and str(context.get("github_run_id") or "") == str(run_id)
        and str(context.get("github_run_attempt") or "") == str(run_attempt)
        and str(context.get("head_sha") or "").lower() == source_sha,
        producer=context.get("producer"),
        github_run_id=context.get("github_run_id"),
        github_run_attempt=context.get("github_run_attempt"),
        head_sha=context.get("head_sha"),
    )

    formal = value.get("formal_release") if isinstance(value.get("formal_release"), dict) else {}
    release_to_version = None
    release_to_url = None
    if isinstance(real_release, dict):
        rr_prechecks = real_release.get("checks", {}) if isinstance(real_release.get("checks"), dict) else {}
        monotonic = rr_prechecks.get("monotonic_versions", {})
        release_urls = rr_prechecks.get("release_urls_https", {})
        if isinstance(monotonic, dict):
            release_to_version = monotonic.get("to_version")
        if isinstance(release_urls, dict):
            release_to_url = release_urls.get("release_n1_url")
    put(
        "formal_release",
        formal.get("unique") is True
        and bool(str(formal.get("release_id") or "").strip())
        and _https(formal.get("release_url"))
        and bool(str(formal.get("version") or "").strip())
        and formal.get("version") == release_to_version
        and formal.get("release_url") == release_to_url,
        release_id=formal.get("release_id"),
        release_url=formal.get("release_url"),
        version=formal.get("version"),
        validated_release_version=release_to_version,
        validated_release_url=release_to_url,
    )

    exact = value.get("exact_exe") if isinstance(value.get("exact_exe"), dict) else {}
    updater = value.get("updater_exe") if isinstance(value.get("updater_exe"), dict) else {}
    exact_sha = _sha(exact.get("sha256"))
    updater_sha = _sha(updater.get("sha256"))
    try:
        exact_bytes = int(exact.get("bytes") or 0)
    except (TypeError, ValueError):
        exact_bytes = 0
    try:
        updater_bytes = int(updater.get("bytes") or 0)
    except (TypeError, ValueError):
        updater_bytes = 0

    put(
        "exact_exe_manifest",
        exact.get("filename") == MAIN_EXE
        and bool(SHA256_RE.fullmatch(exact_sha))
        and exact_bytes > 0,
        filename=exact.get("filename"),
        sha256=exact_sha,
        bytes=exact_bytes,
    )
    put(
        "updater_exe_manifest",
        updater.get("filename") == UPDATER_EXE
        and bool(SHA256_RE.fullmatch(updater_sha))
        and updater_bytes > 0,
        filename=updater.get("filename"),
        sha256=updater_sha,
        bytes=updater_bytes,
    )

    windows = windows if isinstance(windows, dict) else {}
    put(
        "windows_exact_exe_binding",
        windows.get("status") == "PASS"
        and windows.get("same_hash") is True
        and windows.get("updater_same_hash") is True
        and str(windows.get("source_sha") or "").lower() == source_sha
        and _sha(windows.get("exe_sha256")) == exact_sha
        and _sha(windows.get("rebuild_sha256")) == exact_sha
        and _sha(windows.get("updater_sha256")) == updater_sha
        and _sha(windows.get("updater_rebuild_sha256")) == updater_sha,
    )

    physical_gui = physical_gui if isinstance(physical_gui, dict) else {}
    put(
        "physical_gui_binding",
        physical_gui.get("status") == "PASS"
        and physical_gui.get("same_hash") is True
        and _sha(physical_gui.get("exe_sha256_before")) == exact_sha
        and _sha(physical_gui.get("exe_sha256_after")) == exact_sha,
    )

    same_hash = same_hash if isinstance(same_hash, dict) else {}
    put(
        "post_gui_same_hash_binding",
        same_hash.get("status") == "PASS"
        and _sha(same_hash.get("exe_sha256")) == exact_sha
        and _sha(same_hash.get("build_sha256")) == exact_sha
        and _sha(same_hash.get("physical_gui_sha256")) == exact_sha,
    )

    real_release = real_release if isinstance(real_release, dict) else {}
    rr_checks = real_release.get("checks") if isinstance(real_release.get("checks"), dict) else {}
    rr_assets = rr_checks.get("release_asset_hashes") if isinstance(rr_checks.get("release_asset_hashes"), dict) else {}
    rr_n1_main = _sha(rr_assets.get("release_n1_main"))
    rr_n1_updater = _sha(rr_assets.get("release_n1_updater"))
    put(
        "real_release_binding",
        real_release.get("schema") == "happy8-real-release-validation-v1"
        and real_release.get("status") == "PASS"
        and real_release.get("repository") == repository
        and str(real_release.get("source_sha") or "").lower() == source_sha
        and rr_n1_main == exact_sha
        and rr_n1_updater == updater_sha,
        release_n1_main_sha256=rr_n1_main,
        release_n1_updater_sha256=rr_n1_updater,
    )

    put("created_at", _iso(value.get("created_at")), created_at=value.get("created_at"))

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    return {
        "schema": "happy8-final-artifact-validation-v1",
        "status": status,
        "repository": repository,
        "source_sha": source_sha,
        "checks": checks,
    }


def load(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--repo-root", default="../..")
    parser.add_argument("--windows")
    parser.add_argument("--physical-gui")
    parser.add_argument("--same-hash")
    parser.add_argument("--real-release")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not args.input or not Path(args.input).exists():
        report = {
            "schema": "happy8-final-artifact-validation-v1",
            "status": "NOT VERIFIED",
            "repository": args.repository,
            "source_sha": args.source_sha,
            "detail": "unique final artifact manifest is unavailable",
        }
    else:
        try:
            input_path = Path(args.input).resolve()
            repo_root = Path(args.repo_root).resolve()
            try:
                rel = input_path.relative_to(repo_root).as_posix()
            except ValueError as exc:
                raise RuntimeError("final artifact manifest is outside the current repository workspace") from exc
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", rel],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if tracked.returncode == 0:
                raise RuntimeError("final artifact manifest must be generated by the current run, not committed to Git")
            report = validate_final_artifact(
                load(args.input),
                repository=args.repository,
                source_sha=args.source_sha,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                windows=load(args.windows),
                physical_gui=load(args.physical_gui),
                same_hash=load(args.same_hash),
                real_release=load(args.real_release),
            )
        except Exception as exc:
            report = {
                "schema": "happy8-final-artifact-validation-v1",
                "status": "FAIL",
                "repository": args.repository,
                "source_sha": args.source_sha,
                "error": f"{type(exc).__name__}: {exc}",
            }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
