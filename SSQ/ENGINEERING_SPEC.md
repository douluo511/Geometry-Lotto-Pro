# Geometry Lotto Pro SSQ — Frozen Engineering Contract

Target line: 8.5.x verification/hardening until an independent-repository release is qualified.

## Requirement / Purpose Model
Maintain a self-contained Windows SSQ research application with four real entries: 预测下一期 / 一键更新 / 一键修复 / 高级分析. Prediction paths fail closed and never claim validated edge without the frozen scientific protocol. The distributable main EXE embeds an independently built and hash-bound updater EXE so update/repair work executes across a real process boundary while the user can still receive one top-level product EXE.

## 5 Why
Historical “Final” labels failed because source, package, GUI, updater and scientific checks were not bound to the same bytes and current run. Therefore release is bound to current-run evidence for the exact main EXE, exact updater EXE, live official data, release-host update evidence, fault paths, rollback, scientific evidence, GUI effects, Same Hash, repository independence and an evidence-derived Boolean Final Gate.

## Risk Boundary
No mock may satisfy production Real Network. Cache cannot masquerade as live data. Synthetic fault injection cannot satisfy live update. Updater local self-test cannot substitute for a real release-host manifest/artifact transaction. Unknown/WARNING/PENDING/SKIPPED/UNAVAILABLE are non-PASS. Lottery rankings are research outputs; no guaranteed-win claim.

## Domain Model
Draw / CanonicalDataset / SourceReceipt / scientific Evidence / UpdateManifest / UpdaterTransaction are the canonical domain concepts.

## Architecture
Win32 UI → Application boundary:
- prediction / audit → LottoService → Engine / Evidence / Storage / Sources → NetClient → official data sources;
- data update / repair → UpdaterClient → independently built Updater EXE → LottoService / Store;
- software update → independently built Updater EXE → trusted HTTPS release manifest → exact artifact SHA256/size verification → same-volume staging → atomic replacement → exact new-main self-test → preserved previous bytes / automatic rollback.

The updater is a distinct Windows process and exact artifact. A same-process method call does not satisfy the updater gate.

## Function / Interface Contract
The four UI entries route to:
- 预测下一期 → LottoService.predict
- 一键更新 → UpdaterClient.update
- 一键修复 → UpdaterClient.repair
- 高级分析 → LottoService.audit

Software replacement is an updater-only contract: software-update requires target EXE + trusted HTTPS manifest URL and supports waiting for the main process to exit before replacement.

## Data Sources
Primary lottery history: 中国福利彩票发行管理中心 API.
Cross-check: 上海市福利彩票发行中心 + 河北省福利彩票发行管理中心 official surfaces.
All live responses remain fail-closed and source receipts retain status/hash/count/latest issue.

Software release sources are separate from lottery data sources. Software upgrade ordering is determined from the installed target EXE's exact self-test version, not from the updater binary's own build version. The updater must fail before any release-network request if the installed target cannot prove its current version. The software trust root is pinned to the target independent repository `douluo511/Geometry-Lotto-Pro-SSQ`: manifest requests must identify that repository and artifact requests must use that repository's release/download path. Generic GitHub domains or another repository are not sufficient trust. GitHub object/release-asset hosts are accepted only as HTTPS redirect targets reached from an already verified repository URL. The release manifest binds app identity, version, artifact URL, exact SHA256 and byte count.

## NetClient
Lottery sources: HTTPS only; independent connect/read timeout; bounded retries for idempotent GET; 408/429/5xx handling; exponential backoff; redirect downgrade rejection; no retry-as-success fabrication.

Updater release transport: HTTPS allowlist, bounded three-attempt retrieval, connect/read timeout, 429/5xx bounded retry, final redirect host validation, maximum manifest/artifact size, raw receipt hash and fail-closed terminal errors.

## Storage
SQLite and immutable prediction freeze rules remain owned by Store. Corrupt-repair and tamper checks are mandatory. Network data updates are committed only after integrity validation.

Software updater staging occurs on the target volume. The old target bytes are moved to rollback storage before replacement. New bytes are accepted only after exact SHA256 read-back and exact main-EXE self-test. Failed post-replace validation restores the prior exact bytes. A successful update preserves the previous exact EXE for recovery.

## Engine / Evidence
Scientific promotion remains governed by the frozen false-edge firewall, random baseline, walk-forward OOS/holdout, bootstrap, multiple testing controls, leakage checks, ablation, null worlds, stability, counterexamples, reversal validation and dual confirmation. NO_EDGE / NULL_DAN is a valid scientific result.

## Service / UI
UI owns no production data retrieval or scientific calculation. Service is the prediction/audit business boundary. Update/repair UI actions are routed to UpdaterClient and must execute an independently hash-verified updater process. GUI smoke alone does not prove process execution; exact updater process evidence is separate.

## Independent Updater / Repair Process
Required current-run evidence:
1. updater_process = PASS: updater PID differs from main/build parent and parent binding is machine verified;
2. updater_exact_exe = PASS: exact updater EXE exists, has current-run SHA256, and all accepted updater modes execute from those bytes;
3. updater_atomic_rollback = PASS: exact updater EXE proves same-volume staging, atomic replacement, previous-byte preservation, injected post-replace failure and exact-byte rollback;
4. updater_real_network = PASS: exact updater EXE performs a real HTTPS software manifest + main-artifact transaction against the product’s independent release repository and binds manifest/raw/artifact/install hashes;
5. updater_same_hash = PASS: updater EXE hash equals the hash embedded in the accepted main EXE bundle and the separately accepted updater artifact.

Local software-self-test can prove mechanics but never updater_real_network. While the product has no independent release repository/artifact, updater_real_network remains PENDING and Final Gate must FAIL.

## Self-Test / Unit / Contract / Integration / Fault Injection / Real Network
Source self-test plus Unit, NetClient Contract, Integration, integrity-tamper, offline-failclosed, corrupt-repair, live official update, updater software-transaction self-test and updater fault paths are hard gates. Every substantive behavior change invalidates affected acceptance evidence.

## Windows Build / Exact EXE / Physical GUI / Same Hash
Native Windows PyInstaller builds the updater EXE first and accepts its exact bytes. Those exact updater bytes + manifest are embedded into the main EXE. The main EXE is then built and all exact-EXE checks execute against the same bytes. Native physical GUI click evidence binds each visible control to backend evidence. Main and updater hashes are independently checked and cross-bound.

## Business Content Gate
BUSINESS_SPEC.md must PASS together with dynamic scientific validation, counterexample validation and reversal validation. Engineering PASS alone is not project completion.

## Repository Independence
This shared Geometry-Lotto-Pro repository is migration/acceptance only. Here repository_independence = FAIL by policy. Final promotion requires the SSQ product to live in its own repository, rerun the full chain there, and publish release-host updater evidence from that independent repository. The gate is machine-derived from GitHub Actions identity: only `GITHUB_ACTIONS=true`, exact `GITHUB_REPOSITORY=douluo511/Geometry-Lotto-Pro-SSQ`, and `GITHUB_SERVER_URL=https://github.com` can produce `repository_independence=PASS`; no CLI/manual PASS override exists.

## Final Gate
All hard gates must be exactly PASS:
purpose_model, five_why, risk_boundary, domain_model, architecture,
function_contract, interface_contract, data_source, netclient, storage,
engine, evidence, service, ui, self_test, unit_test, contract_test,
integration_test, fault_injection, real_network, business_validation,
counterexample_validation, reversal_validation, windows_build, exact_exe,
gui_smoke, same_hash, business_content, updater_process, updater_exact_exe,
updater_atomic_rollback, updater_real_network, updater_same_hash,
repository_independence.

Any FAIL/PENDING/WARNING/UNAVAILABLE/SKIPPED/UNKNOWN => FINAL_GATE=FAIL.

## Unique Product
The user-facing deliverable remains one top-level main EXE. That main EXE embeds the separately built and accepted updater EXE bytes plus a hash manifest; at runtime the updater is materialized and executed as a distinct process. Final delivery is allowed only after main EXE + embedded updater bytes + release-host updater path all match current-run evidence and Final Gate PASS.

Behavior, model, rules, data chain, source parser, updater, build, UI→Service/Updater binding, release policy or production parameter changes invalidate prior acceptance.

## Portfolio FINAL Promotion Rules

Portfolio FINAL is stricter than staging acceptance and cannot be inferred from a green PR.

- Repository identity is machine-derived. FINAL requires `GITHUB_REPOSITORY=douluo511/Geometry-Lotto-Pro-SSQ` under GitHub Actions.
- Release context is machine-derived. FINAL requires the independent repository frozen `main` branch and event `push` or explicit `workflow_dispatch`. Pull requests and candidate branches are acceptance-only.
- The exact main EXE must report a stable release SemVer. Verification/prerelease versions such as `8.5.0-verification` are non-PASS for `release_version` and can never be labeled Portfolio FINAL.
- Real software-update acceptance must download the verified prior release and current candidate from the independent repository over HTTPS, validate manifest/artifact SHA256 and byte counts, and prove an actual N→N+1 version transition.
- Updater handoff must use the verified prior-release Exact main EXE itself as the live wait target. A synthetic sleeper/process is insufficient. Final evidence binds the prior-main PID, SHA256 and version to the updater wait proof.
- The acceptance candidate release is explicitly non-FINAL. If Final Gate later passes, promotion must reuse the exact already-tested EXE bytes; no rebuild is allowed.
- Audit evidence must upload successfully before the user-facing FINAL artifact. The user-facing FINAL artifact contains one main Windows EXE only; audit evidence is stored separately.
- Any change to version, release workflow, source/parser, updater, model/rules, UI→Service binding, or evidence contracts invalidates prior PASS and requires the complete chain again.

