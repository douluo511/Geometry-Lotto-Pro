from __future__ import annotations

import os
import re


def run_identity() -> dict:
    return {"github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}


def current_report(report: dict, source_sha: str | None) -> bool:
    identity = run_identity()
    return bool(re.fullmatch(r"[0-9a-f]{40}", source_sha or "")
                and all(identity.values()) and report.get("github_sha") == source_sha
                and all(str(report.get(key)) == str(value) for key, value in identity.items()))


def gate_status(report: dict, source_sha: str | None) -> str:
    if not current_report(report, source_sha):
        return "FAIL"
    return report.get("status") if report.get("status") in {"PASS", "FAIL", "NOT VERIFIED", "BLOCKED"} else "FAIL"
