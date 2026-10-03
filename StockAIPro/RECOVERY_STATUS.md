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


## 2026-10-03 strict re-execution evidence

The exact saved `Stock_AI_Pro_DELIVERABLE_FINAL.zip` bytes were recovered again from the user's persistent file library and materialized for direct inspection.

- exact ZIP SHA-256 re-computed: `fedbc5378ed5916e487b9cdc70051d5d00f790e4689ba8ff96dc8f2396ac7e10` — matches the frozen recovered identity;
- archive contains 187 entries, including active 4.3.0 source, rollback 4.2.0 source, Updater runtime, security/rollback tests, manifests and Windows acceptance entrypoints;
- Python compile of the extracted source: PASS;
- root component gates re-executed: distribution layout PASS, data separation PASS, updater transaction/security/rollback PASS, launcher UI-failure rollback PASS, schema rollback compatibility PASS, install fail-fast PASS, deterministic build PASS, distribution manifest bidirectional check PASS;
- active 4.3 component gates re-executed: app contract, audit/5 Why/reversal, backtest, config migration, cost/valuation/decision, entrypoint self-heal, freshness fail-closed, model modes, three-model ensemble, network config, active manifest, prediction hash chain, provider normalization, R&D champion/challenger, self-test, storage, universe parser and healthcheck all PASS;
- `integration_pipeline_test.py` isolated rerun: PASS in 5.98s;
- bundled aggregate `run_full_check.py --offline`: NOT VERIFIED as an aggregate because two attempts reached `integration_pipeline_test.py` and hit the runner's finite child timeout before returning an aggregate verdict. This must not be promoted to full-suite PASS merely from the isolated component PASS.

### Current exact-source import boundary

Fresh Library recovery identity for the exact archive:

- Library file id: `file_00000000127c81f5bea0d5483c4b4eac`;
- Library version id: `6`;
- materialized byte size: `225815`;
- recomputed SHA-256: `fedbc5378ed5916e487b9cdc70051d5d00f790e4689ba8ff96dc8f2396ac7e10`;
- archive safety/shape check: 187 entries under `Stock_AI_Pro/`, no absolute/traversal/symlink entries; 186 UTF-8 text files plus one 645-byte binary ZIP fixture.

The current GitHub connector can create UTF-8/base64 blobs and trees, but it has no direct byte-stream bridge from the materialized Library/container file into a Git blob. Therefore the exact archive is **recovered and reverified locally, but not yet imported into this branch**. A documentation record or reconstructed substitute must not be counted as exact-source import PASS. The unblock condition is a reliable binary upload/byte bridge (or an independent repository environment where the exact archive bytes can be checked out/imported and rehashed before migration).

This recovery removes the stale statement that the exact delivery archive is unavailable. It does **not** satisfy the current product gates: exact source is not yet migrated into the current architecture/repository, the product is still ZIP/BAT/Streamlit rather than the frozen Windows desktop Exact EXE delivery, current Real Network is not verified, independent Updater release transaction is not verified, Windows Native Build/GUI Physical Click/Same Hash are not verified, repository independence remains FAIL, and Final Gate remains FAIL.
