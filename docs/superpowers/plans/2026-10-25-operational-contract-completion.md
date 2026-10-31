# Complete the original continuous-operation contract

Base exact PR467 HEAD: ce8a17402e59301ef32019ad5220d798b6543e71. Sole control Issue468. Preserve the new source-identity and quarantined-outcome changes, all formal models, NULL seed, statistical family, old ledger events, freezes, and main.

Independent requirement-by-requirement read-only audit found three internal gaps against the existing 2026-10-24 design/plan, despite green CI:

1. GAME_RESULT persists a summary but not the original full game state/intake path/scoring result; FINISHED does not persist the whole returned attempt. Later scoring receipts cannot reconstruct the earlier pending roster if stdout is lost.
2. The promised --ssq-snapshot-path and --dlt-snapshot-path are absent. The operational CLI therefore cannot consume explicit future snapshots even though the API supports them.
3. Precreating the intake parent outside the per-game artifact exception handler stops both games and old-roster scoring when the artifact destination is an ordinary file or unavailable directory, although the ledger and old receipts remain usable.

TDD: add real pending-to-completed durable-event comparison, ordinary-file artifact-destination failure with genuine old-ledger scoring, and real subprocess CLI explicit-future-snapshot/mode-guard tests. Capture actual RED on the exact base; test-only existing-branch publication with expected SHA. Then minimal GREEN: retain full state/result inside existing event payloads without rewriting old formats; expose and gate explicit snapshot paths through existing API; defer artifact directory creation to existing write_bundle catch path. Retain strict symlink guards and fail closed on unusable/corrupt ledgers.

Run focused tests, full regression, exact final SHA Ubuntu/Windows CI, and independent incremental review where available (otherwise NOT_VERIFIED). Run a real no-snapshot source attempt separately; never confuse fixtures with real forecasts. No new Harness/PR, backfilled prediction, automatic source promotion, auto-purchase, main merge, or changed acceptance criteria.
