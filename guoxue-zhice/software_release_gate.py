from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input")
    p.add_argument("--repository", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    if not args.input or not Path(args.input).exists():
        report = {
            "schema": "guoxue-real-software-release-validation-v1",
            "status": "BLOCKED",
            "github_sha": os.environ.get("GITHUB_SHA"),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "detail": "real independent production Release N→N+1 evidence is unavailable",
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        checks = {}
        def put(name, ok, **extra):
            checks[name] = {"status": "PASS" if ok else "FAIL", **extra}

        put("schema", isinstance(value, dict) and value.get("schema") == "guoxue-real-software-update-v1")
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

        status = "PASS" if checks and all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
        report = {
            "schema": "guoxue-real-software-release-validation-v1",
            "status": status,
            "github_sha": os.environ.get("GITHUB_SHA"),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "checks": checks,
        }
    except Exception as exc:
        report = {
            "schema": "guoxue-real-software-release-validation-v1",
            "status": "FAIL",
            "github_sha": os.environ.get("GITHUB_SHA"),
            "repository": args.repository,
            "source_sha": args.source_sha,
            "error": f"{type(exc).__name__}: {exc}",
        }

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
