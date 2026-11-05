# Independent-game sealing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** Repair the demonstrated V47G freeze-to-seal interface in the existing module without changing old dual runs or granting any formal admission.
**Architecture:** Dispatch the read-only payload reader by exact run identity. For V47G use one validated game_runs row and existing original-version six-card reader; reuse shared request/cryptographic verification.
**Tech Stack:** Existing Python3.11, SQLite, OpenSSL and unittest only.
**Spec:** docs/superpowers/specs/2026-10-26-independent-game-sealing.md

## Global constraints
SoleIssue468/DraftPR467. Base584a/tree9a7068; verified isolatededit work/local_deployment. No changes to current runtime, actual ledger, source bodies, old cards, model parameters, seeds, formal family, main or system task. Never fabricate a dual manifest, official target, trusted root or future sample. formal_A0/NO_EDGE.

## Review focus
- Same run ID duplicated in recreated game schema must block rather than choosing a row.
- Old frozen core source and six models must replay from original trusted artifacts, not today's code.
- A valid unrelated game must not be required or silently sealed.
- Existing dual payload bytes and precise cutoff boundary behavior must remain unchanged.
- Read-only successes and rejection paths must leave DB/card/source bytes unchanged.

### Task1: One bounded payload/request/verify repair
**Files:** modify research/harness_v46/predraw_seal.py; create research/harness_v46/tests/test_independent_game_seal.py. Change other production consumers only if a demonstrated test proves necessary.
**Interfaces:** Existing frozen_seal_payload, prepare_request, verify_response and main; existing closed_loop._read_frozen_game. No new standalone service or Harness.
- [x] Read spec and all current seal/transport tests; record baseline hashes.
- [x] RED: create real synthetic per-game six-card workspace through original freeze API. Assert exact payload identity and strict singleton request/verify/CLI expected success; observe current DUAL_GAME_V47_RUN_ID_REQUIRED failures, not collection errors. Save original test and production hashes/output.
- [x] Add meaningful adversarial cases for the spec's identities/source/card/time/crypto/DB invariants, distinguishing guards already present from newly failing paths.
- [x] Minimal GREEN: exact-prefix branch, typed singleton registration/payload, unchanged dual branch, accurate singleton time label. Reuse old source replay and shared crypto checks, not duplicate predictors or guessed validation.
- [x] Run focused existing dual+new singleton suites. Use real local TEST_ONLY CA/token for crypto coverage where existing tests support it; synthetic mocks alone do not establish true signature verification.
- [x] Save exact new hashes/diff, original RED/GREEN logs and unchanged DB/source proof; independent review before integration.

### Task2: Regression and exact-version evidence
- [x] Run existing complete V4.7 regression and existing SSQ103/DLT14 offline suites once; retain known local PowerShell policy failures separately and any new failure.
- [x] Independent fresh review of exact diff and tests; fix all Critical/Important findings via RED/GREEN.
- [ ] Fresh remoteHEAD check; upload ASCII-safe exact contents and verified Git blobs to same PR branch using lease, no newPR/merge.
- [ ] Exact newHEAD Ubuntu/Windows CI plus original decoded logs; do not reuse584a green for changed code.
- [ ] Do not hotpatch active runtime. Promote only a fully blob-verified new execution snapshot after checks, or leave verified584a active and identify candidate as unpromoted. Preserve actual owner installation receipts and current task configuration; no unauthorized overwrite/upgrade or assumption of automatic execution.
- [ ] Update soleIssue468 evidence with exact scope and remaining G00/G01/trust/host/external-review barriers. Do not report formal prediction advantage or an approved root from engineering tests.

## Observed implementation evidence

Initial1method/two-gameRED failed solely DUAL_GAME_V47_RUN_ID_REQUIRED; byte-identical test then passed real localTEST_ONLYCA request/signature verification. ExpandedRED had4 expectedWAL assertions, followed by pre-open guard. Finalfocused32testsPASS, including singletonCLI, originalsourceupgrade/tamper, olddual and opaque transport. Base584a-generated original dual preimage53899bytes is exactly unchanged under candidate (SHAa360c4a37097567be87119c961c506abf9a86bdd215d234f08e2ca148f8ea3cb), syntheticDBunchanged.

The existing Windows long-path transport test failed during TemporaryDirectory cleanup after the tested operation passed. Correct its cleanup of the entire verified owned first-level subtree; preserve all long-path assertions. Productiontransport and actualsource/model/archive bytes stay unchanged.

Full local502-test regression executed:13failures,1error,1skip; SSQ103/DLT14passed, checkedsourceandactualledgerunchanged. Retain every rawfailure. Tool account is ConstrainedLanguage; PowerShell AST/dot-source/legacy execution-policy tests block, and a dependent test cannot open its absent syntheticledger. The additional unchanged source-launcher fixture initially exceeded Windows temporary path length; same unmodified test passed using its existing SSQ_SOURCE_LAUNCHER_RESULT_FILE option under an approved shorter project evidencepath. No policy bypass, security changes or assertionrelaxation. These results are NOT full localPASS.

Independent scopedcode review:0Critical/0Important. Reportwork/local_deploy_evidence/independent_game_seal/independent_review.json. ExactnewheadCI and anypromotionremainpending; currentverifiedruntime584a is untouched. All evidence here is engineering/synthetic, never formal future samples or source/cutoff/trust admission.
