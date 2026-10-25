# Repair current operational evidence without changing prediction models

Baseline PR467 HEAD: 99c4c93e3d222b9db4de8a85c0b6101b10580da3.
Sole control: Issue468. No new harness, PR, model, NULL seed, statistical family, old prediction, or main merge.

## Evidence and design

The previous local reviewed source and the current remote runner have different SHA256. Current CI passes its own 13 operational tests but does not cover previously found REPLACE and concurrent-roster defects. Independently reproduced current journal accepts replacement with default recursive_triggers OFF, mismatched payload identity and completion without both game results. Scoring reason is absent from the persisted game event.

A genuine native heartbeat at 2026-10-25T02:59:34.025Z ran the exact remote source. One incomplete source extraction failure was preserved before a complete-source retry. The retry retained SSQ worker timeout and DLT date-semantic failures. Both saved intake packages fail the existing byte auditor because the operational writer uses a different envelope and omits admission-guard metadata. Fix the writer to the existing auditor contract; do not weaken the auditor or overwrite failed artifacts.

Use minimal changes in existing closed_loop.py. Preserve both previously written journal formats and their bytes. Keep local checks explicitly distinct from WORM, certified time, official admission and draw coverage. Source collection failures never stop the other game or read-only old-roster scoring.

## Execution and acceptance

1. Add independent behavior counterexamples on the exact baseline; record actual RED before implementation. Publish a test-only commit to existing branch with expected-HEAD check.
2. Reject ordinary REPLACE regardless of connection recursive_triggers setting. Validate event identity and legal start/game/game/finish order while accepting both old payload formats. Never rewrite prior events.
3. Expose concurrently added but unobserved roster identities/counts separately from completed and pending results. Persist scoring failure reason in game events.
4. Assert actual write_bundle -> unchanged audit_bundle integration passes envelope/guard validation under synthetic I/O. This certifies only package consistency, not sources.
5. Minimal GREEN, full regression after final edits, independent adversarial review with exact file hashes. Read original Ubuntu/Windows logs on the final precise commit. CI is synthetic component evidence only.
6. Synchronize only validated operational files into the existing local checkout after saving prior local candidates; retain every real failure and the original SQLite ledger. Update operation guide and Issue468 with exact evidence and remaining official/host gates.

No future target is inferred from weekday, history successor, advisory endpoint, date-only result, or wall-clock schedule. No retrospective snapshot/forecast backfill. Formal future numerator and denominator remain NOT_VERIFIED; formal_A=0 and NO_EDGE.
