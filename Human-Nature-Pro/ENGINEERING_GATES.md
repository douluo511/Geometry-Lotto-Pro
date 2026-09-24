# Human Nature Pro — Engineering Gates v1.0

This document is the only accepted delivery path for Human Nature Pro.

## Hard rule

A release is FINAL only when every gate below is explicitly PASS against the exact artifact being delivered.
FAIL, WARNING, PENDING, SKIPPED, UNKNOWN, UNAVAILABLE, or NOT_RUN at any gate means the final release gate is FAIL.

## 24-gate chain

1. Requirements / Purpose Modeling
2. 5 Why Root-Cause Analysis
3. Risk Boundary
4. Domain Model
5. Architecture Diagram
6. Function Inventory
7. Interface Contracts
8. Data Sources
9. NetClient
10. Storage
11. Engine
12. Evidence
13. Service
14. UI
15. Self-Test
16. Contract Test
17. Fault Injection
18. Real Network
19. Windows Build
20. Exact EXE
21. GUI Smoke
22. Same Hash
23. Final Gate
24. Unique Final Artifact

## Gate contracts

### G01 Requirements / Purpose Modeling
PASS requires a frozen problem statement, target users, supported scenarios, non-goals, measurable outputs, update behavior, and acceptance criteria.

### G02 5 Why
PASS requires root-cause analysis for the core user need and for failure modes such as false psychological certainty, stale knowledge, broken update, and UI-success/backend-failure divergence.

### G03 Risk Boundary
PASS requires explicit boundaries against deception, coercion, exploiting vulnerabilities, unsupported mind-reading claims, and hidden certainty inflation. Outputs must distinguish observation, inference, hypothesis, evidence, uncertainty, and advice.

### G04 Domain Model
PASS requires typed domain objects for Case, Goal, Observation, EvidenceItem, HumanState, Hypothesis, Strategy, Risk, AnalysisResult, UpdateResult, RepairResult, and AuditRecord.

### G05 Architecture Diagram
PASS requires the frozen dependency direction:
UI -> Application Service -> Domain/Engine -> Evidence/Storage/NetClient.
UI must not contain domain reasoning or network implementation.

### G06 Function Inventory
PASS requires a complete callable inventory with ownership, input/output types, errors, side effects, and tests.

### G07 Interface Contracts
PASS requires stable contracts for analyze, update_all, repair, advanced_analysis, self_test, health, and export/audit operations.

### G08 Data Sources
PASS requires an allowlisted source registry with source ID, purpose, URL, authority class, parser/schema, freshness rules, and provenance requirements.

### G09 NetClient
PASS requires connect/read timeout, idempotent-only bounded retry, exponential backoff with jitter, 429/5xx handling, content-type checks, size limits, schema/hash validation, provenance logging, and no cache-as-network-success masquerading.

### G10 Storage
PASS requires atomic writes, backup/rollback, schema versioning, corruption detection, migration strategy, and separation of bundled seed from mutable user data.

### G11 Engine
PASS requires deterministic analysis from explicit inputs, competing hypotheses, evidence-for/evidence-against, uncertainty, information-gain suggestions, strategy candidates, 5 Why, and reverse validation.

### G12 Evidence
PASS requires evidence lineage, source/time/hash, confidence semantics, contradiction handling, and a prohibition on converting weak signals into facts.

### G13 Service
PASS requires one service-layer entrypoint per UI action. Service owns orchestration; UI owns presentation only.

### G14 UI
PASS requires four top-level actions: Analyze Current Situation, One-click Update, One-click Repair, Advanced Analysis. Each must map to exactly one service contract and surface failures truthfully.

### G15 Self-Test
PASS requires deterministic offline tests for domain, engine, storage, evidence, service, and packaged-resource access.

### G16 Contract Test
PASS requires automated tests proving signatures, return schemas, error semantics, UI-service mapping, and backward compatibility for frozen contracts.

### G17 Fault Injection
PASS requires injected timeout, DNS/network failure, 429, 5xx, malformed JSON, wrong content type, truncated payload, hash/schema mismatch, read-only storage, corrupt local DB, interrupted atomic replace, and stale-cache conditions.

### G18 Real Network
PASS requires a real allowlisted endpoint call from the acceptance runner with recorded URL/source ID, HTTP status, content type, retrieval time, payload hash, parser result, and truthfully failed status if network validation cannot complete.

### G19 Windows Build
PASS requires native Windows x64 build on GitHub Actions from the committed source.

### G20 Exact EXE
PASS requires tests to execute the exact produced EXE, not source Python, and verify self-test/health behavior against packaged resources.

### G21 GUI Smoke
PASS requires the exact EXE GUI to launch on Windows, create its main window, expose all four primary controls, invoke each control's service path in a smoke-safe mode, and exit cleanly.

### G22 Same Hash
PASS requires SHA-256 captured immediately after build, after acceptance, and after final artifact staging. All hashes must match the exact EXE delivered.

### G23 Final Gate
PASS = all G01-G22 PASS and no hard failure.
Any non-PASS value anywhere forces FAIL.

### G24 Unique Final Artifact
PASS requires exactly one final user-facing package for the accepted version, containing the exact accepted EXE plus machine-readable acceptance report and SHA-256 manifest. No alternate "final" binaries are allowed for the same version.

## Current v0.1.0 disposition

v0.1.0 is REVOKED_AS_FINAL under this stricter protocol.
It is retained only as a runnable prototype/reference build.

Known covered areas: partial Engine, UI, Self-Test, Windows Build, Exact EXE self-test, single SHA-256 evidence.
Known missing hard gates: formal Domain Model, architecture contract, function inventory, stable interface contract, source registry, hardened NetClient, Storage layer, Evidence layer, Service layer, Contract Test, Fault Injection, Real Network acceptance, GUI Smoke, true Same-Hash staging, strict aggregate Final Gate, and Unique Final Artifact semantics.
