# Human Nature Pro — Frozen Master System Architecture & Final Acceptance Standard

Status: FROZEN / NON-DOWNGRADABLE
Scope: Human Nature Pro only
Supersedes: Engineering Gates v1.0 where this document is stricter
Rule: Human Nature Pro must remain a completely independent project with its own repository, code, data, configuration, models, content, updater, Windows build, exact EXE, same-hash evidence, final gate, and final artifact.

## 1. Master architecture

Product / Governance
Requirements · Business Purpose · 5 Why · Risk Boundary
        ↓
Domain
Entities · Rules · State · Use Cases · Constraints
        ↓
Information / Data Source
Authoritative Sources · Local Knowledge · User Data · Case Library
        ↓
NetClient
Timeout · Retry · Backoff · Schema · Hash · Multi-source · Failover · Fail-Closed
        ↓
Storage
Raw · Canonical · Cache · DB · Snapshot · Version · Migration · Backup · Recovery
        ↓
Engine
Rule Engine · Models · Reasoning · Scoring · Analysis
        ↓
Validation
Baseline · Positive Validation · Counterexample · Reversal · Ablation · Stability
        ↓
Evidence
Source · Hash · Lineage · Decision · Log · Replay
        ↓
Application / Service
Use-case Orchestration · State Machine · Error Propagation · Audit
        ↓
UI
Analyze Current Situation · One-click Update · One-click Repair · Advanced Analysis
        ↓
Acceptance / Release
Self-Test → Contract Test → Integration Test → Fault Injection → Real Network
→ Business Validation → Counterexample → Reversal Validation
→ Windows Build → Exact EXE → GUI Physical Click → Same Hash → Final Gate

## 2. Fixed layers

1. Product
2. Governance
3. Domain
4. Source
5. NetClient
6. Storage
7. Engine
8. Validation
9. Evidence
10. Service
11. UI
12. Release

No skipping layers. No business/network logic directly in UI.

## 3. Mandatory pre-code work

Recover original requirements
→ business purpose
→ 5 Why
→ risk boundary
→ success criteria
→ failure criteria
→ Domain Model
→ data requirements
→ feature inventory
→ function inventory
→ interface contracts
→ acceptance criteria

## 4. Standard project layout

project/
├─ app/
│  ├─ domain/{entities,value_objects,rules,policies,exceptions}/
│  ├─ sources/{official,secondary,local,adapters}/
│  ├─ net/{client.py,retry.py,validation.py,failover.py}
│  ├─ storage/{repositories,database,cache,migrations,recovery}/
│  ├─ engine/{rules,models,scoring,reasoning,ensemble}/
│  ├─ validation/{baseline,ablation,counterexample,reversal,stability}/
│  ├─ evidence/{lineage,audit,replay,reports}/
│  ├─ services/{main_service.py,update_service.py,repair_service.py,analysis_service.py}
│  └─ ui/{main_window,dialogs,views,presenters}/
├─ content/{knowledge,rules,models,cases,counterexamples,sources}/
├─ tests/{unit,contract,integration,fault_injection,network,gui,acceptance}/
├─ updater/
├─ build/
├─ release/
├─ manifests/
├─ evidence/
└─ docs/

## 5. UI contract

Analyze Current Situation | One-click Update
One-click Repair          | Advanced Analysis

Complex functions stay inside Advanced Analysis/settings.

## 6. NetClient hard standard

Request
→ DNS / Connect Timeout
→ Read Timeout
→ HTTP Status Validation
→ Content-Type Validation
→ Schema Validation
→ Semantic Validation
→ Payload Hash
→ Source Timestamp
→ Canonicalization
→ Evidence

Failure path:
Primary FAIL → bounded retry → exponential backoff + jitter → secondary source → cross-check → HARD FAIL

Network failure must never be disguised as cache success.

## 7. Storage data chain

RAW → VALIDATED → CANONICAL → FEATURE / KNOWLEDGE → RESULT → EVIDENCE

Every relevant record must retain:
source, retrieved_at, source_timestamp, raw_hash, canonical_hash, schema_version,
parser_version, engine_version, config_hash, result_hash.

## 8. Engine rule

Candidate Pool → Rule Engine → Statistical/ML Models → Reasoning Engine
→ Validation → Qualified Models Only → Champion/Ensemble → Production

More models does not mean a stronger system. Only validated information may enter production.

## 9. Evidence is first-class

Every important result must support:
Input, Source, Raw Hash, Canonical Hash, Rule/Model Version, Parameters,
Intermediate Result, Final Result, Confidence/Limitation, Counter Evidence, Replay ID.

The system must be able to answer:
Why this result? What evidence supports it? What opposes it?
Does it change if a key model/source/window/seed/rule is removed or altered?

## 10. 5 Why + reversal

Anomaly → Why1 → Why2 → Why3 → Why4 → Why5/Root Cause
→ Reverse Test → Counterfactual → Modification Candidate → Full Revalidation

Reversal checks include key-data removal, key-model removal, time-window change,
source change, seed change, counterexample injection, and rule-parameter change.

## 11. Test chain

Static / Compile
→ Unit
→ Contract
→ Integration
→ Fault Injection
→ Real Network
→ Business Validation
→ Counterexample
→ Reversal Validation
→ Windows Build
→ Exact EXE
→ GUI Physical Click
→ Same Hash
→ Final Gate

Source-code PASS never implies final-EXE PASS.

## 12. Fault injection minimum

Offline, timeout, DNS error, 403, 404, 429, 500/502/503, wrong content type,
schema drift, HTML structure drift, empty data, corrupt data, hash mismatch,
multi-source conflict, corrupt cache, corrupt DB, permission denied, disk full,
update failure, interrupted upgrade, corrupt config, corrupt model file.

No failure condition may be incorrectly reported as PASS.

## 13. Independent Updater

Main app → version check → independent Updater → download
→ hash/signature/manifest validation → close main app → backup
→ replace → launch new version → self-test
PASS: keep new version
FAIL: automatic rollback

The running EXE may not overwrite itself.

## 14. Final release evidence

release/
├─ Product.exe
├─ manifest.json
├─ acceptance.json
├─ build_info.json
├─ evidence.json
├─ sha256.txt
└─ release_report.json

acceptance.json minimum:
engineering_gate, business_gate, network_gate, fault_gate, windows_runtime_gate,
exact_exe_gate, gui_gate, same_hash_gate, final_gate.

All must be explicit PASS to mark FINAL.

## 15. Dual-completion reporting

Every progress report must show:
Engineering completion: X%
Business-content completion: Y%
Overall completion: min(X%, Y%)
Final Gate: PASS / FAIL

Engineering includes architecture, network, storage, engine, evidence, service, UI,
tests, fault injection, Windows build, exact EXE, GUI, same hash, final gate.

Business content includes knowledge scope, sources, data volume, rule system,
models/reasoning, case library, counterexamples, functional depth, output quality,
and practical value.

## 16. Final-complete definition

Engineering = 100%
AND Business Content = 100%
AND Final Gate = PASS

PENDING, WARNING, UNAVAILABLE, SKIPPED, UNKNOWN, NOT_EVALUATED are never PASS.

## 17. Material-change invalidation

Any material change to behavior code, business rules, model, data chain, network logic,
parser, storage structure, core configuration, production parameters, or UI-Service binding
invalidates all prior final acceptance.

Must rerun:
Build → Tests → Real Network → Windows EXE → Exact EXE → GUI Physical Click
→ Same Hash → Final Gate

No mixing old PASS evidence with a new version.

## 18. Independent-system principle

Human Nature Pro must independently own:
Domain, Source, Content, Engine, Validation, Evidence, Tests, Updater,
Windows Build, Exact EXE, Same Hash, Final Gate.

One system = one independent project = one independent EXE
= one independent evidence chain = one independent Final Gate.

## 19. Frozen execution line

Recover original requirements
→ business purpose
→ 5 Why
→ risk boundary
→ Domain
→ sources/data
→ NetClient
→ Storage
→ Engine
→ Evidence
→ Service
→ UI
→ content/models/rules/cases
→ Self-Test
→ Contract Test
→ Integration Test
→ Fault Injection
→ Real Network
→ Business Validation
→ Counterexample
→ Reversal Validation
→ Windows Build
→ Exact EXE
→ GUI Physical Click
→ Same Hash
→ Final Gate
→ unique final artifact

FINAL is forbidden until Engineering = 100%, Business Content = 100%, and Final Gate = PASS.

## Current compliance disposition

Human Nature Pro v0.1.0 is PROTOTYPE ONLY and is not FINAL.

Current hard blocker introduced by this frozen standard:
Human Nature Pro is presently located inside the Geometry-Lotto-Pro repository/branch.
That violates the independent-repository rule. Therefore current Final Gate = FAIL until
the project is migrated to its own repository and revalidated end-to-end there.

The previous prototype acceptance evidence may be retained as historical evidence only.
It cannot be reused to satisfy a later independent-project Final Gate after migration or material code changes.
