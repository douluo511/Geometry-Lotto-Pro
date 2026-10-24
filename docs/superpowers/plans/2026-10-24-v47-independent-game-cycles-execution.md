# Superpowers execution record: independent SSQ/DLT draw cycles

Master Issue #468; ONLY original stacked PR #467, no new Harness, no main merge.
Author: existing single closed_loop runner; no independent code reviewer connected.

## Prior root cause

Current dual mode `manifest(snapshots)` used BOTH lottery targets to derive
a single RUN_ID; frozen 12-card batch and caller result were tied to both
games. Sat DLT result could not finish score while Sun SSQ was still pending,
and Monday DLT could conflict with the pre-existing SSQ target guard.

## Exact design decision

Keep the legacy dual tables intact and immutable. Extend existing
`closed_loop.advance_game_workspace` and CLI with `--game-snapshot`
and `--game`, using two additive tables `game_runs` and
`game_predictions` in the SAME persisted `ledger.sqlite3`.
Do not count cross-game same calendar day as identical draw identities.
Save exactly six immutable model predictions per (game, numeric issue),
refuse any new freeze on/after that game's declared sales cutoff, replay
old per-game snapshot/model digests, refuse changed retry, score only each
game's independent caller result. Store the local scoreboard in per-game
folders; no official admission, no external TSA, no automatic model upgrade.

Existing Windows Bot `invoke_closed_loop.ps1` accepts opt-in
`ssq_snapshot_bundle` and `dlt_snapshot_bundle`. Its one installed
Task Scheduler job can perform both independent ticks sequentially, logging
each result and continuing the other game when one tick is blocked.
If per-game config not selected, old legacy dual mode remains available.
**This script has not been installed on any owner's persistent host.**

## Falsifiable TDD + verification

1. Synthetic tests first on PR #467, RED commit
   `1ac645542c3ca7eb4112ba44934056f9efff6d4e`, CI
   [#40000685220](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/40000685220):
   7 new tests fail because single-game API and CLI do not exist.
2. GREEN code commit
   `18b74fb574b3739dc06489d8b0abb086f3959524`:
   additional tables and per-game read-only scoring; original 12-card
   and original fixed Random NULL stream stay untouched.
3. Windows initial test failure (#40001017224): new test fixtures held
   SQLite handles open through `with sqlite3.connect`, preventing
   TempDirectory deletion. Test-only fix `42d8a37b7a1b636e54963cb3e6a574c33429e26c`
   explicitly closes all SQLite connections; production lock logic unchanged.
4. Bot invocation test RED `2bb21943dff1582bf8a8853b4331d3db9ed3df13`
   CI [#40001559053](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/40001559053):
   no per-game snapshot flags in Windows script. GREEN
   `0e5734a09257b85cee8b4d23b7de0fa9f978210b`.
5. Final exact HEAD CI Ubuntu and Windows full matrix, plus genuine
   Windows PowerShell subprocess invocation of both independent game
   forecasts, must finish and original logs must be checked before PASS.
6. Preserve original legacy dual freeze and score unchanged. No user data
   or live tickets; no fabricated trust for unverified official sources.

## Outstanding gates

- Windows/Ubuntu ephemeral CI is not an actually deployed durable host,
  supervised boot/power cut, external WORM custody or approved TSA signer.
- No verified G01 120+ dual-source official history, future issue,
  independent cutoff, actual 2026 pre-sale time, afterdraw outcome
  or officially complete prospective D2 cohort.
- Fixed Random NULL, DLT 69/2880 anomaly, preregistration and independent
  multiple-test-adjusted future comparison stay unresolved.
- No independently invocable reviewer: `INDEPENDENT_CODE_REVIEW=NOT_VERIFIED`.

`ENGINEERING_PASS=NOT_YET`; `RESEARCH_VALID=NOT_YET`;
`D2_EDGE_CONFIRMED=NO`; `formal_A=0`; `NO_EDGE`.
