# HIGH-STANDARD / FAIL-CLOSED / NON-DEGRADATION POLICY

Status: FROZEN

Authority: User-defined highest project constraint. It remains binding until the user explicitly changes it.

## Non-negotiable rules

- Do not lower standards because of time, environment, unavailable tools, network failure, missing data, complexity, workload, partial usability, a runnable UI, generated EXE/ZIP, a `Final` filename, or one passing run.
- Only an explicit `PASS` supported by current-version evidence is a pass.
- Unknown, untested, unavailable, incomplete, warning, skipped, pending, blocked, cached, simulated, stale, historical, or assumed success is not a pass.
- All critical paths are fail-closed. Missing evidence blocks the Final Gate.
- A code, configuration, model, data-processing, network, UI, packaging, or dependency change invalidates prior final acceptance and requires the complete downstream acceptance chain to be rerun.
- No placeholder, empty button, disconnected entry point, TODO, mock, demo data, default value, swallowed exception, or false-success UI state may be treated as production functionality.
- **No-shell hard gate:** Every in-scope button, module, model, updater, network function, and analysis entry point must have a real implementation, a reachable production call path, authentic inputs/data, passing real tests, and reviewable Evidence bound to the current candidate. Any missing element is non-PASS and blocks the unique final artifact. Mock, TODO, placeholder pages, demo data, fake interfaces, and an EXE that merely opens cannot satisfy this gate.
- After any substantive code, configuration, model, data-processing, network, UI, packaging, or dependency change, prior final acceptance is invalid. Rerun **Real Network -> Windows Build -> Exact EXE -> Physical GUI Click -> Same Hash -> Final Gate** on the new candidate. The physical GUI stage must also prove that network-facing entry points in the Exact EXE perform real calls and record their response Evidence; a source-only network test is insufficient.

## Mandatory engineering sequence

Original requirement recovery
-> Business purpose
-> 5 Why
-> Risk boundary
-> Success and failure criteria
-> Domain Model
-> Architecture
-> Feature inventory
-> Function inventory
-> Interface contracts
-> Data sources
-> NetClient
-> Storage
-> Engine
-> Validation
-> Evidence
-> Service
-> UI
-> Self-Test
-> Unit Test
-> Contract Test
-> Integration Test
-> Fault Injection
-> Real Network
-> Business Validation
-> Counterexample Validation
-> Reversal Validation
-> Windows Build
-> Exact EXE
-> Physical GUI Click
-> Same Hash
-> Final Gate
-> One unique final artifact

No stage may be skipped without recording an explicit non-PASS state and blocking downstream acceptance.

## Network hard requirements

- Separate connection and read timeouts.
- Finite retry budget.
- Exponential backoff with jitter.
- Explicit 429 and 5xx handling.
- Schema, content, freshness, semantic, and source validation.
- Source provenance and raw response preservation.
- Trusted fallback source and source-conflict detection.
- Any failure must propagate through the call chain into Evidence and must never display success.

## Data lineage

`RAW -> VALIDATED -> CANONICAL -> FEATURE / KNOWLEDGE -> RESULT -> EVIDENCE`

Every production result must trace source, retrieval time, raw content, cleaning, transformations, algorithm input, algorithm output, version, and final status.

## Model and algorithm qualification

Candidate Pool
-> Independent Validation
-> Baseline Comparison
-> OOS / Walk-forward
-> Bootstrap
-> Ablation
-> Stability Test
-> Multiple Seeds / Windows
-> Counterexample Test
-> Reality Check
-> Multiple-testing Correction
-> Qualified Models Only
-> Champion / Ensemble
-> Production

Models without stable incremental value must be rejected or downgraded. Evaluation standards may not be changed to preserve a preferred model.

## Evidence requirements

Every critical PASS must include:

- timestamp;
- inputs and outputs;
- status and failure details;
- logs;
- version and hash;
- test conditions and environment;
- reproducible artifacts.

No evidence means no completion.

## Root-cause and reversal workflow

Symptom
-> Root cause
-> 5 Why
-> Systemic-scope check
-> Fix
-> Counterexample validation
-> Reversal validation
-> Regression tests
-> Full acceptance rerun

Reversal validation must ask what evidence would exist if the conclusion were wrong, whether reversing the key condition preserves the result, and whether chance, leakage, overfitting, or bad data can explain the outcome.

## Dual completion reporting

- Engineering completion covers the complete engineering and acceptance chain.
- Business-content completion covers knowledge scope, sources, data volume, rules, model/reasoning depth, cases, feature depth, output quality, counterexamples, and real user value.
- Overall completion equals the lower limiting completion; engineering completion cannot substitute for business completion.
- Percentages require an independently frozen, approved denominator and current evidence. If either is missing, report unverified (machine value `null`), not an estimate and not a fabricated zero.
- Structural schema validation, static symbol/string checks, and evidence-file integrity checks are narrowly scoped checks, never proof of full business completion, real execution, or release authorization.

## Operational application

- Keep the frozen requirement/entry inventory separate from the report being evaluated. A report must not remove its own failing entries or alter its own denominator.
- Resolve evidence references, independently hash the actual files, bind accepted evidence to the current candidate, check validity times, and calculate scores from criteria rather than counting tests.
- A controlled fault test may PASS when the expected failure is detected and propagated. Its failed request remains FAIL; synthetic test inputs cannot count as production input or Real Network evidence.
- Keep repository-topology and updater-process constraints separate from functional proof. Preserve existing blocking controls while recording the authority of any additional requirement; do not silently waive or invent user approval.
- Development changes and read-only hourly supervision are separate modes. An observation does not itself implement a fix, and a successful narrow test does not complete the project.

## Required status report

Every stage report must state:

- Engineering completion: X%
- Business-content completion: X%
- Overall completion: X%
- Completed
- Verified PASS
- Incomplete
- BLOCKED
- FAIL
- Largest current risk
- Next step
- Final Gate: PASS / FAIL / BLOCKED
- Unique final artifact: YES / NO

## Final-release hard gate

A project may be called final or complete only when all requirements, the No-shell hard gate for every in-scope entry point, real functions, contracts, data and exception chains, fault injection, real network, business validation, counterexample/reversal validation, native Windows build, Exact EXE, physical GUI clicks, all core entry points, Same Hash, Evidence, Final Gate, 100% engineering completion, 100% business-content completion, and single-version/single-artifact requirements are explicit PASS.

If any item is missing, the project is not Final and is not complete.

## Priority order

Truthfulness > Correctness > Safety > Verifiability > Reproducibility > Completeness > Stability > Maintainability > Performance > Development speed > Presentation.

## Core execution command

No degradation. No false PASS. No skipped steps. No empty shell. No simulation presented as reality. Code existence is not functional proof. EXE generation is not EXE acceptance. A single success is not stable validation. Engineering completion is not business completion. Every conclusion requires evidence. Every final version must pass the Final Gate. The target is a real, complete, verifiable, reproducible, auditable, and durable system.
