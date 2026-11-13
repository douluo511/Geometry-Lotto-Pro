"""Synthetic checks for exact-head, cross-OS V4.7 test coverage evidence."""
import unittest

from research.harness_v46.ci_coverage import (
    CoverageBlocked, check_platform, check_matrix, WINDOWS_ONLY,
)

SHA = "a" * 40


def record(platform, passed, skipped=(), sha=SHA, failures=(), errors=()):
    return {
        "schema": "V47_CI_COVERAGE_V1",
        "platform": platform,
        "head_sha": sha,
        "passed": sorted(passed),
        "skipped": {x: "native Windows API" for x in skipped},
        "failures": list(failures),
        "errors": list(errors),
        "expected_failures": [],
        "unexpected_successes": [],
        "tests_run": len(passed) + len(skipped) + len(failures) + len(errors),
    }


class MatrixCoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.common = {"test_alpha", "test_beta"}
        self.all = self.common | WINDOWS_ONLY

    def test_windows_must_execute_every_native_case_with_zero_skips(self):
        report = record("windows", self.all)
        self.assertEqual(check_platform(report), len(self.all))
        with self.assertRaisesRegex(CoverageBlocked, "WINDOWS_SKIPPED"):
            check_platform(record("windows", self.all - {next(iter(WINDOWS_ONLY))},
                                  [next(iter(WINDOWS_ONLY))]))

    def test_linux_has_only_allowlisted_native_windows_skips(self):
        self.assertEqual(check_platform(record("linux", self.common, WINDOWS_ONLY)),
                         len(self.all))
        with self.assertRaisesRegex(CoverageBlocked, "NON_WINDOWS_UNEXPECTED_SKIP"):
            check_platform(record("linux", self.common, WINDOWS_ONLY | {"test_alpha"}))

    def test_linux_cannot_hide_missing_native_case(self):
        with self.assertRaisesRegex(CoverageBlocked, "WINDOWS_SKIP_SET_MISMATCH"):
            check_platform(record("linux", self.common, WINDOWS_ONLY - {next(iter(WINDOWS_ONLY))}))

    def test_real_cross_platform_roster_has_no_unexecuted_tests(self):
        ubuntu = record("linux", self.common, WINDOWS_ONLY)
        windows = record("windows", self.all)
        result = check_matrix(ubuntu, windows)
        self.assertEqual(result["skipped_on_all_platforms"], 0)
        self.assertEqual(result["linux_skipped_executed_on_windows"], len(WINDOWS_ONLY))
        self.assertEqual(result["status"], "PASS")

    def test_missing_windows_execution_is_hard_failure(self):
        ubuntu = record("linux", self.common, WINDOWS_ONLY)
        windows = record("windows", self.all - {next(iter(WINDOWS_ONLY))})
        with self.assertRaisesRegex(CoverageBlocked, "CROSS_PLATFORM_ROSTER_MISMATCH"):
            check_matrix(ubuntu, windows)

    def test_mixed_sha_is_hard_failure(self):
        with self.assertRaisesRegex(CoverageBlocked, "HEAD_SHA_MISMATCH"):
            check_matrix(record("linux", self.common, WINDOWS_ONLY),
                         record("windows", self.all, sha="b" * 40))

    def test_any_error_or_failure_blocks(self):
        with self.assertRaisesRegex(CoverageBlocked, "FAILED_OR_INCOMPLETE"):
            check_platform(record("windows", self.all, errors=["test_import"]))
        with self.assertRaisesRegex(CoverageBlocked, "FAILED_OR_INCOMPLETE"):
            check_platform(record("windows", self.all, failures=["test_logic"]))

    def test_unknown_platform_not_accepted(self):
        with self.assertRaisesRegex(CoverageBlocked, "UNKNOWN_PLATFORM"):
            check_platform(record("macos", self.all))


if __name__ == "__main__":
    unittest.main()
