# TalkCraft Pro v1.1 Engineering Freeze

Frozen sequence:

Requirement recovery / provenance → Business Purpose → 5 Why → Risk Boundary → Domain → Architecture → Function Contracts → Data Sources → NetClient → Storage → Engine → Evidence → Service → UI → Self/Unit/Contract/Integration → Fault Injection → Real Network → Business/Counterexample/Reversal → Windows Build → Exact EXE → GUI Smoke → Physical GUI → Same Hash → Evidence-derived Final Gate → unique artifact.

## Data lineage
Recovered prototype and prior user-owned training documents → REAUTHORED_CONTENT v1.1 → runtime training data → user Evidence → acceptance Evidence.

The v1.1 JSON content pack is explicitly re-authored from recovered source material. It is not represented as byte-identical recovery of missing legacy JSON.

## Network
HTTPS only. Separate connect/read timeout. Finite attempts. Retry only transport failures and 408/429/5xx. Exponential backoff+jitter. Final HTTPS URL required. HTML content type required. Payload size bounded. Raw body hash/body_b64 and attempt ledger persisted.

## Release
Only current-run evidence may set a gate PASS. Missing/UNKNOWN/SKIPPED/PENDING/FAIL are hard fail. Monorepo staging must keep repository_independence=FAIL; portfolio Final requires rerun in an independent repository.
