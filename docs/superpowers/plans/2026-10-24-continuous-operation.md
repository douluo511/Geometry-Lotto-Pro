# V4.7 Continuous Operation Implementation Plan

> **For agentic workers:** Use Superpowers test-driven-development and verification-before-completion. Execute the already authorized repair continuously.

**Goal:** Remove dependence on manual chat prompts by enabling recurring continuation and recording real two-game operational attempts in the existing loop.
**Architecture:** Native heartbeat triggers existing closed_loop operational tick. Same immutable ledger and six formal producer identities; no new Harness or inferred targets.
**Tech:** Python3.11 stdlib/sqlite, existing official_intake, current desktop automation tool.
**Spec:** docs/superpowers/specs/2026-10-24-continuous-operation-design.md

## Global constraints
Do not alter core/statistics/model_versions/old frozen data/NULL seed/formal family. No main merge or purchase. No privileged scheduler install or synthetic certification. Source date-only data never become invented exact draw times.

## Review focus
Leaking target/seed normalization; suppressing blocked or crashed attempts; checksum self-rehash claims; one-game failures stopping the other; treating native scheduling/local clock/HTTP200 as formal admission.

### Task1: operational journal and tick
Files: existing research/harness_v46/closed_loop.py; new research/harness_v46/tests/test_operational_tick.py.
Interfaces: operational_tick(workspace, *, snapshot_paths=None, intake_timeout_seconds=45) -> operational receipt; CLI `--operational-tick`, optional `--ssq-snapshot-path`, `--dlt-snapshot-path`, `--intake-timeout-seconds` (only this mode). Existing CLI options remain compatible.
- [ ] Write behavior tests and capture actual missing-feature RED. Notify controller before implementation for remote test-only commit.
- [ ] Add minimal append-only events and existing intake/per-game orchestration. Preserve real failures and previous unfinished attempts.
- [ ] FocusedGREEN and full unittest discovery; save original logs.
- [ ] Independently review new implementation and adversarial probes, repair meaningful findings via RED/GREEN.

### Task2: activate, execute, verify
- [ ] Check existing automations, create/update exactly one30-minute heartbeat attached to current chat, view native ACTIVE config and preserve ID.
- [ ] Save concrete operational settings/guide in outputs/V47_CONTINUOUS_OPERATION.md and persistent workspace location; run a genuine bounded two-game tick, retain source responses/blockers and event receipt.
- [ ] Push only existingPR467 using expected-parent CAS; inspect exact-HEAD Windows/Ubuntu originalCI logs and independent scope.
- [ ] Update soleIssue468 with actual trigger status, operation attempt, code/test evidence and unresolved formal gates. Never substitute another historical rerun for operations.

Ruling: user explicitly requested that this keep running around draws without repeated prompts; native recurring continuation is within scope. No additional clarification/permission is needed for that reversible task. Host filesystem/network or privileged scheduler access still follows actual tool permissions. Overall engineering/forecast edge remains NOT_YET/NO_EDGE until its existing acceptance criteria are met.
