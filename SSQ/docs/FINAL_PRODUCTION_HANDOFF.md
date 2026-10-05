# SSQ Final Production Handoff Contract

Status: **NOT FINAL until the independent-repository Final Gate reports PASS.**

This document is normative for the SSQ production handoff. It does not relax any machine gate.

## 1. Independent production identity

Required production repository:

`douluo511/Geometry-Lotto-Pro-SSQ`

The production identity must be independent for repository, code, data, configuration, model/content, updater, Windows build, Exact EXE, release, evidence, Same Hash and Final Gate.

A run in `douluo511/Geometry-Lotto-Pro` can prove engineering behavior, but cannot satisfy `repository_independence` or `release_context`.

## 2. Frozen architecture

```text
Product / Governance
        ↓
Domain
        ↓
Official Sources
        ↓
NetClient
        ↓
Storage
        ↓
Engine
        ↓
Validation
        ↓
Evidence
        ↓
Application Service
        ↓
UI
        ↓
Independent Updater
        ↓
Release
        ↓
Windows Native Build
        ↓
Exact EXE
        ↓
Physical GUI Click
        ↓
Same Hash
        ↓
Final Gate
```

Layer rules:
- UI calls Service only.
- Engine performs no network I/O.
- Sources do not bypass NetClient.
- Production network failures never fall back to demo/mock as success.
- Evidence is a first-class production module.

## 3. Data lifecycle

```text
RAW → VALIDATED → CANONICAL → FEATURE/KNOWLEDGE → RESULT → EVIDENCE
```

A failed source/validation/cross-check must preserve the previous canonical state and emit failure evidence.

## 4. Network contract

NetClient is the only production network entry point.

Required controls:
- HTTPS and TLS verification.
- explicit connect/read timeouts.
- finite retry.
- exponential backoff plus jitter.
- bounded Retry-After.
- host allowlist.
- redirect validation.
- Content-Type validation.
- RAW bytes + SHA-256 persistence.
- request/attempt ledger.
- Fail Closed.

Required failure matrix includes DNS/TLS/403/404/429/5xx/connect timeout/read timeout/reset/truncated response/wrong media type/invalid JSON or HTML/empty payload/schema drift/missing fields/duplicates/stale or future data/source conflict/cross-host redirect/HTTPS downgrade/raw-hash corruption.

## 5. Core interfaces

```python
class NetClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        source_id: str,
        params=None,
        headers=None,
        body=None,
        connect_timeout: float,
        read_timeout: float,
        max_attempts: int,
        allowed_hosts: frozenset[str],
    ) -> NetworkResult: ...
```

```python
class SourceProvider(Protocol):
    def fetch_raw(self, client, request) -> RawPayload: ...
    def validate(self, raw) -> ValidatedPayload: ...
    def normalize(self, validated) -> CanonicalDataset: ...
```

```python
class StorageService(Protocol):
    def stage_raw(self, raw) -> ArtifactId: ...
    def stage_validated(self, data) -> ArtifactId: ...
    def commit_canonical(self, dataset, expected_previous_hash: str) -> DatasetVersion: ...
    def rollback(self, transaction_id: str) -> None: ...
```

```python
class Engine(Protocol):
    def run(self, dataset: CanonicalDataset, config: FrozenConfig) -> EngineResult: ...
```

```python
class ApplicationService(Protocol):
    def core_action(self, request): ...
    def update_all(self): ...
    def repair(self): ...
    def advanced_analysis(self, request): ...
```

```python
class UpdateService(Protocol):
    def check_manifest(self): ...
    def download(self, manifest): ...
    def verify(self, artifact): ...
    def install(self, artifact): ...
    def healthcheck(self, transaction): ...
    def rollback(self, transaction): ...
```

## 6. Evidence binding

Every production result/release must bind at least:
- source commit.
- dataset hash.
- config hash.
- model hash.
- result hash.
- Exact EXE SHA-256.
- updater SHA-256.
- GitHub run identity.
- evidence hashes.

A PASS from an older behavior-changing commit is invalid for a newer commit.

## 7. Production release transaction

The required closure path is:

```text
verified export
→ independent main
→ v8.5.0 baseline prerelease
→ hash/bytes/self-test-bound manifest
→ APP_VERSION-only advance to v8.5.1
→ independent Windows build
→ v8.5.1 prerelease
→ real HTTPS updater: 8.5.0 → 8.5.1
→ PID handoff / backup / atomic replace
→ health check and rollback proof
→ Physical GUI Click
→ Same Hash
→ Final Gate
→ promote v8.5.1 to formal Release
→ upload unique Final EXE
```

Neither v8.5.0 nor v8.5.1 may be called Final before the last Final Gate.

## 8. Physical GUI acceptance

The four desktop entries must be exercised against the Exact EXE:
- prediction/core action.
- one-click update.
- one-click repair.
- advanced analysis/audit.

Acceptance requires real child-control hit testing and physical mouse event delivery, visible UI effect and backend ledger/evidence effect.

Process launch alone is not GUI acceptance.

## 9. Same Hash

The following identities must be equal for the final deliverable:
- primary deterministic build.
- isolated deterministic rebuild.
- Exact EXE acceptance input.
- real-network-tested EXE.
- Physical-GUI-tested EXE.
- Final Gate EXE.
- user-delivered EXE.

Any mismatch is Final Gate FAIL.

## 10. Final Gate semantics

Only literal PASS counts.

PENDING / WARNING / SKIPPED / UNAVAILABLE / UNKNOWN are NOT PASS.

Final requires:
- engineering completeness = 100%.
- business content completeness = 100%.
- hard_fail_count = 0.
- real_network = PASS.
- fault_injection = PASS.
- business_validation = PASS.
- counterexample_validation = PASS.
- reversal_validation = PASS.
- windows_build = PASS.
- exact_exe = PASS.
- physical_gui_click = PASS.
- same_hash = PASS.
- updater_real_network = PASS.
- repository_independence = PASS.
- release_context = PASS.
- Final Gate = PASS.

## 11. Current handoff blocker

The connected GitHub App can write code, branches and PRs and inspect Actions/artifacts, but does not expose repository-administration writes.

The final bootstrap workflow therefore requires the explicit repository secret:

`SSQ_REPO_ADMIN_TOKEN`

It must be authorized to create/push `douluo511/Geometry-Lotto-Pro-SSQ`.

No token / no independent repository / no Final claim.


## 12. Finalization trigger audit

2026-10-02: user explicitly re-authorized continued execution toward the unique Final artifact. This documentation-only commit intentionally retriggers the branch-bound production bootstrap and full Windows acceptance. It does not waive any gate and must not be used as evidence by itself.
