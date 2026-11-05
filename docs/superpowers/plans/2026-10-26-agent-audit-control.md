# V4.7 bounded multi-agent audit control Implementation Plan
> REQUIRED SUB-SKILL: superpowers:executing-plans.
Goal: run and persist deterministic local audits through the existing V4.7 entrypoint.
Architecture: audit_control.py owns only new tables/evidence, fixed task DAG and pure read-only handlers; closed_loop.main adds mutually exclusive audit request dispatch. Existing Codex actors supply real role provenance; authority is unverified, never grants formal PASS.
Tech: Python3.11 stdlib, existing core/closed_loop/audit_intake_bundle. No new dependency.
Spec: docs/superpowers/specs/2026-10-26-agent-audit-control.md

Constraints: solePR467/Issue468, no extraHarness/newrepo/main merge/purchase/securitypolicychange; old forecasts/NULL/models/family unchanged. Docker/localhost scheduler actual unavailable or unauthorized; do not install or fabricate deployment. Source/runtime pinning and bounded data before audit calls; no arbitrary executable inputs.

Review Focus: forged role != actual independent origin; old-table writes; rehashed wrong identities and changed evidence; replay after uncertain crash; Windows junction/WAL/large-tree reads.

Task1 — append-only task/evidence memory
Create research/harness_v46/audit_control.py and tests/test_audit_control.py.
Interface create_session(workspace,key,actors,source_root); run_session(workspace,session_id,actor); report_session(workspace,session_id); record_review(workspace,session_id,actor,result_digest,note); remember(workspace,session_id,actor,text,evidence_id,status,refutes=None); dispatch(workspace,request,source_root).
- [ ] Add meaningful tests, assert missing feature RED before production.
- [ ] Fixed registry/DAG, source pin, new-only SQLite tables/triggers, canonical per-task chain, once-only start claim, confined create-only evidence and revalidated reports.
- [ ] Execute fixed source/journal/latest-intake/frozen-inventory/container-readiness handlers. No source replays or subprocesses masquerading as isolation. Local byte statuses and actual empty/missing/blocked states.
- [ ] Review is a bound separate-actor claim only; generic memory permits hypothesis/refutation, deterministic handler alone emits VERIFIED_LOCAL.
- [ ] GREEN, including old formal-table byte preservation.

Task2 — original entrypoint and actual Windows evidence
Modify closed_loop.main only; add --audit-request mode exclusive with all other modes. Unknown request schema/keys rejected before new tables/evidence.
- [ ] CLI subprocess tests RED then minimal dispatch GREEN.
- [ ] Full existing suites, exact final source manifest and ledger stable; scoped fresh independent review; fix Important with RED→GREEN.
- [ ] Same existing PR update with expected-parent CAS, exactSHAUbuntu/Windows CI and independent delivered-byte verification.
- [ ] Promote immutable source only after checks; actual Executor runs original audit request against current persistent workspace, records real capability blockers, retains old120events and all frozen rows. Existing heartbeat reads task/fact memory without repeated historical study or duplicate unknown execution. Update soleIssue468 and operation/handoff docs.

Ruling: user supplied the design and explicitly requested deployment/code takeover; no additional choice/approval is inferred for existing authorized read-only software work. Administrator install/task/WSL/reboot remain outside this increment and need original owner authorization. Preserve all evidence instead of deleting the plan workspace.


Final review fix pass: 3P1 findings -> 6 concrete RED assertions among29 tests (realWindowsjunction alreadypasses); shared bounded-reader/check hooks also modify existing audit_intake_bundle.py. Pin actualclosed_loop dependency, all journal selected-column bytes, exactschema+new-onlywriteauthorizer. Additional emptyCLI-mode counterexample RED1 then is-not-None dispatch. Final30focusedGREEN; full559 candidate tests expected,542 files before/after captured. Scoped independence stays unverified for authenticated identity/WORM/officialdata/OSdeployment, never granted PASS.
