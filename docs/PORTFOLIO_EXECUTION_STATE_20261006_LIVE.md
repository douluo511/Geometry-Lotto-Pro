# Portfolio Live Exact-State Checkpoint — 2026-10-06

This is the latest exact-state checkpoint on control PR #84. Historical checkpoints remain available in Git history and Issue #11.

## Portfolio boundary

- **Active-candidate deterministic migration/export readiness: 17/18 PASS.**
- Reason for the regression from 18/18: Stock PR #268 is a behavior-changing acceptance fix on top of product `c25a5c39...`; Stock export PR #260 remains valid only for the superseded `c25a5c39...` exact state and is stale relative to active candidate `632b59da...`.
- Connected GitHub repository enumeration still exposes only `douluo511/Geometry-Lotto-Pro`.
- Dedicated independent repositories: **0/18 evidenced**.
- Repository Independence: **0/18 PASS**.
- Final Gate: **0/18 PASS**.
- Formal delivery allowed: **0/18**.
- Connected GitHub actions still expose no repository-creation mutation.

## Stock active remediation candidate — PR #268

PR #268: `Stock AI: fail closed on semantically incomplete historical PIT bundles`

- Base: current prior product authority `c25a5c394363058d341b624b18943cd3733eb720`.
- Exact active head: `632b59da262e2f7468bbc4d0fd43d3cf67c0297b`.
- This line closes a verified false-PASS path in Historical ST/PIT evidence evaluation.

Verified defect on the base:
- `evaluate_historical_st_pit()` recomputed real file SHA-256 values but did not semantically verify canonical JSONL / source manifest / per-market evidence bytes against the declared three-market completeness claim.
- The previous positive contract fixture contained only **one SSE canonical row** while the claim declared SSE/SZSE/BSE PASS.
- Therefore real-byte binding alone could accept a semantically incomplete three-market bundle.

Executed repair:
- canonical JSONL must parse completely before PASS;
- malformed rows, invalid dates, invalid market/code mapping, non-boolean state, and duplicate `(date,code)` rows fail closed;
- canonical data must actually contain SSE/SZSE/BSE;
- when expected trade date is supplied, each required market must have canonical state on that date;
- bound source manifest must parse, be `point_in_time_only=true`, and actually list SSE/SZSE/BSE;
- each bound market evidence file must parse and agree with its claim on market, ST identity, suspension state, trading calendar, daily state, window, canonical SHA, source count, point-in-time flag, and zero future-leakage violations;
- new counterexamples deliberately rebind all SHA values after reducing canonical data to SSE-only or source manifest to SSE-only; evaluator must remain WARN;
- inner/outer PACKAGE_MANIFEST SHA bindings were recomputed to the changed product bytes.

Changed product SHA-256:
- `stock_ai/historical_pit.py`: `83acd049569b6b795d694f43a067190bc83e6677b7359ab0cc2d3d299fc74489`
- inner `PACKAGE_MANIFEST.json`: `afc84ee8ccbb840db6295460397c1e7bbe2e4802464bdcfa862c765115abac5b`
- outer distribution manifest after rebinding: `21d7e78dad65ef5f2d6e94db4ab5f90d55127d72f590d830a0a0f07f369adfa3`

Fresh exact-head workflows:
- Source/offline `37419257825` / job `112124705286`: **IN_PROGRESS**.
- Full Business `37419257711` / job `112124704832`: **IN_PROGRESS**.
- Windows Desktop `37419257669` / job `112124705359`: **IN_PROGRESS**.
- No fresh PASS is promoted while they are active.

## Stock Historical ST/PIT data completeness remains separate

PR #268 does **not** invent a historical bundle. Even after evaluator hardening, the actual hash-bound canonical bundle is still absent. Product contract still requires:
- schema `stock-ai-historical-st-pit-v1`;
- claim status/full/daily/PIT/no-future-leakage assertions;
- fresh canonical daily-state bytes;
- source manifest;
- SSE/SZSE/BSE market evidence;
- exact `(date,code)` coverage consumed by backtest at signal date and true next market open.

Issue #252 confirms evaluated row/date PIT gaps must fail closed. Runtime consumption denominator is the frozen research dataset after turnover filtering for signal keys plus post-PIT/Top-N next-market-open execution keys. The broader business meaning of `full_historical_st_pit` still lacks an independently frozen all-market numerical denominator and must not be reduced to the runtime key set by assumption.

## Stock source-data diagnostics

PR #261 current diagnostic head `26f7f8afcfb046100d5fefe2c3c5408e7c7e2543`, run `37417963945` remains **IN_PROGRESS**. Its exact checkout and unchanged-`c25a5c39...` Stock product-byte checks passed before parser execution. It remains source-diagnostic evidence only and does not promote Historical ST/PIT.

The older #261 SUCCESS on synthetic merge commit `87a55479...` remains historical only and is not exact PR-head proof.

## Superseded Stock exact-state evidence

PR #257 `c25a5c394363058d341b624b18943cd3733eb720`:
- source `37371301910` = SUCCESS;
- full business `37371301878` = FAIL on absent historical ST/PIT bundle;
- desktop `37371302045` retry remains IN_PROGRESS at frozen research-corpus qualification;
- these runs are preserved for that exact state but are not inherited by PR #268.

PR #260 export `0cacdb645aaac68ee6820f04b95595bf4073b334` / run `37413482053` = SUCCESS for product `c25a5c39...`; it is now stale relative to PR #268 and therefore current-candidate portfolio export readiness is 17/18.

## RMF

RMF formal completion remains:
- Engineering: **85.7%**
- Business: **75.0%**
- Overall: **75.0%**
- Final: **FAIL**

PR #250 rerun job `112113533557` = SUCCESS with 58/58 comparable dates matched, but historical PIT availability and survivorship selection control remain NOT VERIFIED.

PR #189 supports 5% amount-based capacity diagnostics only; historical bid/ask spread, observed market impact, broker execution slippage, limit-up/down fillability, full cost/slippage calibration and full liquidity-capacity gate remain NOT VERIFIED.

## Strict adjudication

Queued / in-progress = NOT VERIFIED.
Behavior-changing changes invalidate affected downstream evidence.
Real-byte binding without semantic consistency is not sufficient evidence.
Migration/export readiness is not Repository Independence and is not Final Gate.
