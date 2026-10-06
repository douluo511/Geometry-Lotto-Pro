from __future__ import annotations
from gate_common import run_identity

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

SHARED = "douluo511/Geometry-Lotto-Pro"


def version(value):
    parts = str(value or "").split(".")
    if not parts or any(not x.isdigit() for x in parts):
        raise ValueError("invalid numeric version")
    return tuple(map(int, parts))


def receipt(value, *, trusted_hosts, expected_hash=None, expected_size=None):
    if not isinstance(value, dict):
        raise ValueError("missing raw network receipt")
    raw = base64.b64decode(value.get("raw_b64", ""), validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    url = urlsplit(str(value.get("final_url") or value.get("url") or ""))
    if not raw or url.scheme != "https" or url.hostname not in trusted_hosts:
        raise ValueError("receipt is not raw trusted HTTPS evidence")
    if int(value.get("http_status") or value.get("status_code") or 0) != 200:
        raise ValueError("receipt HTTP status is not 200")
    if value.get("sha256") != digest or int(value.get("byte_count") or 0) != len(raw):
        raise ValueError("receipt raw bytes do not match identity")
    if expected_hash and digest != expected_hash:
        raise ValueError("artifact cross-hash mismatch")
    if expected_size is not None and len(raw) != expected_size:
        raise ValueError("artifact cross-size mismatch")
    ledger = value.get("attempt_ledger") or value.get("attempts")
    if not value.get("fetched_at") or not isinstance(ledger, (list, tuple)) or not ledger:
        raise ValueError("receipt provenance incomplete")
    return raw


def validate(value, *, repository, source_sha, run_id, run_attempt):
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository) or repository == SHARED or value.get("repository") != repository:
        raise ValueError("independent repository binding failed")
    if value.get("schema") != "english-root-real-software-update-v1" or value.get("status") != "PASS":
        raise ValueError("real release evidence schema invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or value.get("source_sha") != source_sha:
        raise ValueError("source binding failed")
    if not run_id or not run_attempt or value.get("producer") != "english-root-physical-release-workflow-v1":
        raise ValueError("current workflow producer missing")
    if str(value.get("github_run_id")) != run_id or str(value.get("github_run_attempt")) != run_attempt:
        raise ValueError("wrong run or attempt")
    n, n1 = value.get("release_n") or {}, value.get("release_n1") or {}
    if version(n1.get("version")) <= version(n.get("version")):
        raise ValueError("release is not N to N+1")
    old_hash, new_hash = n.get("main_exe_sha256"), n1.get("main_exe_sha256")
    updater_hash = n.get("updater_exe_sha256")
    next_updater_hash = n1.get("updater_exe_sha256")
    for digest in (old_hash, new_hash, updater_hash, next_updater_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest or "")):
            raise ValueError("release artifact identity invalid")
    for item in (n, n1):
        if not str(item.get("release_url") or "").startswith(f"https://github.com/{repository}/releases/"):
            raise ValueError("release URL outside independent repository")
    config = value.get("release_config") or {}
    hosts = set(config.get("trusted_hosts") or [])
    if not hosts or config.get("schema") != "english-root-software-update-config-v1":
        raise ValueError("release config contract missing")
    api_releases = []
    for item in (n, n1):
        api_receipt = item.get("api_receipt") or {}
        tag = str(item.get("tag") or "")
        if not tag or (api_receipt.get("url") or api_receipt.get("requested_url")) != f"https://api.github.com/repos/{repository}/releases/tags/{quote(tag, safe='')}":
            raise ValueError("raw repository release API endpoint missing")
        api = json.loads(receipt(api_receipt, trusted_hosts={"api.github.com"}).decode("utf-8-sig"))
        if (api.get("tag_name") != tag or api.get("html_url") != item.get("release_url")
                or api.get("draft") is not False or api.get("prerelease") is not False
                or int(api.get("id") or 0) <= 0 or not api.get("published_at")
                or not isinstance(api.get("assets"), list)):
            raise ValueError("raw release API does not prove an official published release")
        commit_receipt = item.get("commit_receipt") or {}
        if (commit_receipt.get("url") or commit_receipt.get("requested_url")) != f"https://api.github.com/repos/{repository}/commits/{quote(tag, safe='')}":
            raise ValueError("tag commit API endpoint missing")
        commit = json.loads(receipt(commit_receipt, trusted_hosts={"api.github.com"}).decode("utf-8-sig"))
        if (not re.fullmatch(r"[0-9a-f]{40}", str(commit.get("sha") or ""))
                or commit.get("sha") != item.get("source_sha")
                or commit.get("html_url") != f"https://github.com/{repository}/commit/{commit.get('sha')}"):
            raise ValueError("release tag does not prove exact repository commit")
        if item is n1 and commit["sha"] != source_sha:
            raise ValueError("release N+1 source does not match the accepted current head")
        api_releases.append(api)
    old_main = receipt(n.get("main_exe_receipt"), trusted_hosts=hosts, expected_hash=old_hash)
    old_updater = receipt(n.get("updater_exe_receipt"), trusted_hosts=hosts, expected_hash=updater_hash)
    for key, digest in (("main_exe_receipt", old_hash), ("updater_exe_receipt", updater_hash)):
        endpoint = n[key].get("url") or n[key].get("requested_url")
        if not str(endpoint or "").startswith(f"https://github.com/{repository}/releases/download/{quote(n['tag'], safe='')}/"):
            raise ValueError("release N artifact endpoint is outside the official release")
        if not any(asset.get("browser_download_url") == endpoint and asset.get("digest") == "sha256:" + digest
                   and int(asset.get("id") or 0) > 0 and asset.get("state") == "uploaded"
                   and int(asset.get("size") or 0) == len(old_main if key == "main_exe_receipt" else old_updater)
                   for asset in api_releases[0]["assets"]):
            raise ValueError("release N raw download is not its published asset")
    next_updater = receipt(n1.get("updater_exe_receipt"), trusted_hosts=hosts, expected_hash=next_updater_hash)
    next_updater_url = n1["updater_exe_receipt"].get("url") or n1["updater_exe_receipt"].get("requested_url")
    if not str(next_updater_url or "").startswith(f"https://github.com/{repository}/releases/download/{quote(n1['tag'], safe='')}/"):
        raise ValueError("release N+1 updater endpoint is outside the official release")
    if not any(asset.get("browser_download_url") == next_updater_url and asset.get("digest") == "sha256:" + next_updater_hash
               and int(asset.get("id") or 0) > 0 and asset.get("state") == "uploaded"
               and int(asset.get("size") or 0) == len(next_updater) for asset in api_releases[1]["assets"]):
        raise ValueError("release N+1 updater is not its official published asset")
    result = value.get("updater_result") or {}
    if (result.get("status") != "PASS" or result.get("action") != "UPDATED"
            or result.get("operation") != "software_update" or result.get("rollback_performed") is not False
            or result.get("old_exe_sha256") != old_hash or result.get("new_exe_sha256") != new_hash
            or version(result.get("from_version")) != version(n.get("version"))
            or version(result.get("to_version")) != version(n1.get("version"))):
        raise ValueError("updater transaction is not the accepted release transition")
    manifest_raw = receipt(result.get("manifest_receipt"), trusted_hosts=hosts)
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    if (manifest.get("schema") != "english-root-software-update-manifest-v1"
            or manifest.get("artifact_sha256") != new_hash
            or version(manifest.get("version")) != version(n1.get("version"))):
        raise ValueError("raw manifest does not bind to N+1")
    if (result["manifest_receipt"].get("url") or result["manifest_receipt"].get("requested_url")) != config.get("manifest_url"):
        raise ValueError("manifest receipt did not use configured endpoint")
    artifact = result.get("artifact_receipt") or {}
    if (artifact.get("url") or artifact.get("requested_url")) != manifest.get("artifact_url"):
        raise ValueError("artifact endpoint mismatch")
    artifact_bytes = int(manifest.get("artifact_bytes") or 0)
    if not 0 < artifact_bytes <= 512 * 1024 * 1024:
        raise ValueError("manifest artifact size invalid")
    artifact_raw = receipt(artifact, trusted_hosts=hosts, expected_hash=new_hash,
                           expected_size=artifact_bytes)
    if not str(manifest.get("artifact_url") or "").startswith(f"https://github.com/{repository}/releases/download/{quote(n1['tag'], safe='')}/"):
        raise ValueError("release N+1 artifact endpoint is outside the official release")
    if not any(asset.get("browser_download_url") == manifest.get("artifact_url")
               and asset.get("digest") == "sha256:" + new_hash
               and int(asset.get("id") or 0) > 0 and asset.get("state") == "uploaded"
               and int(asset.get("size") or 0) == len(artifact_raw)
               for asset in api_releases[1]["assets"]):
        raise ValueError("release N+1 artifact is not its published asset")
    execution = value.get("updater_execution") or {}
    if execution.get("independent_process") is not True or execution.get("updater_exe_sha256") != updater_hash or int(execution.get("pid") or 0) <= 0:
        raise ValueError("distinct updater process evidence missing")
    click = value.get("physical_update_click") or {}
    if (click.get("status") != "PASS" or click.get("label") != "一键更新"
            or click.get("method") != "physical_mouse" or click.get("from_exe_sha256") != old_hash
            or click.get("to_exe_sha256") != new_hash):
        raise ValueError("physical update transition evidence missing")
    post = value.get("post_update_self_test") or {}
    if post.get("status") != "PASS" or post.get("exe_sha256") != new_hash:
        raise ValueError("post-update exact health evidence missing")
    return {"new_exe_sha256": new_hash, "updater_exe_sha256": next_updater_hash,
            "transition_updater_exe_sha256": updater_hash,
            "new_exe_bytes": len(artifact_raw), "from_version": n["version"], "to_version": n1["version"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {"schema": "english-root-real-software-release-validation-v1",
              **run_identity(), "github_sha": args.source_sha, "repository": args.repository}
    if not args.input or not Path(args.input).is_file():
        report.update(status="BLOCKED", detail="Real independent N to N+1 release evidence unavailable")
    else:
        try:
            path = Path(args.input).resolve()
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)],
                                     capture_output=True, check=False)
            if tracked.returncode == 0:
                raise ValueError("release proof must be generated by the current run, not tracked")
            if tracked.returncode != 1:
                raise ValueError("cannot verify release proof is untracked in the current repository")
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            accepted = validate(value, repository=args.repository, source_sha=args.source_sha,
                                run_id=os.environ.get("GITHUB_RUN_ID", ""),
                                run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""))
            report.update(status="PASS", accepted=accepted)
        except Exception as exc:
            report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
