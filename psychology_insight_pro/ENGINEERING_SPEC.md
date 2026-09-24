# Psychology Insight Pro — Frozen Engineering & Release Contract

Version target: 0.2.0

## 1. Requirement / Purpose Model
Goal: turn observable conversation/behavior evidence into calibrated, competing psychological hypotheses for reflection and communication support.

Non-goals:
- no mind-reading claims;
- no lie-detector claims;
- no mental-health diagnosis;
- no coercive or exploitative targeting of vulnerabilities.

Primary user flow:
Input -> Observations -> Baseline comparison -> Competing hypotheses -> Evidence/counter-evidence -> 5 Why -> Reverse validation -> Guidance -> Outcome feedback (future).

## 2. 5 Why
1. Why not output one answer? Because the same behavior can have multiple causes.
2. Why keep alternatives? To reduce confirmation bias and false certainty.
3. Why keep evidence lineage? So every inference is auditable.
4. Why calibrate confidence? Sparse evidence must not become strong claims.
5. Why outcome feedback? Rules that do not survive real outcomes should be downgraded or removed.

## 3. Risk Boundary
Hard boundaries are encoded in contracts and UI:
- probabilistic inference only;
- explicit uncertainty;
- no diagnosis / lie detection / certainty claims;
- important decisions require direct communication and later behavior verification.

## 4. Domain Model
Observation, Evidence, Hypothesis, AnalysisResult, SourceRecord, UpdateResult, GateReport.

## 5. Architecture
UI -> Application Service -> Engine -> Evidence -> Domain
                         -> Storage
                         -> NetClient -> Real Network
Self-Test / Contract Test / Fault Injection operate across the same public contracts.

## 6. Function / API Contract
Service:
- analyze_text(text, baseline_text="") -> AnalysisResult
- update_knowledge() -> UpdateResult
- repair() -> dict
- health() -> dict

NetClient:
- get_json(url, validator) -> (payload, SourceRecord)

Storage:
- load_knowledge() -> dict
- replace_knowledge(payload, source) -> None
- repair_knowledge() -> dict

Engine:
- analyze(text, knowledge, baseline_text="") -> AnalysisResult

## 7. Data Source
Production update source:
https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/psychology_insight_pro/knowledge.json

Network success requires: HTTPS, bounded size, content/schema validation, payload SHA256, source URL and HTTP status evidence.

## 8. NetClient
- explicit connect/read timeout equivalent through urllib timeout;
- GET only;
- finite retry only for transient network errors, 429 and 5xx;
- exponential backoff + jitter;
- bounded body;
- content-type check;
- SHA256 lineage;
- failure never reported as fresh-network success.

## 9. Storage
- AppData scoped;
- schema validation before replacement;
- backup before replacement;
- fsync + atomic os.replace;
- corruption repair from bundled known-good knowledge.

## 10. Evidence
Every network update records source URL, fetch timestamp, HTTP status and SHA256.
Every hypothesis keeps support/counter-evidence.

## 11. Tests
Self-Test: deterministic internal capability test.
Contract Test: public interfaces and schemas.
Fault Injection: corrupt local file, invalid schema, oversize payload, HTTP 500/429 path, network failure fallback behavior.
Real Network: fetch and validate GitHub source.
Exact EXE: run the built EXE itself with self-test.
GUI Smoke: the built EXE must initialize Tk, create/update/destroy the real main window.
Same Hash: hash before final staging must equal hash of the staged final EXE.

## 12. Final Gate
PASS iff every hard gate is exactly PASS:
self_test, contract_test, fault_injection, real_network, windows_build, exact_exe, gui_smoke, same_hash.

WARNING / SKIPPED / UNAVAILABLE / UNKNOWN / FAIL => Final Gate FAIL.

## 13. Unique Product
Audit artifacts may be stored separately, but the final deliverable artifact contains exactly one file:
Psychology_Insight_Pro.exe
