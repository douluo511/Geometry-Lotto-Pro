# Psychology Insight Pro — Frozen Engineering & Release Contract

Version target: 0.2.1

## 1. Requirement / Purpose Model
Goal: turn observable conversation/behavior evidence into calibrated, competing psychological hypotheses for reflection and communication support. No mind-reading, lie-detector, diagnosis, coercion, or exploitation claims.

## 2. 5 Why
Single-answer certainty creates confirmation bias; competing hypotheses, lineage, confidence calibration, reverse validation, and later outcome feedback are required.

## 3. Risk Boundary
Inference stays probabilistic and auditable. Unknown/failed evidence never becomes PASS. Network/cache failures are surfaced explicitly.

## 4. Domain Model
Observation, Evidence, Hypothesis, AnalysisResult, SourceRecord, UpdateResult.

## 5. Architecture
UI -> Service -> Engine / Storage / NetClient / Evidence -> Data Source. UI may compose only through create_service and does not directly call Network or Storage.

## 6. Function / API Contract
Service: analyze_text, update_knowledge, repair, health. Engine: analyze, self_test. NetClient: get_json. Storage: load/replace/repair.

## 7. Data Source
Production HTTPS knowledge source is the repository raw knowledge.json. Real-network success requires HTTP/content/schema/hash lineage.

## 8. NetClient
Bounded GET retry, timeout, transient HTTP handling, content validation, SHA256 evidence, no cache-as-live success.

## 9. Storage
Schema validation, backup, fsync, atomic replace, repair from bundled known-good data.

## 10. Engine
Psychological hypotheses remain competing and calibrated; no fixed mind-reading result or unsupported certainty.

## 11. Evidence
Network updates and hypotheses retain auditable source/support/counter-evidence.

## 12. Service / UI
Service is the business orchestration boundary. UI binds only to Service and renders explicit success/failure.

## 13. Self-Test / Contract Test / Fault Injection / Real Network
All execute as hard gates. Mock/fallback cannot satisfy Real Network.

## 14. Windows Build / Exact EXE / GUI Smoke / Same Hash
Final Windows EXE is self-contained. Tests target the frozen EXE. Release artifact must be byte-identical to the tested EXE.

## 15. Final Gate
PASS iff every one of the 22 frozen hard gates is exactly PASS: purpose_model, five_why, risk_boundary, domain_model, architecture, function_contract, interface_contract, data_source, netclient, storage, engine, evidence, service, ui, self_test, contract_test, fault_injection, real_network, windows_build, exact_exe, gui_smoke, same_hash. Any FAIL/PENDING/WARNING/UNAVAILABLE/SKIPPED/UNKNOWN => FAIL.

## 16. Unique Product
One version, one EXE, one SHA256, one machine-readable final report. Any behavior-code change invalidates prior final acceptance.
