from __future__ import annotations

import argparse
import json
import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urlsplit, quote
from head_intelligence.software_net_client import NetClient

SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHARED_REPOSITORY = "douluo511/Geometry-Lotto-Pro"


def version(value):
    parts = str(value or "").strip().split(".")
    if not parts or any(not x.isdigit() for x in parts):
        return None
    return tuple(int(x) for x in parts)


def https(url):
    p = urlsplit(str(url or ""))
    return p.scheme.lower() == "https" and bool(p.hostname)


def official_releases(n, n1, repository, source_sha, *, net=None):
    """Fetch official metadata and asset bytes; declared hashes alone are insufficient."""
    checks, receipts = {}, {}
    if repository == SHARED_REPOSITORY or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("independent repository identity invalid")
    net = net or NetClient(max_payload_bytes=512 * 1024 * 1024)
    for label, release in (("n", n), ("n1", n1)):
        tag = str(release.get("tag") or "")
        if tag not in {str(release.get("version")), "v" + str(release.get("version"))}:
            raise ValueError("release tag does not match its version")
        api_url = f"https://api.github.com/repos/{repository}/releases/tags/{quote(tag, safe='')}"
        raw, metadata_receipt = net.get_bytes(api_url, source_id=f"official_release_{label}")
        metadata = json.loads(raw.decode("utf-8-sig"))
        valid = (metadata.get("tag_name") == tag and metadata.get("id") == release.get("release_id")
                 and metadata.get("draft") is False and metadata.get("prerelease") is False
                 and bool(metadata.get("published_at"))
                 and metadata.get("html_url") == f"https://github.com/{repository}/releases/tag/{tag}"
                 and metadata.get("html_url") == release.get("release_url"))
        receipts[f"release_{label}"] = metadata_receipt.to_dict()
        assets = metadata.get("assets") or []
        for name, field in (("HeadIntelligence.exe", "main_exe_sha256"), ("HeadIntelligence_Updater.exe", "updater_exe_sha256")):
            found = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
            if len(found) != 1:
                valid = False
                continue
            asset = found[0]
            expected_url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
            if asset.get("browser_download_url") != expected_url or asset.get("state") != "uploaded":
                valid = False
                continue
            payload, receipt = net.get_bytes(expected_url, source_id=f"official_asset_{label}_{name}")
            evidence = receipt.to_dict()
            evidence.pop("raw_b64", None)
            receipts[f"asset_{label}_{name}"] = evidence
            final_host = urlsplit(evidence.get("final_url", "")).hostname
            valid = valid and (len(payload) == asset.get("size") and len(payload) > 0
                              and hashlib.sha256(payload).hexdigest() == release.get(field)
                              and final_host in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
        checks[f"official_release_{label}"] = {"status": "PASS" if valid else "FAIL"}
    commit_url = f"https://api.github.com/repos/{repository}/commits/{quote(str(n1['tag']), safe='')}"
    raw, commit_receipt = net.get_bytes(commit_url, source_id="official_release_n1_commit")
    receipts["tag_commit"] = commit_receipt.to_dict()
    checks["official_tag_source_binding"] = {"status": "PASS" if json.loads(raw.decode("utf-8-sig")).get("sha") == source_sha else "FAIL"}
    return checks, receipts


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input")
    p.add_argument("--repository", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    if not args.input or not Path(args.input).exists():
        report = {
            "schema": "head-intelligence-real-software-release-validation-v1",
            "status": "BLOCKED",
            "github_sha": (os.environ.get("HEAD_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "workflow_run": os.environ.get("GITHUB_RUN_ID"),
            "workflow_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "detail": "real independent production Release N→N+1 evidence is unavailable",
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0

    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        checks = {}
        def put(name, ok, **extra):
            checks[name] = {"status": "PASS" if ok else "FAIL", **extra}

        put("schema", isinstance(value, dict) and value.get("schema") == "head-intelligence-real-software-update-v1")
        put("declared_status", isinstance(value, dict) and value.get("status") == "PASS")
        put(
            "dedicated_repository_binding",
            args.repository != SHARED_REPOSITORY
            and value.get("repository") == args.repository,
            evidence_repository=value.get("repository"),
        )
        put(
            "source_binding",
            bool(COMMIT.fullmatch(str(args.source_sha).lower()))
            and str(value.get("source_sha") or "").lower() == str(args.source_sha).lower(),
        )

        n = value.get("release_n") if isinstance(value.get("release_n"), dict) else {}
        n1 = value.get("release_n1") if isinstance(value.get("release_n1"), dict) else {}
        v0, v1 = version(n.get("version")), version(n1.get("version"))
        old_hash = str(n.get("main_exe_sha256") or "").lower()
        new_hash = str(n1.get("main_exe_sha256") or "").lower()
        updater_hash = str(n.get("updater_exe_sha256") or "").lower()
        put("monotonic_versions", v0 is not None and v1 is not None and v1 > v0)
        put(
            "release_assets",
            all(SHA256.fullmatch(x) for x in (old_hash, new_hash, updater_hash))
            and https(n.get("release_url")) and https(n1.get("release_url")),
        )

        result = value.get("updater_result") if isinstance(value.get("updater_result"), dict) else {}
        put(
            "updater_transaction",
            result.get("status") == "PASS"
            and result.get("operation") == "software_update"
            and result.get("action") == "UPDATED"
            and version(result.get("from_version")) == v0
            and version(result.get("to_version")) == v1
            and str(result.get("old_exe_sha256") or "").lower() == old_hash
            and str(result.get("new_exe_sha256") or "").lower() == new_hash
            and result.get("rollback_performed") is False,
        )

        for key in ("manifest_receipt", "artifact_receipt"):
            receipt = result.get(key) if isinstance(result.get(key), dict) else {}
            digest = str(receipt.get("sha256") or "").lower()
            try:
                byte_count = int(receipt.get("byte_count") or receipt.get("bytes") or 0)
            except (TypeError, ValueError):
                byte_count = 0
            put(
                key,
                https(receipt.get("final_url") or receipt.get("url"))
                and int(receipt.get("http_status") or 0) == 200
                and bool(SHA256.fullmatch(digest))
                and byte_count > 0,
            )

        execution = value.get("updater_execution") if isinstance(value.get("updater_execution"), dict) else {}
        put(
            "independent_updater_execution",
            execution.get("independent_process") is True
            and str(execution.get("updater_exe_sha256") or "").lower() == updater_hash,
        )

        click = value.get("physical_update_click") if isinstance(value.get("physical_update_click"), dict) else {}
        put(
            "physical_one_click_update",
            click.get("status") == "PASS"
            and click.get("label") == "一键更新"
            and str(click.get("from_exe_sha256") or "").lower() == old_hash
            and str(click.get("to_exe_sha256") or "").lower() == new_hash,
        )

        post = value.get("post_update_self_test") if isinstance(value.get("post_update_self_test"), dict) else {}
        put(
            "post_update_self_test",
            post.get("status") == "PASS"
            and str(post.get("exe_sha256") or "").lower() == new_hash,
        )

        official_checks, official_receipts = official_releases(n, n1, args.repository, args.source_sha)
        checks.update(official_checks)

        status = "PASS" if checks and all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
        report = {
            "schema": "head-intelligence-real-software-release-validation-v1",
            "status": status,
            "github_sha": (os.environ.get("HEAD_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "workflow_run": os.environ.get("GITHUB_RUN_ID"),
            "workflow_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "checks": checks,
            "official_source_receipts": official_receipts,
        }
    except Exception as exc:
        report = {
            "schema": "head-intelligence-real-software-release-validation-v1",
            "status": "FAIL",
            "github_sha": (os.environ.get("HEAD_SOURCE_SHA") or os.environ.get("GITHUB_SHA")),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "workflow_run": os.environ.get("GITHUB_RUN_ID"),
            "workflow_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "error": f"{type(exc).__name__}: {exc}",
        }

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
