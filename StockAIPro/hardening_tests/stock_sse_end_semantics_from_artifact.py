from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SOURCE_RUN_ID = 37315009304
SOURCE_ARTIFACT_ID = 11347866669
SOURCE_ARTIFACT_ZIP_SHA256 = "adafe0e238c4f08c9b139c8fee3cb9a79f7749ad9519ab5958d0c638a5513080"
EXPECTED_SOURCE_JSON_SHA256 = "c7e392293af96e22ee35c3920b3a9102dab18862eacfaf5ad185cda23ae23917"

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: stock_sse_end_semantics_from_artifact.py SOURCE_JSON OUTPUT_JSON", file=sys.stderr)
        return 2

    source = Path(argv[1])
    output = Path(argv[2])
    raw = source.read_bytes()
    source_sha = sha256_bytes(raw)
    if source_sha != EXPECTED_SOURCE_JSON_SHA256:
        raise SystemExit(
            f"source evidence hash mismatch: expected={EXPECTED_SOURCE_JSON_SHA256} actual={source_sha}"
        )
    data = json.loads(raw)

    cross = data["daily_interval_crosscheck"]["dates"]
    checks = [
        # Single-day interval: event start=end=2022-01-04 and official daily snapshot
        # says 605090 is suspended on that date. This is a direct counterexample
        # to treating endStopDate as an exclusive/resumption boundary.
        ("20220104", "605090", True),
        # Continuous interval 600072 ends 2022-01-12: active on end date,
        # absent on the following date.
        ("20220112", "600072", True),
        ("20220113", "600072", False),
        # Continuous interval 603227 ends 2022-01-17: active on end date,
        # absent on the following date.
        ("20220117", "603227", True),
        ("20220118", "603227", False),
    ]

    results = []
    for date, code, expected in checks:
        x = cross[date]
        snapshot = set(x["snapshot_active_stock_codes"])
        inclusive = set(x["event_active_inclusive_end_codes"])
        exclusive = set(x["event_active_exclusive_end_codes"])
        row = {
            "date": date,
            "code": code,
            "expected_active": expected,
            "snapshot_active": code in snapshot,
            "event_inclusive_active": code in inclusive,
            "event_exclusive_active": code in exclusive,
        }
        row["snapshot_matches_expected"] = row["snapshot_active"] == expected
        row["inclusive_matches_expected"] = row["event_inclusive_active"] == expected
        results.append(row)

    inclusive_pass = all(
        x["snapshot_matches_expected"] and x["inclusive_matches_expected"]
        for x in results
    )
    exclusive_counterexample = any(
        x["expected_active"]
        and x["snapshot_active"]
        and not x["event_exclusive_active"]
        for x in results
    )

    legacy_2026_contradiction = all(
        not cross[d]["inclusive_exact_match"]
        for d in ("20260924", "20260930")
    )

    adjudication = {
        "source_run_id": SOURCE_RUN_ID,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "source_artifact_zip_sha256": SOURCE_ARTIFACT_ZIP_SHA256,
        "source_json_sha256": source_sha,
        "stock_product_bytes_changed_in_source_run": data["adjudication"]["product_bytes_changed"],
        "event_interval_end_semantics": (
            "PASS_INCLUSIVE_SAMPLE"
            if inclusive_pass and exclusive_counterexample
            else "NOT VERIFIED"
        ),
        "legacy_daily_snapshot_2026": (
            "CONTRADICTED_SAMPLE" if legacy_2026_contradiction else "NOT VERIFIED"
        ),
        "historical_daily_suspension_state": "NOT VERIFIED",
        "shanghai_historical_st_pit": "NOT VERIFIED",
        "full_historical_st_pit": "NOT VERIFIED",
        "advanced_business": "NOT VERIFIED",
        "final_gate": "FAIL",
    }
    report = {
        "schema": "stock-sse-end-semantics-artifact-replay-v1",
        "source": {
            "run_id": SOURCE_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_zip_sha256": SOURCE_ARTIFACT_ZIP_SHA256,
            "json_sha256": source_sha,
        },
        "checks": results,
        "inclusive_pass": inclusive_pass,
        "exclusive_counterexample": exclusive_counterexample,
        "legacy_2026_contradiction": legacy_2026_contradiction,
        "adjudication": adjudication,
    }

    if not inclusive_pass or not exclusive_counterexample:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
    if adjudication["historical_daily_suspension_state"] != "NOT VERIFIED":
        raise SystemExit("strict non-promotion boundary violated")

    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(adjudication, ensure_ascii=True, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
