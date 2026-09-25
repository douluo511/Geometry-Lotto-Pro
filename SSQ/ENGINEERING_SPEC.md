# Geometry Lotto Pro SSQ — Frozen Engineering Contract

Target version: 8.5.0-verification

## Requirement / Purpose Model
Maintain a self-contained Windows SSQ research application with four real entries: 预测下一期 / 一键更新 / 一键修复 / 高级分析. Prediction paths must fail closed and never claim validated edge without the frozen scientific protocol.

## 5 Why
Historical “Final” labels failed because source, package, GUI and scientific checks were not bound to the same bytes. Therefore production release is bound to one exact EXE, live official sources, fault paths, scientific evidence, same hash and a Boolean final gate.

## Risk Boundary
No mock may satisfy production Real Network. Cache cannot masquerade as live data. Unknown/WARNING/PENDING/SKIPPED/UNAVAILABLE are release failures. Lottery rankings are research outputs; no guaranteed-win claim.

## Domain Model
Draw / CanonicalDataset / SourceReceipt and scientific evidence objects are the canonical domain.

## Architecture
Win32 UI -> LottoService -> Engine / Evidence / Storage / Sources -> NetClient -> official data sources.

## Function / Interface Contract
The four UI entries route to LottoService.predict / update / repair / audit. Source access is GET-only through NetClient.

## Data Sources
Primary: 中国福利彩票发行管理中心 API.
Cross-check: 上海市福利彩票发行中心 + 河北省福利彩票发行管理中心 official surfaces.
All live responses remain fail-closed and source receipts retain status/hash/count/latest issue.

## NetClient
HTTPS only; independent connect/read timeout; bounded retries for idempotent GET; 408/429/5xx retry; exponential backoff; no retry-as-success fabrication.

## Storage
SQLite and immutable freeze rules remain owned by Store. Corrupt-repair and tamper checks are mandatory.

## Engine / Evidence
Scientific promotion remains governed by the frozen false-edge firewall, random baseline, OOS/holdout, leakage, ablation, null worlds, stability and dual confirmation.

## Service / UI
UI owns no production data retrieval or scientific calculation. Service is the business entry boundary.

## Self-Test / Contract / Fault Injection / Real Network
Source self-test plus explicit integrity-tamper, offline-failclosed, corrupt-repair and live official update are hard gates.

## Windows Build / Exact EXE / GUI Smoke / Same Hash
PyInstaller output is frozen, all acceptance checks run on the exact EXE, native GUI routing is tested, default GUI must stay alive, Unicode-path/no-Python-PATH must pass, and release bytes must match tested SHA256.

## Business Content Gate
The scientific/business specification in BUSINESS_SPEC.md must also return PASS. Engineering PASS alone is not project completion.

## Final Gate
All mother-template engineering gates plus business_content must be exactly PASS:
purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, contract_test, fault_injection, real_network, windows_build, exact_exe, gui_smoke, same_hash.

Any FAIL/PENDING/WARNING/UNAVAILABLE/SKIPPED/UNKNOWN => FINAL_GATE=FAIL.

## Unique Product
One version, one EXE, one SHA256, one machine-readable report. Behavior changes invalidate old acceptance.
