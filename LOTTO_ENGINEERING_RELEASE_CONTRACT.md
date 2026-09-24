# Geometry Lotto Pro — Unified Engineering & Release Contract

Applies identically to DLT and SSQ. This order is mandatory and non-skippable.

## Frozen master line

需求/目的建模 → 5 Why → 风险边界 → Domain Model → 架构图 → 函数清单 → 接口契约 → 数据源 → NetClient → Storage → Engine → Evidence → Service → UI → Self-Test → Contract Test → Fault Injection → Real Network → Windows Build → Exact EXE → GUI Smoke → Same Hash → Final Gate → 唯一成品

## Stage contract

1. 需求/目的建模
   - Define the user goal, non-goals, success criteria, failure semantics and acceptance evidence.
   - Prediction quality must never be implied merely because the UI returns numbers.

2. 5 Why
   - Root-cause the current failure/problem before code changes.
   - No patch-by-symptom workflow.

3. 风险边界
   - Freeze safety, scientific, network, storage, update, rollback and release boundaries.
   - Any unknown/ambiguous critical state is fail-closed.

4. Domain Model
   - DLT and SSQ have separate immutable game rules, draw entities, prediction entities, evidence entities and freeze entities.
   - No cross-game data/model contamination.

5. 架构图
   - UI → Application/Service → Domain/Engine/Evidence → Storage/NetClient → External official sources.
   - UI contains no scientific/network/storage business logic.

6. 函数清单
   - Every public behavior has an owner function, inputs, outputs, side effects, error modes and test coverage.

7. 接口契约
   - Freeze signatures and schemas before implementation.
   - Behavior-changing contract changes require version bump and full revalidation.

8. 数据源
   - Official sources only for production canonical data.
   - Source identity, fetch time, HTTP status, raw hash, parser/schema version and canonical hash must be recorded.

9. NetClient
   - Explicit connect/read timeout.
   - Limited retry only for idempotent reads.
   - Exponential backoff + jitter.
   - 429/5xx handling.
   - Content-Type/schema/hash validation.
   - Multi-source quorum/fallback.
   - Failed live fetch can never be reported as cached success.

10. Storage
    - Atomic writes.
    - SQLite handles explicitly closed on Windows.
    - Canonical hash verification.
    - Immutable Freeze.
    - Ledger integrity check, backup, rebuild and rollback evidence.

11. Engine
    - Candidate-model pool is broad; production-model pool is narrow.
    - Only frozen VALIDATED_EDGE members may receive production weight.
    - NO_EDGE/UNVALIDATED members have zero production weight.

12. Evidence
    - Walk-forward OOS.
    - Random baseline.
    - Bootstrap.
    - Reality Check / Holm.
    - Leave-One-Era-Out.
    - Remove/Shuffle/Random ablation.
    - Model correlation/incremental information.
    - Leakage Sentinel.
    - Null-world FPR.
    - Untouched holdout.
    - Dual confirmation.
    - Multi-window/model/seed stability.
    - Scientific PASS means the falsification system executed correctly; it does not force EDGE_PROVEN.

13. Service
    - Four UI entries map 1:1 to service functions.
    - Predict is autonomous: live update → canonical → evidence → production selector → immutable freeze.
    - Update, Repair and Advanced Analysis are separately testable and fail-closed.

14. UI
    - Fixed four-entry desktop layout:
      预测下一期 | 一键更新
      一键修复   | 高级分析
    - UI is a thin adapter to Service.
    - All clickable entries must route to real service behavior.

15. Self-Test
    - Deterministic local checks for rules, contracts, hashes, immutable freeze, ledger integrity, leakage rejection and recovery.

16. Contract Test
    - Verify function signatures, schemas, UI→Service mapping, error semantics and backward-incompatible changes.

17. Fault Injection
    - Offline.
    - Timeout.
    - 429/5xx.
    - Bad content type.
    - Malformed JSON/HTML.
    - Schema drift.
    - Hash mismatch.
    - Partial/corrupt canonical file.
    - Corrupt SQLite/WAL/SHM.
    - Duplicate/stale draw.
    - Source disagreement.
    - Model/evidence mismatch.
    - Freeze tampering.

18. Real Network
    - Run against real official endpoints from CI/Windows runner.
    - Record receipts and quorum outcome.
    - No mock result may satisfy this gate.

19. Windows Build
    - Build native self-contained Windows x64 EXE with pinned build environment.
    - End user must not need Python.

20. Exact EXE
    - All final acceptance checks run against the exact built EXE bytes, not a source-tree surrogate.

21. GUI Smoke
    - Native Win32 window creation.
    - Four controls exist.
    - Real command routing reaches the intended service method.
    - Default double-click/no-argument launch remains alive.
    - Unicode/space path behavior verified.

22. Same Hash
    - SHA-256 of tested EXE == SHA-256 recorded in acceptance report == SHA-256 of delivered EXE.

23. Final Gate
    - PASS iff:
      hard_fail_count == 0
      AND final_release_gate == PASS
      AND exact_exe_acceptance == PASS
      AND same_hash == PASS
      AND required Real Network gate == PASS.
    - FAIL/UNAVAILABLE/SKIPPED/WARNING/PENDING/UNKNOWN can never be promoted to final PASS.

24. 唯一成品
    - Only one final artifact per game/version.
    - No Candidate/old build may be labeled Final.
    - Any behavior-code change invalidates the previous final package and reruns the entire chain.

## Non-regression rule

Every behavior change in DLT or SSQ must restart at the earliest affected stage and must still rerun all downstream release gates through Exact EXE, Same Hash and Final Gate.

## Production model rule

全模型候选池 → 全模型证伪 → 有效模型晋级 → 无效模型零权重/DEAD_PATH → Champion/Ensemble Freeze → Windows EXE → exact-package 重验 → same-hash → final_release_gate == PASS → 唯一 final artifact.

Allowed model states:
- VALIDATED_EDGE
- NO_EDGE
- UNVALIDATED

If no model is VALIDATED_EDGE, production Champion is the auditable random/uniform baseline. The system must not manufacture a Dan/edge merely to produce an answer.
