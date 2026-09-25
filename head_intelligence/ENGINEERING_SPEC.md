# Head Intelligence — Frozen Engineering Contract

Version target: 0.2.1

## Requirement / Purpose Model
Collect, validate and structure research/head information so user judgments are based on traceable evidence rather than fixed or fabricated claims.

## 5 Why
Bad decisions commonly originate from stale/unverified information; therefore source lineage, competing interpretations, explicit failures, and reversible updates are mandatory.

## Risk Boundary
No fake live data, no cache-as-live, no silent network/storage failure, no unsupported certainty. Unknown states never become PASS.

## Domain Model
The existing domain.py is the canonical domain boundary.

## Architecture
UI -> Service -> Engine / Storage / NetClient / Evidence -> Data Source. Service is the application boundary.

## Function Contract / Interface Contract
contracts.py plus contract tests freeze callable names, parameters, result shapes, status values and UI bindings.

## Data Source / NetClient
Only validated real HTTPS responses satisfy the production network gate. Retries/timeouts are bounded and evidence retains source/status/hash.

## Storage
Atomic/validated storage behavior and recovery paths must pass fault injection.

## Engine / Evidence / Service / UI
Business calculation stays in Engine; Evidence records facts; Service orchestrates; UI does not own production logic.

## Self-Test / Contract Test / Fault Injection / Real Network
Each is a hard gate with explicit evidence.

## Windows Build / Exact EXE / GUI Smoke / Same Hash
Final EXE is self-contained, tested as the exact frozen artifact, GUI-smoked, then copied with identical SHA256.

## Final Gate
Exactly these 22 gates must all be PASS: purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, contract_test, fault_injection, real_network, windows_build, exact_exe, gui_smoke, same_hash. Any other state => FAIL.

## Unique Product
One version, one EXE, one SHA256, one final report. Behavior-code changes invalidate all previous acceptance.
