# English Root Intelligence — Frozen Engineering Contract

Version target: 0.2.0

## Requirement / Purpose Model
Understand vocabulary and spoken chunks through roots/prefixes/suffixes without inventing etymology. The system must support daily study, one-click update, repair, and analysis.

## 5 Why
Memorization fails when form, meaning and usage are disconnected; validated root data, conservative segmentation, repeated practice and auditable updates reduce false learning.

## Risk Boundary
No forced decomposition when evidence is weak; no fake live update; failed network/cache/storage states never display success.

## Domain Model
SourceReceipt and UpdateResult define network/update facts; root records are schema-validated.

## Architecture
UI -> Service -> Engine / Storage / NetClient / Evidence -> Data Source.

## Function Contract / Interface Contract
Service functions are the sole production UI boundary; contracts validate root and manifest schemas.

## Data Source
HTTPS update manifest plus hashed root dataset. Production network PASS requires actual remote response and matching SHA256.

## NetClient
Separate connect/read timeout, bounded GET retry, 429/5xx transient handling, backoff+jitter, content/size/hash evidence.

## Storage
Staging, fsync, schema validation, backup, atomic replace, post-write verification, rollback/repair.

## Engine
Conservative root analysis; low-confidence unknowns remain unknown rather than fabricated.

## Evidence / Service / UI
Evidence ledger records network/engine/storage facts. Service orchestrates. UI does not directly use Engine, Storage or NetClient.

## Self-Test / Contract Test / Fault Injection / Real Network
All are hard gates and failures are explicit.

## Windows Build / Exact EXE / GUI Smoke / Same Hash
Self-contained Windows EXE; exact artifact is tested, GUI-smoked, frozen and hash-bound.

## Final Gate
All 22 frozen hard gates must be exactly PASS; all other states fail.

## Unique Product
One EXE, one SHA256, one manifest/report. Any behavior-code change invalidates prior acceptance.
