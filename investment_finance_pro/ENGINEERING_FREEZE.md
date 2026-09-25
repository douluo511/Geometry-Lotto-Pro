# Investment Finance Pro — Engineering Freeze v1.0

This file freezes the non-degradable delivery line for Investment Finance Pro.

## 0. Final rule

FINAL PASS is allowed only when every hard gate below is explicitly PASS and the exact EXE delivered to the user has the same SHA-256 as the EXE that passed the EXE tests and GUI smoke.

Anything else is NOT FINAL: FAIL / PARTIAL / PENDING / SKIPPED / WARNING / UNKNOWN / UNAVAILABLE.

## 1. 需求 / 目的建模

Goal: build a research-grade investment decision desktop system that helps the user study capital allocation, valuation, risk and progress toward financial freedom.

Non-goal: claim guaranteed returns or convert an unvalidated ranking into a buy/sell signal.

Primary user flows:
1. 投资机会
2. 一键更新
3. 一键修复
4. 高级分析

## 2. 5 Why

Problem: "投资软件看起来更新了，但可能仍使用旧数据或假信号。"

1. Why can a UI look updated while evidence is stale? Because UI success may be disconnected from source provenance.
2. Why can provenance be disconnected? Because network fetch, cache and engine are not contract-bound.
3. Why can model output look strong but be false? Because in-sample ranking can be mistaken for validated edge.
4. Why can packaged behavior differ from source behavior? Because source tests do not prove the built EXE works.
5. Why can the final artifact still differ from the tested EXE? Because artifact identity was not bound by hash.

Root controls:
- explicit source lineage and update state
- UNVALIDATED state until scientific validation passes
- source tests + exact EXE tests + GUI smoke
- same-hash gate between tested EXE and delivered EXE
- machine-readable final gate

## 3. 风险边界

Hard boundaries:
- no guaranteed return claims
- no silent fallback to stale cache as a successful live update
- no VALIDATED model state without independent validation evidence
- no final PASS when any hard gate is non-PASS
- no mutation of tested EXE after hash capture
- no hidden source substitution: provider name must be recorded

## 4. Domain Model

Core entities:
- MarketBar: date/open/high/low/close/volume
- MarketSnapshot: per-symbol metrics + provider lineage + timestamp
- MacroObservation: series/date/value/provider
- ResearchRank: symbol/metrics/score/status
- EvidenceRecord: source/test/status/detail/hash
- UpdateResult: PASS/PARTIAL/FAILED + providers + snapshot
- RepairResult: checks + overall
- ReleaseEvidence: source tests + network + EXE tests + GUI smoke + hashes + final gate

State enums:
- UpdateState: PASS | PARTIAL | FAILED
- ModelState: UNVALIDATED | VALIDATED
- GateState: PASS | FAIL

## 5. 架构图

UI
  -> Service / Orchestrator
    -> Engine
      -> NetClient / Providers
      -> Storage
      -> Evidence
    -> Repair
    -> Validation

Release path:
Source
  -> Self-Test
  -> Contract Test
  -> Fault Injection
  -> Real Network
  -> Windows Build
  -> Exact EXE Self-Test
  -> Exact EXE Real Network
  -> GUI Smoke
  -> Same Hash
  -> Final Gate
  -> Unique Artifact

## 6. 函数清单

Production:
- fetch_text
- fetch_yahoo_history
- fetch_stooq_history
- fetch_market_history
- fetch_fred_series
- compute_metrics
- rank_research
- one_click_update
- repair_system
- deterministic_self_test
- network_smoke_test
- run_gui

Verification:
- contract_test
- fault_injection_test
- sha256_file
- evaluate_final_gate

## 7. 接口契约

one_click_update() -> dict
Required keys:
- app
- version
- research_only
- model_status
- update_state
- updated_at_utc
- providers
- macro
- metrics
- ranking

Rules:
- model_status must remain UNVALIDATED unless a separate scientific promotion gate exists
- every live provider attempt must produce a provider evidence row
- update_state PASS only if all required live-provider checks pass
- PARTIAL when useful market data exists but one or more required checks fail
- FAILED when no usable market data exists

repair_system() -> dict
Required keys:
- overall
- checks
- at_utc

## 8. 数据源

Current MVP:
- Yahoo Chart (market history, primary)
- Stooq (market history, fallback)
- FRED DGS10
- FRED DFF

Source identity must be present in the snapshot evidence.

## 9. NetClient

Required properties:
- HTTPS
- explicit timeout
- explicit User-Agent
- bounded provider fallback
- parse validation
- no fake success on network failure

Future hardening:
- retry only for idempotent GET
- exponential backoff + jitter
- 429 / 5xx policy
- payload hash and content-type evidence

## 10. Storage

- local app data directory
- atomic JSON replace
- corrupt-cache quarantine during repair
- stale cache may be displayed only as cached data, never as a successful live update

## 11. Engine

Current MVP engine is intentionally simple and transparent:
20-day momentum / annualized 20-day volatility / 60-day drawdown.

It is a research ranking only and MUST remain UNVALIDATED.

## 12. Evidence

Every release must preserve machine-readable evidence:
- source_self_test.json
- contract_test.json
- fault_injection.json
- source_network_smoke.json
- exe_self_test.json
- exe_network_smoke.json
- gui_smoke.json
- final_gate.json
- exact_exe_sha256.txt

## 13. Service

UI actions must map to service functions:
- 投资机会 -> cached ranking render
- 一键更新 -> one_click_update
- 一键修复 -> repair_system
- 高级分析 -> evidence / snapshot inspection

UI may not embed independent business logic that bypasses service behavior.

## 14. UI

Primary layout remains two rows by two columns:
投资机会 | 一键更新
一键修复 | 高级分析

## 15. Self-Test

Deterministic and offline. Must verify metric computation, nonnegative volatility, UNVALIDATED guard and writable storage.

## 16. Contract Test

Must fail if required function signatures or required result keys drift.

## 17. Fault Injection

Must prove:
- complete provider failure becomes FAILED
- partial source failure becomes PARTIAL, never PASS
- corrupt cache repair is explicit

## 18. Real Network

Must run on GitHub-hosted Windows before build and again against the built EXE.

## 19. Windows Build

PyInstaller single-file windowed x86-64 EXE.

## 20. Exact EXE

All EXE verification runs against dist/InvestmentFinancePro.exe before it is copied to final/.

## 21. GUI Smoke

Launch exact EXE, require process to stay alive for the smoke interval, then terminate it. Immediate exit/crash is FAIL.

## 22. Same Hash

SHA-256(dist/InvestmentFinancePro.exe) MUST equal SHA-256(final/InvestmentFinancePro.exe).

## 23. Final Gate

PASS iff:
- source self-test PASS
- contract test PASS
- fault injection PASS
- source real-network PASS
- exact EXE self-test PASS
- exact EXE real-network PASS
- GUI smoke PASS
- same hash true

## 24. 唯一成品

Only final/InvestmentFinancePro.exe is the releasable executable.

No alternate "final", "fixed", "new", "v2-final-final" binaries are allowed in the release artifact.
