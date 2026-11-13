# V4.7 isolated maths/physics-audit execution plan

Scope: one incremental stacked PR on PR #467, no changes to formal selectors, seed, schedule, ledger, result source, cutoff or time-seal policy.

1. Audit the #467 exact parent SHA and original model registry, including Pairwise-D2 and fixed SHA256 Random NULL. Preserve the original HEAD; no force push.
2. Add synthetic tests first: D2 exact rational arithmetic, registered six-model contract, elastic/inelastic/contact negatives. Capture GitHub Actions RED test logs.
3. Add `physics_audit.py` implementing a pure read-only audit and basic rigid-sphere contact kernel. Keep all outputs `SHADOW`, `formal_A=0`, `NO_EDGE`.
4. Add adversarial patched score test and false provenance test. Re-run complete `research/harness_v46/tests` plus offline SSQ and DLT suite with exact GitHub SHA on both operating systems.
5. Inspect CI job logs for actual counts and all failures; preserve any PowerShell-policy, official-source quorum, native builds, and physical host scheduling blockers.
6. Record exact HEAD, RED/GREEN run IDs, test failures, scope limitations, and pending independent review in stacked Draft PR.
7. Never merge, reissue historical predictions, adopt physics as an evidence-backed lottery predictor, or claim unattended Windows-host P0 from synthetic CI.

Acceptance: independently measured test logs for the exact submitted commit, with any limitations explicit. Even a GREEN result is insufficient for formal engineering/research admission.
