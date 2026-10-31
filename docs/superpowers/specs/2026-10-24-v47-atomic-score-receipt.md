# PR #467 / Issue #468 — SHADOW score receipt atomic publish specification

**Scope:** existing `research/harness_v46/closed_loop.py::_write_once`.
Do **not** introduce another Harness, extra PR, new model, changed
formal eight slots, altered historical frozen predictions, or changed fixed NULL.

## Observed defect and invariant

The old create-once receipt writer used `path.open("xb")` before data flush.
Injecting `OSError("injected flush failure")` at `os.fsync` caused a final
`receipts/<run_id>.json` path to exist even though the write returned
failure. Such an object is not a committed score and can poison restart,
denominator completeness and evidence custody.

**Invariant:** a receipt with its final `.json` name MUST never be published
before the entire canonical byte payload is written and synchronized; no
existing receipt may be replaced, including with concurrent invocations.
The original frozen SQLite ledger must not be edited by score/retry.

## Design and security boundaries

- Create a uniquely named `*.pending` staging file exclusively in
  the final receipt's existing parent directory.
- Write the complete canonical JSON with a trailing newline, flush and
  `fsync` the staged data file before publication.
- Publish via `os.link(stage, final_path)`, which atomically creates the
  final name *only if absent*. Never use `os.replace` / rename-over-existing.
- A preexisting final receipt is idempotent only if its bytes equal the
  candidate; any discrepancy raises `SCORE_RECEIPT_CONFLICT`.
- Attempt parent-directory `fsync` on POSIX to commit the name; do not
  claim equivalent audited NTFS hardware durability from Windows CI.
- Remove temporary staging on ordinary exception and after success.
  An abrupt power-off may leave `.pending`; it is **not** a scored
  `.json` receipt and must not count toward a cohort.
- Fail closed on unsupported hard links/permissions; no overwrite fallback.

## Adversarial threat boundary

Tests cover injected flush failure, no final-file publication after failed
flush, later retry completion, bytewise conflict, same-path concurrent
writers, and two concurrent entire-loop replays of one frozen run.
An operator with privileged access can still replace the SQLite database
or files; local hard links are NOT external WORM custody or TSA attestation.
Physical Windows power-cut/cold boot, FS volatility, approved service-account
ACLs, official draw authenticity and future hit-rate are NOT verified.

Until separate evidence: ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET;
D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE. Independent reviewer NOT_VERIFIED.
