from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

SHARED_REPOSITORY = "douluo511/Geometry-Lotto-Pro"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAIN_EXE = "Geometry_Lotto_Pro_Happy8.exe"
UPDATER_EXE = "Geometry_Lotto_Pro_Happy8_Updater.exe"


def _version(value: object) -> tuple[int, ...] | None:
    text = str(value or "").strip()
    parts = text.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _sha256(value: object) -> str:
    return str(value or "").strip().lower()


def _https_host(value: object) -> str | None:
    parsed = urlsplit(str(value or ""))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    return parsed.hostname.lower()


def _iso_timestamp(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _receipt_ok(receipt: object, *, trusted_hosts: set[str], sha: str | None = None, size: int | None = None) -> bool:
    if not isinstance(receipt, dict):
        return False
    host = _https_host(receipt.get("url"))
    digest = _sha256(receipt.get("sha256"))
    try:
        byte_count = int(receipt.get("bytes") or 0)
    except (TypeError, ValueError):
        return False
    if (
        host not in trusted_hosts
        or int(receipt.get("http_status") or 0) != 200
        or not SHA256_RE.fullmatch(digest)
        or byte_count <= 0
    ):
        return False
    if sha is not None and digest != sha:
        return False
    if size is not None and byte_count != size:
        return False
    return True


def _official_json_receipt(receipt: object, expected_url: str) -> dict | None:
    if not isinstance(receipt, dict) or receipt.get("url") != expected_url:
        return None
    raw = receipt.get("raw_body")
    if not isinstance(raw, str):
        return None
    raw_bytes = raw.encode("utf-8")
    if not _receipt_ok(receipt, trusted_hosts={"api.github.com"}, sha=hashlib.sha256(raw_bytes).hexdigest(), size=len(raw_bytes)):
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _official_release_binding(release: dict, *, repository: str) -> dict:
    """Cross-check captured HTTPS release/tag responses and downloaded asset receipts."""
    release_id = str(release.get("release_id") or "")
    version = str(release.get("version") or "")
    source = str(release.get("source_sha") or "").lower()
    capture = release.get("official_release") if isinstance(release.get("official_release"), dict) else {}
    api_root = f"https://api.github.com/repos/{repository}"
    release_url = f"{api_root}/releases/{release_id}"
    metadata = _official_json_receipt(capture.get("release_response"), release_url) or {}
    tag = str(metadata.get("tag_name") or "")
    commit_url = f"{api_root}/commits/{quote(tag, safe='')}"
    commit = _official_json_receipt(capture.get("tag_commit_response"), commit_url) or {}
    expected_page = f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}"
    metadata_ok = (
        bool(REPOSITORY_RE.fullmatch(repository))
        and release_id.isdigit() and int(release_id) > 0
        and str(metadata.get("id") or "") == release_id
        and metadata.get("url") == release_url
        and metadata.get("html_url") == expected_page
        and release.get("release_url") == expected_page
        and metadata.get("draft") is False and metadata.get("prerelease") is False
        and _iso_timestamp(metadata.get("published_at"))
        and tag in (version, "v" + version)
        and commit.get("sha") == source and bool(COMMIT_RE.fullmatch(source))
        and commit.get("html_url") == f"https://github.com/{repository}/commit/{source}"
    )
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    details = {}
    for key, filename, expected_sha in (
        ("main", MAIN_EXE, _sha256(release.get("main_exe_sha256"))),
        ("updater", UPDATER_EXE, _sha256(release.get("updater_exe_sha256"))),
    ):
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename]
        asset = matches[0] if len(matches) == 1 else {}
        asset_id = str(asset.get("id") or "")
        size = asset.get("size")
        expected_asset_url = f"https://github.com/{repository}/releases/download/{quote(tag, safe='')}/{filename}"
        receipt = capture.get(key + "_asset_receipt")
        ok = (
            len(matches) == 1 and asset_id.isdigit() and int(asset_id) > 0
            and asset.get("url") == f"{api_root}/releases/assets/{asset_id}"
            and asset.get("browser_download_url") == expected_asset_url
            and asset.get("state") == "uploaded" and isinstance(size, int) and size > 0
            and isinstance(receipt, dict) and str(receipt.get("asset_id") or "") == asset_id
            and receipt.get("url") == expected_asset_url
            and _receipt_ok(receipt, trusted_hosts={"github.com"}, sha=expected_sha, size=size)
            and (asset.get("digest") is None or asset.get("digest") == "sha256:" + expected_sha)
        )
        details[key] = {"status": "PASS" if ok else "FAIL", "asset_id": asset_id,
                        "asset_url": asset.get("browser_download_url"), "bytes": size, "sha256": expected_sha}
    return {
        "status": "PASS" if metadata_ok and all(item["status"] == "PASS" for item in details.values()) else "FAIL",
        "release_id": release_id, "tag": tag, "resolved_source_sha": commit.get("sha"),
        "release_response_url": release_url, "tag_commit_response_url": commit_url,
        "metadata_status": "PASS" if metadata_ok else "FAIL", "assets": details,
    }


def validate_real_release_evidence(
    value: object,
    *,
    repository: str,
    source_sha: str,
    run_id: str,
    run_attempt: str,
) -> dict:
    checks: dict[str, dict] = {}

    def put(name: str, ok: bool, **evidence: object) -> None:
        checks[name] = {"status": "PASS" if ok else "FAIL", **evidence}

    if not isinstance(value, dict):
        return {
            "schema": "happy8-real-release-validation-v1",
            "status": "FAIL",
            "repository": repository,
            "source_sha": source_sha,
            "checks": {"document": {"status": "FAIL", "detail": "evidence root is not an object"}},
        }

    put("schema", value.get("schema") == "happy8-real-release-update-v1", actual=value.get("schema"))
    put("declared_status", value.get("status") == "PASS", actual=value.get("status"))

    repo_ok = bool(repository) and repository != SHARED_REPOSITORY and value.get("repository") == repository
    put(
        "dedicated_repository_binding",
        repo_ok,
        current_repository=repository,
        evidence_repository=value.get("repository"),
        shared_repository=SHARED_REPOSITORY,
    )

    source_sha = str(source_sha or "").lower()
    put("source_sha_format", bool(COMMIT_RE.fullmatch(source_sha)), source_sha=source_sha)

    context = value.get("execution_context") if isinstance(value.get("execution_context"), dict) else {}
    put(
        "current_run_binding",
        context.get("producer") == "happy8-real-release-acceptance-v1"
        and str(context.get("github_run_id") or "") == str(run_id)
        and str(context.get("github_run_attempt") or "") == str(run_attempt)
        and str(context.get("head_sha") or "").lower() == source_sha,
        producer=context.get("producer"),
        github_run_id=context.get("github_run_id"),
        github_run_attempt=context.get("github_run_attempt"),
        head_sha=context.get("head_sha"),
    )

    release_n = value.get("release_n") if isinstance(value.get("release_n"), dict) else {}
    release_n1 = value.get("release_n1") if isinstance(value.get("release_n1"), dict) else {}
    checks["official_release_n_binding"] = _official_release_binding(release_n, repository=repository)
    checks["official_release_n1_binding"] = _official_release_binding(release_n1, repository=repository)
    release_n_id = str(release_n.get("release_id") or "").strip()
    release_n1_id = str(release_n1.get("release_id") or "").strip()
    put(
        "release_ids",
        bool(release_n_id) and bool(release_n1_id) and release_n_id != release_n1_id,
        release_n_id=release_n_id,
        release_n1_id=release_n1_id,
    )
    n_version = _version(release_n.get("version"))
    n1_version = _version(release_n1.get("version"))
    put(
        "monotonic_versions",
        n_version is not None and n1_version is not None and n1_version > n_version,
        from_version=release_n.get("version"),
        to_version=release_n1.get("version"),
    )

    n_source = str(release_n.get("source_sha") or "").lower()
    n1_source = str(release_n1.get("source_sha") or "").lower()
    put(
        "release_source_binding",
        bool(COMMIT_RE.fullmatch(n_source))
        and bool(COMMIT_RE.fullmatch(n1_source))
        and n1_source == source_sha,
        release_n_source_sha=n_source,
        release_n1_source_sha=n1_source,
    )

    n_main = _sha256(release_n.get("main_exe_sha256"))
    n1_main = _sha256(release_n1.get("main_exe_sha256"))
    n_updater = _sha256(release_n.get("updater_exe_sha256"))
    n1_updater = _sha256(release_n1.get("updater_exe_sha256"))
    put(
        "release_asset_hashes",
        all(SHA256_RE.fullmatch(x) for x in (n_main, n1_main, n_updater, n1_updater)),
        release_n_main=n_main,
        release_n1_main=n1_main,
        release_n_updater=n_updater,
        release_n1_updater=n1_updater,
    )
    put(
        "release_urls_https",
        _https_host(release_n.get("release_url")) is not None
        and _https_host(release_n1.get("release_url")) is not None,
        release_n_url=release_n.get("release_url"),
        release_n1_url=release_n1.get("release_url"),
    )

    config = value.get("update_config") if isinstance(value.get("update_config"), dict) else {}
    trusted_hosts = {
        str(host).strip().lower()
        for host in (config.get("trusted_hosts") or [])
        if str(host).strip()
    }
    manifest_url_host = _https_host(config.get("manifest_url"))
    put(
        "trusted_update_config",
        config.get("schema") == "happy8-update-config-v1"
        and bool(trusted_hosts)
        and manifest_url_host in trusted_hosts,
        manifest_url=config.get("manifest_url"),
        trusted_hosts=sorted(trusted_hosts),
    )

    manifest = value.get("manifest") if isinstance(value.get("manifest"), dict) else {}
    artifact_host = _https_host(manifest.get("artifact_url"))
    artifact_sha = _sha256(manifest.get("artifact_sha256"))
    try:
        artifact_bytes = int(manifest.get("artifact_bytes") or 0)
    except (TypeError, ValueError):
        artifact_bytes = 0
    manifest_ok = (
        manifest.get("schema") == "happy8-update-manifest-v1"
        and _version(manifest.get("version")) == n1_version
        and artifact_host in trusted_hosts
        and artifact_sha == n1_main
        and bool(SHA256_RE.fullmatch(artifact_sha))
        and 0 < artifact_bytes <= 512 * 1024 * 1024
    )
    put(
        "manifest_contract",
        manifest_ok,
        version=manifest.get("version"),
        artifact_url=manifest.get("artifact_url"),
        artifact_sha256=artifact_sha,
        artifact_bytes=artifact_bytes,
    )

    updater_result = value.get("updater_result") if isinstance(value.get("updater_result"), dict) else {}
    updater_core_ok = (
        updater_result.get("status") == "PASS"
        and updater_result.get("operation") == "software_update"
        and updater_result.get("action") == "UPDATED"
        and _version(updater_result.get("from_version")) == n_version
        and _version(updater_result.get("to_version")) == n1_version
        and _sha256(updater_result.get("old_exe_sha256")) == n_main
        and _sha256(updater_result.get("new_exe_sha256")) == n1_main
        and updater_result.get("rollback_performed") is False
        and isinstance(updater_result.get("startup_recovery"), dict)
        and updater_result["startup_recovery"].get("status") == "PASS"
    )
    put("updater_result_contract", updater_core_ok, action=updater_result.get("action"))

    put(
        "manifest_receipt",
        _receipt_ok(updater_result.get("manifest_receipt"), trusted_hosts=trusted_hosts)
        and updater_result["manifest_receipt"].get("url") == config.get("manifest_url"),
    )
    put(
        "artifact_receipt",
        _receipt_ok(
            updater_result.get("artifact_receipt"),
            trusted_hosts=trusted_hosts,
            sha=n1_main if SHA256_RE.fullmatch(n1_main) else None,
            size=artifact_bytes if artifact_bytes > 0 else None,
        ) and updater_result["artifact_receipt"].get("url") == manifest.get("artifact_url"),
    )

    execution = value.get("updater_execution") if isinstance(value.get("updater_execution"), dict) else {}
    put(
        "independent_updater_execution",
        execution.get("independent_process") is True
        and _sha256(execution.get("updater_exe_sha256")) == n_updater
        and _sha256(execution.get("main_exe_sha256_before")) == n_main,
        independent_process=execution.get("independent_process"),
    )

    click = value.get("physical_update_click") if isinstance(value.get("physical_update_click"), dict) else {}
    put(
        "physical_one_click_update",
        click.get("status") == "PASS"
        and click.get("label") == "一键更新"
        and _sha256(click.get("from_exe_sha256")) == n_main
        and _sha256(click.get("to_exe_sha256")) == n1_main,
        label=click.get("label"),
    )

    self_test = value.get("post_update_self_test") if isinstance(value.get("post_update_self_test"), dict) else {}
    put(
        "post_update_self_test",
        self_test.get("status") == "PASS"
        and _sha256(self_test.get("exe_sha256")) == n1_main,
    )

    put("tested_at", _iso_timestamp(value.get("tested_at")), tested_at=value.get("tested_at"))

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    return {
        "schema": "happy8-real-release-validation-v1",
        "status": status,
        "repository": repository,
        "source_sha": source_sha,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--repo-root", default="../..")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not args.input or not Path(args.input).exists():
        report = {
            "schema": "happy8-real-release-validation-v1",
            "status": "BLOCKED",
            "repository": args.repository,
            "source_sha": args.source_sha,
            "detail": "real independent production Release N→N+1 evidence is unavailable",
        }
    else:
        try:
            input_path = Path(args.input).resolve()
            repo_root = Path(args.repo_root).resolve()
            try:
                rel = input_path.relative_to(repo_root).as_posix()
            except ValueError as exc:
                raise RuntimeError("real release evidence is outside the current repository workspace") from exc
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", rel],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if tracked.returncode == 0:
                raise RuntimeError("real release evidence must be generated by the current run, not committed to Git")
            value = json.loads(input_path.read_text(encoding="utf-8-sig"))
            report = validate_real_release_evidence(
                value,
                repository=args.repository,
                source_sha=args.source_sha,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            )
        except Exception as exc:
            report = {
                "schema": "happy8-real-release-validation-v1",
                "status": "FAIL",
                "repository": args.repository,
                "source_sha": args.source_sha,
                "error": f"{type(exc).__name__}: {exc}",
            }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 2 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
