"""Fail-closed cross-platform coverage gate for the V4.7 synthetic test suite.

The nineteen native Windows tests cannot execute on Ubuntu. They MUST all
execute and pass in a genuine Windows CI job at the exact same commit. Missing
or newly skipped cases fail the build, rather than being waved away by a green
unittest exit code. No lottery forecasts or mutable ledgers are touched.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


SCHEMA = "V47_CI_COVERAGE_V1"
WINDOWS_ONLY = frozenset({
    "test_audit_control.AuditControlTests.test_real_windows_junction_is_refused",
    "test_closed_loop_scheduler.ClosedLoopSchedulerTests.test_bot_actual_powershell_tick_freezes_two_game_issues_without_shared_run",
    "test_closed_loop_scheduler.ClosedLoopSchedulerTests.test_bot_source_blocked_ssq_still_processes_dlt_without_fake_ssq",
    "test_closed_loop_scheduler.ClosedLoopSchedulerTests.test_real_windows_optin_operational_mode_persists_two_attempts",
    "test_closed_loop_scheduler.ClosedLoopSchedulerTests.test_windows_powershell_ast_syntax",
    "test_closed_loop_scheduler.ClosedLoopSchedulerTests.test_windows_real_dry_run_does_not_register_task",
    "test_desktop.DesktopTests.test_pythonw_missing_config_flag_and_bad_arguments_are_visible",
    "test_desktop.DesktopTests.test_pythonw_missing_config_retains_receipt_and_shows_native_error",
    "test_desktop.DesktopTests.test_pythonw_startup_diagnostic_does_not_overwrite_and_keeps_original_error_visible",
    "test_desktop.DesktopTests.test_pythonw_startup_without_result_path_uses_exclusive_config_parent_receipt",
    "test_desktop.DesktopTests.test_real_native_buttons_use_inert_callbacks_and_close_waits_for_receipt",
    "test_desktop.DesktopTests.test_real_native_close_waits_for_explicit_acknowledgement_after_fsync_failure",
    "test_recent_observation.RecentObservationTests.test_windows_long_output_directory_captures_and_replays",
    "test_schedule.SchedulerTests.test_windows_powershell_syntax",
    "test_tsa_transport.TSATransportTests.test_windows_long_output_path_preserves_response",
    "test_windows_operational_snapshots.WindowsOperationalSnapshotTests.test_bad_ssq_snapshot_still_freezes_only_valid_synthetic_dlt",
    "test_windows_operational_snapshots.WindowsOperationalSnapshotTests.test_explicit_paths_freeze_both_synthetic_games_and_retry_reuses_cards",
    "test_windows_operational_snapshots.WindowsOperationalSnapshotTests.test_new_paths_reject_wrong_mode_and_preserve_legacy_conflict",
    "test_windows_operational_snapshots.WindowsOperationalSnapshotTests.test_timeout_above_host_budget_rejects_before_python_or_log_start",
})


class CoverageBlocked(ValueError):
    """Do not accept a success statement with an unexecuted test."""


def _check_report_shape(report: dict) -> None:
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise CoverageBlocked("INVALID_REPORT_SCHEMA")
    if (not isinstance(report.get("head_sha"), str)
            or re.fullmatch(r"[0-9a-f]{40}", report["head_sha"]) is None):
        raise CoverageBlocked("INVALID_EXACT_HEAD_SHA")
    if (not isinstance(report.get("passed"), list)
            or not isinstance(report.get("skipped"), dict)):
        raise CoverageBlocked("INVALID_TEST_ROSTER")
    for field in ("failures", "errors", "expected_failures", "unexpected_successes"):
        if not isinstance(report.get(field), list):
            raise CoverageBlocked("INVALID_TEST_ROSTER")
    entries = list(report["passed"]) + list(report["skipped"]) + sum(
        (report[f] for f in ("failures", "errors", "expected_failures", "unexpected_successes")), [])
    if any(not isinstance(x, str) or not x for x in entries) or len(set(entries)) != len(entries):
        raise CoverageBlocked("DUPLICATE_OR_INVALID_TEST_ID")
    if (type(report.get("tests_run")) is not int
            or report["tests_run"] != len(entries)):
        raise CoverageBlocked("TEST_COUNT_MISMATCH")


def check_platform(report: dict) -> int:
    """Validate a platform-local report without silently tolerating a skip."""
    _check_report_shape(report)
    if any(report[field] for field in
           ("failures", "errors", "expected_failures", "unexpected_successes")):
        raise CoverageBlocked("FAILED_OR_INCOMPLETE_TEST_CASES")
    passed, skipped = set(report["passed"]), set(report["skipped"])
    platform = report.get("platform")
    if platform == "windows":
        if skipped:
            raise CoverageBlocked("WINDOWS_SKIPPED_TESTS")
        if not WINDOWS_ONLY <= passed:
            raise CoverageBlocked("WINDOWS_NATIVE_TEST_NOT_EXECUTED")
    elif platform == "linux":
        if skipped - WINDOWS_ONLY:
            raise CoverageBlocked("NON_WINDOWS_UNEXPECTED_SKIP")
        if skipped != WINDOWS_ONLY:
            raise CoverageBlocked("WINDOWS_SKIP_SET_MISMATCH")
    else:
        raise CoverageBlocked("UNKNOWN_PLATFORM")
    return report["tests_run"]


def check_matrix(linux: dict, windows: dict) -> dict:
    """A platform skip is acceptable only when that exact case passed on Windows."""
    check_platform(linux)
    check_platform(windows)
    if linux["platform"] != "linux" or windows["platform"] != "windows":
        raise CoverageBlocked("INVALID_MATRIX_PLATFORM_ORDER")
    if linux["head_sha"] != windows["head_sha"]:
        raise CoverageBlocked("HEAD_SHA_MISMATCH")
    linux_all = set(linux["passed"]) | set(linux["skipped"])
    win_all = set(windows["passed"]) | set(windows["skipped"])
    if linux_all != win_all:
        raise CoverageBlocked("CROSS_PLATFORM_ROSTER_MISMATCH")
    if not set(linux["skipped"]) <= set(windows["passed"]):
        raise CoverageBlocked("CROSS_PLATFORM_UNEXECUTED_SKIP")
    return {
        "status": "PASS", "schema": "V47_CI_MATRIX_COVERAGE_V1",
        "head_sha": linux["head_sha"], "unique_core_tests": len(win_all),
        "linux_skipped_executed_on_windows": len(linux["skipped"]),
        "skipped_on_all_platforms": len(set(linux["skipped"]) & set(windows["skipped"])),
        "errors": 0, "failures": 0,
        "formal_A": 0, "edge": "NO_EDGE",
    }


class RecordingResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.passed: list[str] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def _run(output: Path) -> None:
    platform = "windows" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else "unsupported"
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    suite = unittest.defaultTestLoader.discover("research/harness_v46/tests", pattern="test*.py")
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
    record = {
        "schema": SCHEMA, "platform": platform, "head_sha": head_sha,
        "passed": sorted(result.passed),
        "skipped": {case.id(): reason for case, reason in result.skipped},
        "failures": [case.id() for case, _ in result.failures],
        "errors": [case.id() for case, _ in result.errors],
        "expected_failures": [case.id() for case, _ in result.expectedFailures],
        "unexpected_successes": [case.id() for case in result.unexpectedSuccesses],
        "tests_run": result.testsRun,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as out:
        json.dump(record, out, sort_keys=True, indent=2)
        out.write("\n")
    count = check_platform(record)
    print(json.dumps({
        "platform": platform, "head_sha": head_sha,
        "tests_run": count, "passed": len(record["passed"]),
        "skipped_native_executed_in_windows_matrix": len(record["skipped"]),
        "coverage_condition": "CROSS_PLATFORM_CHECK_PENDING",
        "formal_A": 0, "edge": "NO_EDGE",
    }, sort_keys=True))


def _matrix(linux_path: Path, windows_path: Path) -> None:
    linux = json.loads(linux_path.read_text(encoding="utf-8"))
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    report = check_matrix(linux, windows)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if report["head_sha"] != actual:
        raise CoverageBlocked("MATRIX_NOT_EXACT_CHECKOUT_SHA")
    print(json.dumps(report, sort_keys=True))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    matrix = sub.add_parser("matrix")
    matrix.add_argument("--linux", type=Path, required=True)
    matrix.add_argument("--windows", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "run":
            _run(args.output)
        else:
            _matrix(args.linux, args.windows)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"V47_CI_COVERAGE_BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
