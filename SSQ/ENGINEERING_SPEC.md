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

Software release sources are separate from lottery data sources. Only explicit trusted HTTPS GitHub release/raw hosts are accepted by the updater. The release manifest binds app identity, version, artifact URL, exact SHA256 and byte count.

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
This shared Geometry-Lotto-Pro repository is migration/acceptance only. Here repository_independence = FAIL by policy. Final promotion requires the SSQ product to live in its own repository, rerun the full chain there, and publish release-host updater evidence from that independent repository.

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
