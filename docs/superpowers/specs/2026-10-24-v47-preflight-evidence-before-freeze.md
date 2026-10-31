# Issue #468 P0: Per-game evidence preflight before irrevocable SHADOW freeze

**Scope:** Existing PR #467, existing `research.harness_v46.closed_loop.advance_game_workspace` only. Do not alter model formulas, fixed Random NULL seed, historical freezes, global A=0 or main.

## Falsifiable hazard
In the current implementation, `BEGIN IMMEDIATE` inserts six immutable cards and `game_runs` and commits **before** rejecting unknown `outcomes_by_game/<game>/*.json`, unknown `receipts_by_game/<game>/*.json`, or an evidence directory that is a non-directory. A failed tick can therefore still create an irreversible frozen target. This is a local SHADOW state inconsistency, NOT official data authentication.

## Acceptance contract
- If a game's preexisting outcome/receipt directory is unsafe, an unknown issue's JSON is present, or the evidence directory is not a directory, raise the same current GateError **before inserting any new game run or six-card record**.
- Under a new issue, a result file claiming that issue before the first freeze is still unknown and must not be silently adopted.
- Only check the selected game's namespace, so a broken SSQ evidence area cannot suppress a valid DLT SHADOW tick.
- In the transaction re-read the registered issue keys so the preflight corresponds to the protected SQLite writer view. The existing post-commit guards remain as defense against filesystem changes while processing.
- No official status or external RFC3161 trust derived from this test; this does not solve TOCTOU on a hostile filesystem, a privileged DB writer or crash-hardening.

## Proof
Exact HEAD GitHub CI on Ubuntu and Windows; tests first RED, smallest code repair GREEN, complete suite, unchanged old records. No independent reviewer means `NOT_VERIFIED`.
