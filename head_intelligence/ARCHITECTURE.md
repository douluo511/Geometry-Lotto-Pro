# Head Intelligence — Frozen Engineering Route

## Purpose

The product is not a news reader. It is an evidence-preserving information-intelligence system that turns a small set of verified, recent, decision-relevant primary-source items into an auditable judgment surface.

## Frozen route

需求/目的建模 → 5 Why → 风险边界 → Domain Model → 架构图 → 函数清单 → 接口契约 → 数据源 → NetClient → Storage → Engine → Evidence → Service → UI → Self-Test → Contract Test → Fault Injection → Real Network → Windows Build → Exact EXE → GUI Smoke → Same Hash → Final Gate → 唯一成品

## 5 Why

1. Why not just aggregate news? Because volume does not improve judgment.
2. Why preserve raw evidence? Because summaries alone cannot be audited.
3. Why separate Evidence from Engine? Because scoring logic must be testable independently.
4. Why require Service between UI and Engine? Because UI must not become hidden business logic.
5. Why exact-EXE/same-hash? Because source-code PASS does not prove the downloaded executable is the tested binary.

## Risk boundaries

- A source statement is not automatically a verified fact.
- Information-value score is not a probability of truth.
- One source appearing in many copies must not be treated as independent corroboration.
- Failed network updates must never overwrite the last known-good snapshot.
- Cache/fallback data must never be labeled as a successful fresh-network update.
- final_gate must be exactly PASS; WARNING/PENDING/SKIPPED/UNKNOWN do not count.

## Domain Model

Source → RawDocument → InformationItem → Evidence → Snapshot → Judgment Surface.

The current version implements Source, RawDocument, InformationItem, SourceHealth, UpdateReport and Snapshot persistence. Cross-source event clustering and hypothesis competition remain future capabilities and must not be claimed as complete.

## Architecture

UI
↓
Application Service
↓
Information Engine
├── Evidence Engine
├── NetClient
└── Atomic Storage
↓
Domain Model

## Function contracts

- NetClient.fetch(Source) -> RawDocument
- AtomicStorage.save_raw(RawDocument) -> Path
- AtomicStorage.save_json_atomic(name, dict) -> Path
- AtomicStorage.read_json(name) -> dict | None
- EvidenceEngine.deduplicate(items) -> items
- InformationEngine.one_click_update() -> UpdateReport
- InformationService.update() -> dict

## Release invariant

The only releasable artifact is final/HeadIntelligence.exe from a workflow where:
unit tests, contract tests, fault injection, Python self-test, real-network smoke, Windows build, exact-EXE self-test, GUI smoke, same-hash, final-copy self-test and final-copy GUI smoke all pass, and final_gate.json says final_gate: PASS.
