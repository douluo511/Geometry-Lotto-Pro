# Superpowers TDD execution — score-receipt crash safety / Issue #468

Single integration branch: PR #467. No new Harness, branch, or PR. Original
eight formal slots and fixed NULL stay untouched.

1. **Investigate** actual writer `closed_loop._write_once` and
   `advance_workspace` idempotent restart/roster flow. Hypothesis:
   `xb` creates a public final pathname *before* `fsync`; failure
   leaves an incomplete official-looking result.
2. **RED** add `test_closed_loop_atomic_receipts.py` with a real
   injected `os.fsync` failure and a no-final-receipt assertion.
   Verify original Ubuntu/Windows CI failure and record full SHA/job log.
3. **GREEN** implement only staged, fsynced, atomic no-replace publish.
   Keep score semantics and unfrozen model code unchanged.
4. **Regression** run full V4.7 synthetic suite on Ubuntu/Windows for the
   exact code SHA. Test idempotence, mismatched receipts and racing writes.
5. **Integration** simulate exception and retry via
   `advance_workspace` against a real fixture SQLite ledger; then
   test two concurrent read-only scorers and all 12 original arms.
6. **Audit** inspect final PR diff and both original job logs, compare
   exact checkout SHA, record completed/failure evidence in Issue #468
   and PR #467. Independent second-reviewer resource is not connected:
   mark `INDEPENDENT_CODE_REVIEW=NOT_VERIFIED`, do not pose as one.
7. **Gate** synthetic test success is component only; require separately
   witnessed durable Windows power-loss recovery, trusted official
   source/cutoff, approved RFC3161 external signature including accuracy,
   real postdraw results and complete preregistered future D2 cohort for
   final project admission.

The failure injection is NOT a physical power-loss experiment; no real
forecast, official outcome or positive-edge conclusion is produced.
