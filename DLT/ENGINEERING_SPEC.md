# Geometry Lotto Pro DLT — Frozen Engineering Contract

Target version: 2.3.0-verification

## Requirement / Purpose Model
Provide a self-contained Windows DLT research app with four real entries: 预测下一期 / 一键更新 / 一键修复 / 高级分析. No guaranteed-win claim; production prediction remains fail-closed unless the frozen scientific gate passes.

## 5 Why
Prior delivery failures came from treating source tests or a named “Final” file as completion. The release must bind real official-network consensus, scientific validation, fault paths, GUI execution and the exact same EXE hash.

## Risk Boundary
No mock may satisfy Real Network. Cache cannot masquerade as live data. Official-source disagreement fails closed. Any FAIL/PENDING/WARNING/UNAVAILABLE/SKIPPED/UNKNOWN blocks release.

## Domain Model
Draw / CanonicalDataset / SourceReceipt plus prediction, evidence and gate records.

## Architecture
UI -> LottoService -> Engine / Evidence / Storage / Sources -> NetClient -> official sources.

## Function / Interface Contract
The four UI entries route through Service. Source GETs use NetClient. Engine owns research calculations. Evidence records verifiable outcomes.

## Data Sources
Required Primary is Jiangsu Sports Lottery DLT history and required Secondary is Gansu Sports Lottery DLT history. Both must be live, agree on the latest draw and at least 10 overlapping draws. The national China Sports Lottery API is supplemental; WAF failure remains explicit FAIL and is never converted to source PASS. A stale trusted baseline may advance only through consecutive Primary+Secondary consensus.

## NetClient
HTTPS only; independent connect/read timeout; bounded idempotent GET retry; 408/429/5xx handling; exponential backoff; no fake success.

## Storage / Engine / Evidence / Service / UI
Storage owns persistence and recovery. Engine owns model computation. Evidence owns facts. Service owns orchestration. UI contains no source or model implementation.

## Self-Test / Contract Test / Fault Injection / Real Network
Source self-test, exact-package negative paths, corrupt repair, offline fail-closed, live official quorum and scientific tests are hard gates.

## Windows Build / Exact EXE / GUI Smoke / Same Hash
The Windows EXE is frozen once built. All acceptance is executed against those exact bytes, including native GUI smoke and SHA256 equality.

## Business / Scientific Gate
BUSINESS_SPEC.md and scripts/business_gate.py are a mandatory release gate. Engineering completion alone is not project completion.

## Final Gate
All mother-template gates plus business_content must be exactly PASS:
purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, contract_test, fault_injection, real_network, windows_build, exact_exe, gui_smoke, same_hash.

Any other state => FINAL_GATE=FAIL.

## Unique Product
One version, one EXE, one SHA256, one machine-readable final report. Any behavior-code change invalidates previous acceptance.
