# English Root Intelligence — Frozen Engineering Contract

Version target: 0.4.0

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
Two independently addressable trusted HTTPS manifest paths plus two independently addressable data distribution paths. Production network PASS requires current-run raw responses, matching SHA256, semantic agreement, complete attempt ledgers, and source quorum.

## NetClient
Separate connect/read timeout, bounded GET retry, 429/5xx transient handling, backoff+jitter, content/size/hash evidence.

## Storage
Roots, progress and evidence are all staged before mutation; commit is rollback-safe across all three files. Any evidence/progress/data persistence failure leaves production roots/progress unchanged.

## Engine
Conservative root analysis; low-confidence unknowns remain unknown rather than fabricated.

## Evidence / Service / UI
Evidence ledger records network/engine/storage facts. Service orchestrates. UI does not directly use Engine, Storage or NetClient.

## Self-Test / Contract Test / Fault Injection / Real Network
All are hard gates and failures are explicit.

## Windows Build / Exact EXE / GUI Smoke / Same Hash
Self-contained Windows EXE; exact artifact is tested, GUI-smoked, frozen and hash-bound.

## Final Gate
Every named hard gate in release_gate.py must be exactly PASS; FAIL, NOT VERIFIED and BLOCKED never count as completion. Engineering and business completion are counted independently; combined completion is their minimum.

## Unique Product
One EXE, one SHA256, one manifest/report. Any behavior-code change invalidates prior acceptance.

## Independent Software Updater Contract
The software update button calls Service and launches a separately built updater process beside the installed main EXE. Corpus refresh remains a separate audited Service operation and cannot satisfy software update gates. The main process exits only after a verified process handoff. The updater accepts only a trusted HTTPS release config, validates the raw manifest and artifact SHA256/size, waits for the parent exit, stages bytes, preserves the previous EXE and durable transaction journal, atomically replaces the installed EXE, verifies the new EXE self-test and version, and restarts it. Failure restores the previous bytes; failed rollback retains its backup and journal for restart recovery. Missing official release config is BLOCKED. Repair preserves healthy progress and archives corrupted original bytes before recovery.

## Current Release Acceptance Evidence
A dedicated repository, current exact source/run/attempt, separately built updater EXE, raw release N and N+1 network receipts, physical update click, new installed EXE health and matching source/final hashes are mandatory. Simulation fixtures and an isolated seed do not satisfy these gates. Only a fully accepted final main EXE is the unique user product; updater and audit files are independent supporting components.
