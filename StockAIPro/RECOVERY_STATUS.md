# Stock AI Pro Recovery Status — 2026-09-30

**STAGING / NOT FINAL / NO INHERITED PASS**

This branch records the exact recovered Stock AI Pro lineage before any modernization.
It must not be described as Portfolio FINAL until the complete current Master System Architecture
and Windows hard-gate chain passes from an independent Stock AI Pro repository.

## Recovered package identities

| Package | SHA-256 | Observed identity |
|---|---|---|
| `Stock_AI_Pro_COMPLETE_v3.1.0.zip` | `481bc2ee5f2996d1e549709695f3ff9014d57b0a30e2cc4f55f98509e894250a` | source package, version `3.1.0-complete-selfserve` |
| `Stock_AI_Pro_DELIVERABLE_FINAL.zip` | `fedbc5378ed5916e487b9cdc70051d5d00f790e4689ba8ff96dc8f2396ac7e10` | multi-version delivery package, active `4.3.0`, rollback `4.2.0` |
| `Stock_AI_Pro_Production_Ready.zip` | `1b46783445b91d30642751a2a51691466c5aec10cc37c5982e97a6b998b0c659` | older 1.0.1 candidate containing DEMO fallback |

## Strongest recovered baseline

`Stock_AI_Pro_DELIVERABLE_FINAL.zip` contains:

- active source version `4.3.0-deliverable`;
- rollback source version `4.2.0`;
- source trees under `stock_ai/`;
- model/backtest/audit/R&D/valuation/cost/storage code;
- deterministic package manifests with per-file SHA-256;
- updater runtime 1.2;
- updater security and rollback tests;
- launcher rollback tests;
- distribution and version manifests;
- Windows first-run acceptance entrypoint.

Its recorded 4.3 build audit says source engineering acceptance and offline healthcheck passed,
with Ridge + HistGradientBoosting + ExtraTrees and production/backtest parity.

## Evidence boundary retained

The recovered acceptance report explicitly says the build environment did **not** execute:

- Windows BAT / PowerShell / Task Scheduler;
- fresh Windows online dependency installation;
- live AkShare prediction on the target machine.

Therefore these items are not inherited as PASS.

## Rejected / non-production baseline

`Stock_AI_Pro_Production_Ready.zip` must not be used as the production baseline.
Its README and source include `core/demo.py` and `DEMO_FALLBACK`; its acceptance report also leaves
external market network and release-server configuration pending.

## Current frozen hard gaps

The recovered 4.3 lineage predates the current portfolio architecture and therefore still needs:

1. independent repository creation and migration;
2. exact-source import with package-hash provenance;
3. Product / Governance / Domain / Source / **NetClient** / Storage / Engine / Validation / Evidence / Service / UI / Release layering;
4. one audited NetClient for every production network call with timeout, finite retry, exponential backoff+jitter, source identity, raw response evidence, schema/semantic/freshness validation and fail-closed semantics;
5. current live A-share data validation, cross-source checks, market calendar and corporate-action/PIT controls;
6. leakage-safe OOS / walk-forward / bootstrap / ablation / stability / multiple-seed/window / reality-check and multiple-testing evidence;
7. cost, slippage, liquidity and valuation validation in the exact production scoring/backtest chain;
8. one-click independent Updater with real HTTPS release transaction and rollback;
9. native Windows build;
10. Exact EXE acceptance;
11. physical GUI click acceptance;
12. exact-EXE real network;
13. Same Hash after the accepted GUI/network run;
14. evidence-derived Final Gate with `hard_fail_count=0`.

Any PENDING / WARNING / SKIPPED / UNKNOWN / UNAVAILABLE / FAIL remains non-PASS.

## Current verdict

- Exact source lineage recovery: **PASS (package identity established)**
- Production architecture migration: **INCOMPLETE**
- Windows current-version acceptance: **NOT PASS**
- Real network current-version acceptance: **NOT PASS**
- Repository independence: **FAIL / target repo not yet established**
- Final Gate: **FAIL**
