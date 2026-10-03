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
        service = Happy8Service(
            root,
            snapshot_builder=fixture_snapshot,
            science_validator=fixture_science_validator,
        )

        update = service.update_data()
        checks["update_commit"] = {"status": update.get("status")}
        current_before = service.status()
        checks["status_after_update"] = {"status": current_before.get("status")}

        prediction = service.predict_next()
        checks["prediction_no_false_edge"] = {
            "status": "PASS"
            if (
                prediction.get("edge_state") == "NO_EDGE"
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

        repair_clean = service.repair()
        checks["repair_clean"] = {
            "status": "PASS"
            if repair_clean.get("status") == "PASS"
            and repair_clean.get("action") == "NO_CHANGE_REQUIRED"
            else "FAIL"
        }

        service.store.current.write_text("{corrupt", encoding="utf-8")
        repair = service.repair()
        checks["repair_corrupt_pointer"] = {
            "status": "PASS"
            if repair.get("status") == "PASS"
            and repair.get("action") == "RESTORED_VERIFIED_GENERATION"
            and service.status().get("status") == "PASS"
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
    report = {"schema": "happy8-service-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
