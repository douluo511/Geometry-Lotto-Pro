UPDATER_CHECKS = frozenset({
    "manifest_https_trust_fail_closed", "manifest_and_artifact_contract", "bad_hash_fail_closed",
    "truncated_download_fail_closed", "non_monotonic_no_replace", "normal_atomic_update",
    "offline_manifest_fail_closed", "download_interruption_fail_closed", "permission_replace_failure_rolls_back",
    "main_program_occupied_fail_closed", "health_failure_rolls_back", "rollback_failure_retains_recovery_state",
    "restart_recovery_restores_previous_exe",
})


def validate_atomic_checks(report):
    checks = report.get("checks")
    return (report.get("schema") == "english-root-updater-gate-v1" and report.get("status") == "PASS"
            and isinstance(checks, dict) and set(checks) == UPDATER_CHECKS
            and all(isinstance(checks[name], dict) and checks[name].get("status") == "PASS" for name in UPDATER_CHECKS))
