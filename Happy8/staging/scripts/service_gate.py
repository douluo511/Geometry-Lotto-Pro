from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.services import Happy8Service
from happy8.storage import sha256_bytes, sha256_json


def fixture_snapshot():
    draws = [{
        "issue": "2026261",
        "draw_date": "2026-09-28",
        "numbers": [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    }]
    sh_name = "shanghai_2026200_2026297.html"
    raw = {
        sh_name: b"<html>shanghai service fixture</html>" * 100,
        "jiangsu_welfare_lottery.html": b"<html>jiangsu service fixture</html>" * 100,
    }
    manifest = [{
        "sequence": 1,
        "start_issue": "2026200",
        "end_issue": "2026297",
        "filename": sh_name,
        "http_status": 200,
        "sha256": sha256_bytes(raw[sh_name]),
        "bytes": len(raw[sh_name]),
        "draw_count": 1,
        "first_issue": "2026261",
        "last_issue": "2026261",
        "url": "https://www.swlc.net.cn/lottery/kl8.html?view=previous&start_issue=2026200&end_issue=2026297",
    }]
    report = {
        "schema": "happy8-staging-official-network-v4",
        "status": "PASS",
        "latest": draws[-1],
        "history_count": 1,
        "draws": draws,
        "canonical_hash": sha256_json(draws),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "history_source": "shanghai_welfare_lottery",
        "history_raw_manifest": manifest,
        "shanghai_raw_manifest": manifest,
        "verification": "SHANGHAI_FULL_HISTORY_PLUS_JIANGSU_CURRENT",
        "source_receipts": [
            {
                "source": "shanghai_welfare_lottery",
                "raw_sha256": sha256_json(manifest),
                "bytes": len(raw[sh_name]),
                "status": "PASS",
            },
            {
                "source": "jiangsu_welfare_lottery",
                "raw_sha256": sha256_bytes(raw["jiangsu_welfare_lottery.html"]),
                "bytes": len(raw["jiangsu_welfare_lottery.html"]),
                "status": "PASS",
            },
        ],
    }
    return report, raw


def fixture_science_validator(draws, *, canonical_hash: str):
    if not draws or not canonical_hash:
        raise RuntimeError("fixture science validator requires verified inputs")
    return {
        "status": "PASS",
        "software_verdict": "PASS",
        "edge_state": "NO_EDGE",
        "dan_state": "NULL_DAN",
        "formal_dan": [],
        "production_model": "uniform_baseline",
        "test_fixture": True,
    }


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="happy8-service-gate-") as td:
        root = Path(td)
        def fixture_software_update_launcher():
            return {
                "status": "PASS",
                "operation": "software_update",
                "action": "UPDATER_HANDOFF",
                "test_fixture": True,
            }

        def healthy_repair_environment():
            return {
                "status": "PASS",
                "checks": {
                    "release_config": {"status": "PASS"},
                    "network_config": {"status": "PASS"},
                    "version_contract": {"status": "PASS"},
                    "updater_exe": {"status": "PASS"},
                    "main_exe": {"status": "PASS"},
                },
            }

        service = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=fixture_science_validator,
            software_update_launcher=fixture_software_update_launcher,
            repair_environment_probe=healthy_repair_environment,
        )

        software_update = service.software_update()
        checks["software_update_handoff"] = {
            "status": "PASS"
            if (
                software_update.get("status") == "PASS"
                and software_update.get("action") == "UPDATER_HANDOFF"
            )
            else "FAIL"
        }

        update = service.update_data()
        checks["update_commit"] = {"status": update.get("status")}
        current_before = service.status()
        checks["status_after_update"] = {"status": current_before.get("status")}

        prediction = service.predict_next()
        checks["prediction_no_false_edge"] = {
            "status": "PASS"
            if (
                prediction.get("status") == "PASS"
                and prediction.get("edge_state") == "NO_EDGE"
                and prediction.get("dan_state") == "NULL_DAN"
                and not prediction.get("formal_dan")
                and prediction.get("label") == "STRUCTURED_CANDIDATE_ONLY"
                and len(prediction.get("candidate10_research_only") or []) == 10
            )
            else "FAIL"
        }
        repeated = service.predict_next()
        checks["prediction_freeze_idempotent"] = {
            "status": "PASS"
            if prediction.get("freeze_hash") == repeated.get("freeze_hash")
            else "FAIL"
        }

        advanced = service.advanced_analysis()
        checks["advanced_analysis"] = {
            "status": "PASS"
            if (
                advanced.get("status") == "PASS"
                and advanced.get("report", {}).get("software_verdict") == "PASS"
            )
            else "FAIL"
        }

        service.cache.mkdir(parents=True, exist_ok=True)
        (service.cache / "poison.tmp").write_bytes(b"cache-poison")
        repair_clean = service.repair()
        required_components = {
            "data_store", "index_pointer", "missing_files", "cache",
            "configuration", "network_configuration", "version_contract",
            "data_integrity",
        }
        checks["repair_clean_full_contract"] = {
            "status": "PASS"
            if repair_clean.get("status") == "PASS"
            and repair_clean.get("action") == "REPAIR_COMPLETE"
            and required_components.issubset(set(repair_clean.get("components") or {}))
            and all(
                (repair_clean.get("components") or {}).get(name, {}).get("status") == "PASS"
                for name in required_components
            )
            and repair_clean.get("post_repair_self_check", {}).get("status") == "PASS"
            and repair_clean.get("user_data_deleted") is False
            and not (service.cache / "poison.tmp").exists()
            else "FAIL"
        }

        service.store.current.write_text("{corrupt", encoding="utf-8")
        repair = service.repair()
        checks["repair_corrupt_index_pointer"] = {
            "status": "PASS"
            if repair.get("status") == "PASS"
            and repair.get("store_repaired") is True
            and repair.get("components", {}).get("index_pointer", {}).get("status") == "PASS"
            and repair.get("post_repair_self_check", {}).get("status") == "PASS"
            and service.status().get("status") == "PASS"
            else "FAIL"
        }

        service.store.current.unlink()
        missing_pointer_repair = service.repair()
        checks["repair_missing_required_pointer"] = {
            "status": "PASS"
            if missing_pointer_repair.get("status") == "PASS"
            and missing_pointer_repair.get("store_repaired") is True
            and missing_pointer_repair.get("components", {}).get("missing_files", {}).get("status") == "PASS"
            and service.status().get("status") == "PASS"
            else "FAIL"
        }

        blocked_repair = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=fixture_science_validator,
            repair_environment_probe=lambda: {
                "status": "BLOCKED",
                "checks": {
                    "release_config": {"status": "BLOCKED", "detail": "injected missing trusted release config"},
                    "network_config": {"status": "BLOCKED", "detail": "injected missing trusted release endpoint"},
                    "version_contract": {"status": "PASS"},
                    "updater_exe": {"status": "PASS"},
                    "main_exe": {"status": "PASS"},
                },
            },
        )
        blocked = blocked_repair.repair()
        checks["repair_external_config_blocked_not_pass"] = {
            "status": "PASS"
            if blocked.get("status") == "BLOCKED"
            and blocked.get("action") == "LOCAL_REPAIR_COMPLETE_EXTERNAL_BLOCKER"
            and blocked.get("components", {}).get("configuration", {}).get("status") == "BLOCKED"
            and blocked.get("components", {}).get("network_configuration", {}).get("status") == "BLOCKED"
            and blocked.get("post_repair_self_check", {}).get("status") == "PASS"
            else "FAIL"
        }

        bad_version = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=fixture_science_validator,
            repair_environment_probe=lambda: {
                "status": "FAIL",
                "checks": {
                    "release_config": {"status": "PASS"},
                    "network_config": {"status": "PASS"},
                    "version_contract": {"status": "FAIL", "detail": "injected version mismatch"},
                },
            },
        ).repair()
        checks["repair_version_mismatch_fail_closed"] = {
            "status": "PASS"
            if bad_version.get("status") == "FAIL"
            and bad_version.get("components", {}).get("version_contract", {}).get("status") == "FAIL"
            else "FAIL"
        }

        snapshot = service.store.read_current_snapshot()
        raw_dir = service.store.generations / snapshot["generation_id"] / "RAW"
        raw_file = next(path for path in raw_dir.iterdir() if path.is_file())
        original_raw = raw_file.read_bytes()
        raw_file.write_bytes(original_raw + b"tamper")
        integrity_failure = service.repair()
        checks["repair_unrecoverable_data_corruption_fail_closed"] = {
            "status": "PASS"
            if integrity_failure.get("status") == "FAIL"
            and integrity_failure.get("components", {}).get("data_integrity", {}).get("status") == "FAIL"
            and raw_file.exists()
            else "FAIL"
        }
        raw_file.write_bytes(original_raw)
        restored_after_tamper = service.repair()
        checks["repair_post_tamper_recovery_self_check"] = {
            "status": "PASS"
            if restored_after_tamper.get("status") == "PASS"
            and restored_after_tamper.get("post_repair_self_check", {}).get("status") == "PASS"
            else "FAIL"
        }

        stable_hash = service.status().get("canonical_hash")

        def failing_builder():
            raise RuntimeError("simulated upstream failure")

        failed_service = Happy8Service(
            root,
            snapshot_builder=failing_builder,
            science_validator=fixture_science_validator,
        )
        try:
            failed_service.update_data()
            checks["failed_update_fail_closed"] = {"status": "FAIL"}
        except RuntimeError:
            checks["failed_update_fail_closed"] = {
                "status": "PASS"
                if failed_service.status().get("canonical_hash") == stable_hash
                else "FAIL"
            }


        def failing_software_update_launcher():
            return {"status": "FAIL", "operation": "software_update", "action": "BLOCKED"}

        failed_updater = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=fixture_science_validator,
            software_update_launcher=failing_software_update_launcher,
        )
        try:
            failed_updater.software_update()
            checks["software_update_fail_closed"] = {"status": "FAIL"}
        except RuntimeError:
            checks["software_update_fail_closed"] = {"status": "PASS"}

        def failing_science_validator(draws, *, canonical_hash: str):
            raise RuntimeError("simulated science failure")

        failed_science = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=failing_science_validator,
        )
        for operation_name, operation in (
            ("prediction_science_failure_fail_closed", failed_science.predict_next),
            ("advanced_science_failure_fail_closed", failed_science.advanced_analysis),
        ):
            try:
                operation()
                checks[operation_name] = {"status": "FAIL"}
            except RuntimeError:
                checks[operation_name] = {"status": "PASS"}

    status = "PASS" if checks and all(x.get("status") == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-service-gate-v2", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
