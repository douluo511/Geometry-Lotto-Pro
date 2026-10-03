from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.domain import Draw
from happy8.net_client import NetClient
from happy8.storage import canonical_json, sha256_json
from happy8.updater import _trusted_https, _version_tuple
from real_release_evidence import validate_real_release_evidence
from repository_independence_gate import REQUIRED_PATHS, evaluate_repository_independence
from final_artifact_evidence import validate_artifact_files, validate_final_artifact


def expect_raises(exc_type, fn) -> bool:
    try:
        fn()
    except exc_type:
        return True
    return False


def main() -> int:
    checks = {}

    draw = Draw.from_values(
        "2026261",
        "2026-09-28",
        [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    )
    checks["domain_valid_draw"] = {"status": "PASS" if len(draw.numbers) == 20 else "FAIL"}
    checks["domain_bad_issue"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "bad", "2026-09-28", range(1, 21)
        )) else "FAIL"
    }
    checks["domain_duplicate"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2026-09-28", [1] * 20
        )) else "FAIL"
    }
    checks["domain_out_of_range"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2026-09-28", list(range(1, 20)) + [81]
        )) else "FAIL"
    }
    checks["domain_future_date"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2099-01-01", range(1, 21)
        )) else "FAIL"
    }

    checks["version_numeric"] = {
        "status": "PASS" if _version_tuple("1.2.30") == (1, 2, 30) else "FAIL"
    }
    checks["version_invalid_fail_closed"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: _version_tuple("1.2-beta")) else "FAIL"
    }
    checks["trusted_https"] = {
        "status": "PASS"
        if _trusted_https("https://updates.example/a", {"updates.example"})
        and not _trusted_https("http://updates.example/a", {"updates.example"})
        and not _trusted_https("https://evil.example/a", {"updates.example"})
        else "FAIL"
    }

    value = {"b": 2, "a": [3, 1]}
    stable = canonical_json(value)
    checks["canonical_json_deterministic"] = {
        "status": "PASS"
        if stable == canonical_json(value) and sha256_json(value) == sha256_json({"a": [3, 1], "b": 2})
        else "FAIL"
    }

    client = NetClient(connect_timeout=1, read_timeout=2, max_attempts=99, backoff_base=0)
    checks["netclient_bounded_attempts"] = {
        "status": "PASS" if client.max_attempts == 4 else "FAIL"
    }
    checks["netclient_invalid_timeout"] = {
        "status": "PASS"
        if expect_raises(ValueError, lambda: NetClient(connect_timeout=0, read_timeout=1))
        else "FAIL"
    }

    source_sha = "a" * 40
    old_main = "1" * 64
    new_main = "2" * 64
    old_updater = "3" * 64
    new_updater = "4" * 64
    manifest_sha = "5" * 64
    dedicated_repo = "douluo511/Happy8"
    run_id = "123456"
    run_attempt = "1"
    valid_release = {
        "schema": "happy8-real-release-update-v1",
        "status": "PASS",
        "repository": dedicated_repo,
        "execution_context": {
            "producer": "happy8-real-release-acceptance-v1",
            "github_run_id": run_id,
            "github_run_attempt": run_attempt,
            "head_sha": source_sha,
        },
        "release_n": {
            "version": "0.2.0",
            "source_sha": "b" * 40,
            "release_url": "https://updates.example/releases/0.2.0",
            "main_exe_sha256": old_main,
            "updater_exe_sha256": old_updater,
        },
        "release_n1": {
            "version": "0.2.1",
            "source_sha": source_sha,
            "release_url": "https://updates.example/releases/0.2.1",
            "main_exe_sha256": new_main,
            "updater_exe_sha256": new_updater,
        },
        "update_config": {
            "schema": "happy8-update-config-v1",
            "manifest_url": "https://updates.example/latest.json",
            "trusted_hosts": ["updates.example"],
        },
        "manifest": {
            "schema": "happy8-update-manifest-v1",
            "version": "0.2.1",
            "artifact_url": "https://updates.example/Happy8-0.2.1.exe",
            "artifact_sha256": new_main,
            "artifact_bytes": 12345,
        },
        "updater_result": {
            "status": "PASS",
            "operation": "software_update",
            "action": "UPDATED",
            "from_version": "0.2.0",
            "to_version": "0.2.1",
            "old_exe_sha256": old_main,
            "new_exe_sha256": new_main,
            "manifest_receipt": {
                "url": "https://updates.example/latest.json",
                "http_status": 200,
                "bytes": 321,
                "sha256": manifest_sha,
            },
            "artifact_receipt": {
                "url": "https://updates.example/Happy8-0.2.1.exe",
                "http_status": 200,
                "bytes": 12345,
                "sha256": new_main,
            },
            "rollback_performed": False,
            "startup_recovery": {"status": "PASS", "action": "NO_INCOMPLETE_UPDATE"},
        },
        "updater_execution": {
            "independent_process": True,
            "updater_exe_sha256": old_updater,
            "main_exe_sha256_before": old_main,
        },
        "physical_update_click": {
            "status": "PASS",
            "label": "一键更新",
            "from_exe_sha256": old_main,
            "to_exe_sha256": new_main,
        },
        "post_update_self_test": {"status": "PASS", "exe_sha256": new_main},
        "tested_at": "2026-10-03T11:00:00Z",
    }

    valid_release_report = validate_real_release_evidence(
        valid_release,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    checks["real_release_valid_fixture"] = {
        "status": "PASS" if valid_release_report.get("status") == "PASS" else "FAIL"
    }
    status_only_report = validate_real_release_evidence(
        {"status": "PASS"},
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    checks["real_release_status_only_rejected"] = {
        "status": "PASS" if status_only_report.get("status") == "FAIL" else "FAIL"
    }
    bad_hash_release = json.loads(json.dumps(valid_release))
    bad_hash_release["updater_result"]["artifact_receipt"]["sha256"] = "6" * 64
    bad_hash_report = validate_real_release_evidence(
        bad_hash_release,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    checks["real_release_hash_mismatch_rejected"] = {
        "status": "PASS" if bad_hash_report.get("status") == "FAIL" else "FAIL"
    }
    wrong_run_release = json.loads(json.dumps(valid_release))
    wrong_run_release["execution_context"]["github_run_id"] = "999999"
    wrong_run_report = validate_real_release_evidence(
        wrong_run_release,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    checks["real_release_wrong_run_rejected"] = {
        "status": "PASS" if wrong_run_report.get("status") == "FAIL" else "FAIL"
    }

    repo_paths = set(REQUIRED_PATHS)
    dedicated_inventory = evaluate_repository_independence(
        repository=dedicated_repo,
        top_level={".github", "Happy8"},
        paths=repo_paths,
    )
    checks["repository_independence_valid_fixture"] = {
        "status": "PASS" if dedicated_inventory.get("status") == "PASS" else "FAIL"
    }
    shared_inventory = evaluate_repository_independence(
        repository="douluo511/Geometry-Lotto-Pro",
        top_level={".github", "Happy8"},
        paths=repo_paths,
    )
    checks["repository_independence_shared_blocked"] = {
        "status": "PASS" if shared_inventory.get("status") == "BLOCKED" else "FAIL"
    }
    extra_inventory = evaluate_repository_independence(
        repository=dedicated_repo,
        top_level={".github", "Happy8", "OtherProject"},
        paths=repo_paths,
    )
    checks["repository_independence_extra_project_rejected"] = {
        "status": "PASS" if extra_inventory.get("status") == "FAIL" else "FAIL"
    }

    shared_extra_inventory = evaluate_repository_independence(
        repository="douluo511/Geometry-Lotto-Pro",
        top_level={".github", "Happy8", "OtherProject"},
        paths=repo_paths,
    )
    checks["repository_independence_shared_stays_blocked"] = {
        "status": "PASS" if shared_extra_inventory.get("status") == "BLOCKED" else "FAIL"
    }

    windows_fixture = {
        "status": "PASS",
        "source_sha": source_sha,
        "exe_sha256": new_main,
        "rebuild_sha256": new_main,
        "updater_sha256": new_updater,
        "updater_rebuild_sha256": new_updater,
        "same_hash": True,
        "updater_same_hash": True,
    }
    physical_fixture = {
        "status": "PASS",
        "same_hash": True,
        "exe_sha256_before": new_main,
        "exe_sha256_after": new_main,
    }
    same_fixture = {
        "status": "PASS",
        "exe_sha256": new_main,
        "build_sha256": new_main,
        "physical_gui_sha256": new_main,
    }
    final_manifest = {
        "schema": "happy8-final-artifact-v1",
        "status": "PASS",
        "repository": dedicated_repo,
        "source_sha": source_sha,
        "execution_context": {
            "producer": "happy8-final-artifact-freeze-v1",
            "github_run_id": run_id,
            "github_run_attempt": run_attempt,
            "head_sha": source_sha,
        },
        "formal_release": {
            "unique": True,
            "release_id": "release-0.2.1",
            "release_url": "https://updates.example/releases/0.2.1",
            "version": "0.2.1",
        },
        "exact_exe": {
            "filename": "Geometry_Lotto_Pro_Happy8.exe",
            "sha256": new_main,
            "bytes": 50000,
        },
        "updater_exe": {
            "filename": "Geometry_Lotto_Pro_Happy8_Updater.exe",
            "sha256": new_updater,
            "bytes": 40000,
        },
        "created_at": "2026-10-03T11:00:00Z",
    }
    final_valid = validate_final_artifact(
        final_manifest,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        windows=windows_fixture,
        physical_gui=physical_fixture,
        same_hash=same_fixture,
        real_release=valid_release_report,
    )
    checks["final_artifact_valid_fixture"] = {
        "status": "PASS" if final_valid.get("status") == "PASS" else "FAIL"
    }
    wrong_release_url_manifest = json.loads(json.dumps(final_manifest))
    wrong_release_url_manifest["formal_release"]["release_url"] = "https://updates.example/releases/other"
    final_url_mismatch = validate_final_artifact(
        wrong_release_url_manifest,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        windows=windows_fixture,
        physical_gui=physical_fixture,
        same_hash=same_fixture,
        real_release=valid_release_report,
    )
    checks["final_artifact_release_url_mismatch_rejected"] = {
        "status": "PASS" if final_url_mismatch.get("status") == "FAIL" else "FAIL"
    }
    final_status_only = validate_final_artifact(
        {"status": "PASS"},
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        windows=windows_fixture,
        physical_gui=physical_fixture,
        same_hash=same_fixture,
        real_release=valid_release_report,
    )
    checks["final_artifact_status_only_rejected"] = {
        "status": "PASS" if final_status_only.get("status") == "FAIL" else "FAIL"
    }
    bad_final_manifest = json.loads(json.dumps(final_manifest))
    bad_final_manifest["exact_exe"]["sha256"] = "7" * 64
    final_hash_mismatch = validate_final_artifact(
        bad_final_manifest,
        repository=dedicated_repo,
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        windows=windows_fixture,
        physical_gui=physical_fixture,
        same_hash=same_fixture,
        real_release=valid_release_report,
    )
    checks["final_artifact_hash_mismatch_rejected"] = {
        "status": "PASS" if final_hash_mismatch.get("status") == "FAIL" else "FAIL"
    }

    with tempfile.TemporaryDirectory(prefix="happy8-final-files-") as td:
        td_path = Path(td)
        main_path = td_path / "Geometry_Lotto_Pro_Happy8.exe"
        updater_path = td_path / "Geometry_Lotto_Pro_Happy8_Updater.exe"
        main_bytes = b"main-final-artifact-bytes"
        updater_bytes = b"updater-final-artifact-bytes"
        main_path.write_bytes(main_bytes)
        updater_path.write_bytes(updater_bytes)
        file_manifest = json.loads(json.dumps(final_manifest))
        file_manifest["exact_exe"]["sha256"] = hashlib.sha256(main_bytes).hexdigest()
        file_manifest["exact_exe"]["bytes"] = len(main_bytes)
        file_manifest["updater_exe"]["sha256"] = hashlib.sha256(updater_bytes).hexdigest()
        file_manifest["updater_exe"]["bytes"] = len(updater_bytes)
        physical_files = validate_artifact_files(
            file_manifest,
            main_exe=main_path,
            updater_exe=updater_path,
        )
        checks["final_artifact_physical_files_valid"] = {
            "status": "PASS" if physical_files.get("status") == "PASS" else "FAIL"
        }
        bad_bytes_manifest = json.loads(json.dumps(file_manifest))
        bad_bytes_manifest["exact_exe"]["bytes"] += 1
        bad_bytes = validate_artifact_files(
            bad_bytes_manifest,
            main_exe=main_path,
            updater_exe=updater_path,
        )
        checks["final_artifact_byte_mismatch_rejected"] = {
            "status": "PASS" if bad_bytes.get("status") == "FAIL" else "FAIL"
        }

    status = "PASS" if checks and all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-unit-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
