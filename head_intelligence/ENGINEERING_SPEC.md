# Head Intelligence — Frozen Engineering Contract

Version target: 0.4.0

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
Every current-run gate must be explicit PASS: purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, unit_test, contract_test, integration_test, fault_injection, real_network, business_validation, counterexample_validation, reversal_validation, windows_build, exact_exe, gui_smoke, physical_gui_click, same_hash, business_content. The gate input must be derived from current-run evidence; hardcoded PASS is prohibited. Any missing, UNKNOWN, WARNING, PENDING, SKIPPED, UNAVAILABLE, CANCELLED or FAIL state => Final Gate FAIL.

## Unique Product
One version, one EXE, one SHA256, one final report. Behavior-code changes invalidate all previous acceptance.
