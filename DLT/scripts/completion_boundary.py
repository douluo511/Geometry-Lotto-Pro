"""Static prechecks are not complete business or runtime coverage evidence."""
from __future__ import annotations

SCHEMA = "dlt-static-interface-precheck-v2"
SCOPE = "STATIC_INTERFACE_PRECHECK_ONLY"


def completion_states(report: dict) -> dict[str, str]:
    checks = report.get("checks")
    valid = (
        report.get("schema") == SCHEMA
        and report.get("scope") == SCOPE
        and report.get("status") == "PASS"
        and isinstance(checks, list) and bool(checks)
        and all(isinstance(row, dict) and row.get("status") == "PASS"
                and isinstance(row.get("name"), str) and bool(row["name"])
                for row in checks)
    )
    if valid:
        valid = len({row["name"] for row in checks}) == len(checks)
    state = "PENDING" if valid else "FAIL"
    # Even a forged top-level PASS cannot promote source inspection to runtime
    # proof. Complete, approved business/entry evidence remains a separate gap.
    return {"business_content": state, "no_shell": state}


def static_report(checks: list[dict], app_version: str) -> dict:
    report = {
        "schema": SCHEMA,
        "scope": SCOPE,
        "status": "PASS",
        "app_version": app_version,
        "checks": checks,
        "engineering_completion": None,
        "business_completion": None,
        "overall_completion": None,
        "release_authorized": False,
        "reason": "Source symbols/strings cannot prove an approved complete business inventory or per-entry runtime, negative-path and data evidence.",
    }
    states = completion_states(report)
    if "FAIL" in states.values():
        report["status"] = "FAIL"
    report.update(states)
    return report
