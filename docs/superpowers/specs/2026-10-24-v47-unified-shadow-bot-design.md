# Superpowers specification — V4.7 unified SHADOW Bot and challenger (Issue #468)

## User outcome, not a reporting project

Reuse the only existing `research/harness_v46` lineage so the user can repeatedly execute a two-lottery forecast-before-draw, immutable freeze, later read-only score, complete cohort D2/NULL analysis, and strictly separate experimental algorithm research. The expected outcome is an executable flow, not a fourth Harness or another plan. **This scoped PR cannot certify actual forward lottery advantage without authenticated public data, independent pre-sale witnesses and future observations.**

## Integration map and trust boundary

- Existing #466: exact frozen twelve cards; post-draw hash-bound original outcome; all local ledger runs are covered by study; same-draw paired NULL.
- Existing #467: single reentrant CLI and low-level D2 issue-alias guards.
- Earlier sibling #462: fixed `RECENCY_PAIR_H45_120_V1` 120-history/45-half-life walk-forward algorithm, *research only*; imported unmodified and never promoted to any six-arm frozen prediction set or original formal eight slots.
- Earlier sibling #455–#459: separate Bot tick and scheduler work inspired this isolated opt-in scheduler and strict JSON/path checks. No silent cherry-pick of a conflicting whole `prospective_cycle.py`.
- Official data G01, cryptographic TSA, scheduler installation, real-host cold boot/recovery, prospective model efficacy and DLT 69/2880 anomaly are **not** solved or auto-certified by these additions.

## Executable operation

One Python interface: `python -m research.harness_v46.closed_loop --workspace PATH [--snapshot-bundle SNAP] [--research-history-bundle HISTORY]`.

- With dual-game snapshots strictly before locked cutoff, call only the registered existing six forecast arms plus the fixed NULL, commit the dual-game ledger and return `WAITING_FOR_OUTCOME`.
- After original outcome appears under `outcomes/<run_id>.json`, validate full target/time/result, score read-only and persist nonoverwriting score receipt. If any registered run remains pending, do not return complete cohort statistics.
- Optional historical bundle invokes fixed PR462 walk-forward and returns `research_diagnostic` with `RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE`. Never add it to the six-model study family; it must never call forecast to change frozen original D2s, seeds or predictions. A retrospective high D2 hit count cannot become edge proof.
- Parse external JSON with duplicate-name guard on every object, no NaN/Infinity or overflowing float, size ≤32 million bytes, ancestor-symlink and parent traversal detection. Conflict/mismatch fails closed.
- Opt-in `windows_closed_loop_tasks.ps1 -ConfigFile ... [-Install]` allows a persistent Windows operator to preview or explicitly install an isolated 30-minute + startup task. `invoke_closed_loop.ps1` runs the single Python entrypoint and appends local log and real exit code. CI never installs this task, and GitHub hosted runners have ephemeral storage; no trusted archive or independent clock claims.

## Falsification and negative controls

- RED: low-level `29999` and `029999` double count + non-ASCII numeric; GREEN fail closed.
- RED: missing unified runner then GREEN full API/subprocess freeze/postdraw/retry.
- RED: nested duplicate/NaN JSON must block before freezing/receipt, GREEN on actual code.
- RED: historical challenger integration absent then GREEN, preserving original six arms, formal_A=0, NO_EDGE.
- RED: Windows Bot scripts absent then GREEN static/offline PowerShell syntax, no installer invocation.
- Existing DLT 69/2880 anomaly must remain unresolved, never discard a negative-control counterexample.

## Superpowers discipline

Before declaring component success, verify RED jobs failed for the intended assertion, compare exact fix source, test post-fix on exact-HEAD Windows and Ubuntu including raw logs, preserve source SHA and immutable evidence. Require an **independent reviewer** distinct from implementer for research admission; GitHub CI checks are not an independent review actor, so mark `INDEPENDENT_CODE_REVIEW=NOT_VERIFIED` until actually assigned and performed. Neither this spec nor Issue #468 runs an autonomous coding agent by itself.

No main write, release, old-forecast replacement, purchase, invented official outcomes or model edge claim.
