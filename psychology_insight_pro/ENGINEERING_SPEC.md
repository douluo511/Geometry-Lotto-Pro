# Psychology Insight Pro — Frozen Engineering & Release Contract

Version target: 0.4.0

## 1. Requirement / Purpose Model
Goal: turn observable conversation/behavior evidence into calibrated, competing psychological hypotheses for reflection and communication support. No mind-reading, lie-detector, diagnosis, coercion, or exploitation claims.

## 2. 5 Why
Single-answer certainty creates confirmation bias; competing hypotheses, lineage, confidence calibration, reverse validation, counterexamples, and later outcome feedback are required.

## 3. Risk Boundary
Inference stays probabilistic and auditable. Unknown/failed evidence never becomes PASS. Network/cache failures are surfaced explicitly. The tool is not a mental-health diagnosis or a source of hidden personal facts.

## 4. Success / Failure Criteria
Success requires evidence-backed competing hypotheses, explicit uncertainty, business counterexample/reversal validation, strict network provenance, native Windows acceptance, physical GUI clicks, Same Hash and one unique artifact. Any missing/unknown/warning/pending/skipped/unavailable evidence is failure for Final.

## 5. Domain Model
Observation, Evidence, Hypothesis, AnalysisResult, SourceRecord, UpdateResult.

## 6. Architecture
UI -> Service -> Engine / Storage / NetClient / Evidence -> Data Source. UI may compose only through create_service and does not directly call Network or Storage.

## 7. Function / Interface Contract
Service: analyze_text, update_knowledge, repair, health. Engine: analyze, self_test. NetClient: get_json. Storage: load/replace/repair. UI core entries: 心理分析 / 一键更新 / 一键修复 / 高级分析.

## 8. Data Source
Production knowledge distribution uses two independently addressable HTTPS paths (GitHub Raw and jsDelivr CDN). A production network PASS requires at least two distinct source identities returning the same validated semantic package. Single-source availability or source conflict remains FAIL.

## 9. NetClient
Separate connect/read timeouts, finite retry budget, exponential backoff with injectable jitter, explicit 408/429/5xx handling, HTTPS-only, Content-Type/size/UTF-8/schema validation, exact raw bytes, SHA256, source identity, timestamp and full attempt ledger.

## 10. Storage
Schema validation, staged fsync writes, evidence-first/canonical-last commit, rollback on any persistence failure, repair from bundled known-good data. Knowledge and source evidence are bound by one commit identifier.

## 11. Engine
Psychological hypotheses remain competing and calibrated; no fixed mind-reading result or unsupported certainty.

## 12. Evidence
Network updates and hypotheses retain auditable source/support/counter-evidence. Current-run gate artifacts are machine-readable and are the only inputs accepted by Final Gate.

## 13. Service / UI
Service is the business orchestration boundary. UI binds only to Service and renders explicit success/failure. Network failure cannot be displayed as update success.

## 14. Validation
Self-Test -> Unit -> Contract -> Integration -> Fault Injection -> Real Network -> Business Validation -> Counterexample Validation -> Reversal Validation. Mock/fallback/cache cannot satisfy Real Network.

## 15. Windows Build / Exact EXE / Physical GUI / Same Hash
Final Windows EXE is self-contained. Tests target the frozen EXE. All four core GUI entries must be physically clicked through the desktop automation evidence. Release artifact must be byte-identical to the tested EXE.

## 16. Final Gate
PASS iff every current frozen gate is exactly PASS:
purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, unit_test, contract_test, integration_test, fault_injection, real_network, business_validation, counterexample_validation, reversal_validation, windows_build, exact_exe, gui_smoke, same_hash, business_content.

Any FAIL/PENDING/WARNING/UNAVAILABLE/SKIPPED/UNKNOWN/missing/stale/history => FAIL.

## 17. Unique Product
One version, one EXE, one SHA256, one machine-readable final report. Any behavior/config/model/data/network/UI/build/dependency change invalidates prior final acceptance and requires the downstream chain to rerun.
