# Research-only implementation plan / execution receipt (2026-11-11)

1. Read repository safeguards (README, Issue #468, original SSQ engine). Add an isolated sidecar, never a fourth harness.
2. Assemble SSQ 100 and DLT 90 contiguous issues from published pages. Validate number domain/continuity and retain fixture hashes.
3. Test-first local RED: an initial legal-mapping test incorrectly expected (1,2,3,34,35), while the documented increment-and-wrap normalization yields (1,2,3,4,35); corrected the test expectation. This RED was test-spec correction, NOT proof of a program bug.
4. Implement finite-field Newton interpolants, 10 predefined formula variants per game, strict 60/30 temporal split, separately seeded research NULL, fail-closed validator, JSON report.
5. Local reproduction from repo root:
   - PYTHONPATH=. pytest -q tests/test_inverse_probe.py
   - PYTHONPATH=. python -m research.inverse_formula.probe
6. Open draft research-only PR, do not merge. Require independent review, official source quorum, preregistered future evaluation and hosted CI before any promotion.

## Actual locally executed results
- Five focused tests passed (local Python); hosted CI not established by this claim.
- SSQ: 60/60 exact in sample for all ten variants, 0/30 exact in subsequent 2026100..2026129 issues.
- DLT: 60/60 exact in sample for all ten variants, 0/30 exact in subsequent 26099..26128 issues.
- D2 hits and research NULL are emitted by script; no superiority claim or outcome-driven selection.
- An interpolating formula based on all known history can emit a next-issue candidate, but it has NOT demonstrated useful future prediction.
