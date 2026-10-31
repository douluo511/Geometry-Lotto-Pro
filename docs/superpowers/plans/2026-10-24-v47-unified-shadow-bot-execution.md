# Superpowers execution plan — unify existing V4.7, don't create a new Harness

Parent: #467 on #466. Master /goal: Issue #468.

## A. Source and process identity
- [x] Read current #467, #466 and separate #462/#455–#459 source and tests.
- [x] Keep main, formal V4.5 slots, old frozen evidence, Random NULL fixed.
- [x] Carry #462 deterministic challenger/test/document intact on #467 only.
- [x] Verify bottom-level duplicate numeric D2 issue aliases are rejected in the original #467 lineage.

## B. Single entrypoint and safety
- [x] Reuse `closed_loop.advance_workspace` as the one Python research entrypoint.
- [x] Add fail-closed external JSON parsing and path-component checks.
- [x] Add optional isolated `research_diagnostic` as retrospective only, no seventh model and no model promotion.
- [x] Add opt-in Windows 30min+boot scheduler that invokes the same Python path. Do not call GitHub CI deployment.
- [ ] Verify no concurrent process can preempt/rewrite an incomplete receipt and that Windows dry-run produces only a preview; independent review required.

## C. Actual RED→GREEN and CI evidence
- [x] Previous PR467 issue identity RED→GREEN + exact-head dualOS SUCCESS, links in PR467.
- [x] New adversarial CLI duplicate/nonfinite tests committed first (RED commit `d1d7a4a26ce8212b01d39fe9931af110775b2782`, CI `39993861529` FAILURE). GREEN candidate `d84b57811c9fdfe6f5ab217967de9594154161b7`, CI `39993989095` SUCCESS.
- [x] Challenger integration test committed before Python integration (RED commit `bc43869a0c77e242b3e00bd4e1b9a18ba7465470`, CI `39994168189` FAILURE); code `7e1c1de3fe3c97ff7948ed74d94a77b21c624716`.
- [x] Scheduler script-presence/installer-dry-run safety tests committed first (RED commit `1dc0bae0b1a6863782d5fd90c1ec954ad7585134`); scripts subsequently created.
- [ ] Latest exact-HEAD Windows and Ubuntu CI, independent whole-branch review, actual raw run logs, exact checkout SHA and successful syntax/positive and negative subcases. Do not mark complete before verified.

## D. Source and science blockers (NOT done)
- [ ] Reconcile #464 correct DLT draw date semantics with #465/#467 observation input without mutating old evidence.
- [ ] Resolve authoritative independent history/cutoff/current future issue and source disagreements, preserve HTTP status/bodies.
- [ ] Approved external RFC3161 time bound incl. accuracy and exact predicted-seal receipt before sales cutoff.
- [ ] Truly authenticated postdraw outcomes; no local mock result as official.
- [ ] Durable host install/physical reboot/recovery/power-loss simulation/lockstep multiple ticks evidence.
- [ ] DLT 69/2880 anomaly independent same-seed root-cause and true preregistered trial.
- [ ] Report genuine matched-model-vs-NULL future D2 hit counts by issue, family-corrected inference and independent confirmation.

## Overall verdict
ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; A=0; NO_EDGE. Never count this synthetic CI as true increased hit probability.
