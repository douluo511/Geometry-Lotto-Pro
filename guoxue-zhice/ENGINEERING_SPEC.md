# Guoxue Zhice — Frozen Engineering Contract

Version target: 0.2.0

## Requirement / Purpose Model
Turn classical Chinese texts into source-aware, boundary-aware decision prompts for goal analysis, review and long-term learning; never present a classical analogy as automatically true.

## 5 Why
Users need more than quotations: source provenance, applicable boundary, factual questions, counterexamples and post-action review reduce slogan-like misuse.

## Risk Boundary
Classics are analytical lenses, not authoritative answers. Health content is historical thought only and does not replace modern medicine. Network/update failures must fail closed.

## Domain Model
Knowledge corpus -> scenario classification -> method candidates -> factual questions -> 5 Why -> reversal validation -> action hypothesis -> review evidence.

## Architecture
UI -> Service -> Goal/Review/Maintenance engines -> Store / NetClient -> Evidence / trusted distribution.

Software replacement is a separate release path: UI -> GuoxueService.one_click_update -> software_update handoff -> independent Guoxue_Zhice_Updater process -> trusted HTTPS release manifest/artifact -> backup -> atomic replacement -> new-EXE self-test -> commit/rollback/restart recovery. Knowledge refresh remains a separate Advanced Analysis action and must never be presented as software update.

## Function Contract / Interface Contract
UI calls only GuoxueService. The frozen top-level entries are 目标推演 | 一键更新 | 一键修复 | 高级分析. Service owns goal analysis, review, software-update handoff, knowledge refresh and repair. NetClient is the sole production network transport. Repair covers missing/corrupt knowledge and state, configuration, cache, index, network policy, version mismatch and post-repair data integrity; corrupt user/config bytes are preserved under recovery before replacement.

## Data Source
Trusted HTTPS manifest distribution paths select a hash-bound knowledge package. Raw responses, attempts, selected source, hashes and parser version are preserved.

## NetClient
Separate connect/read timeout, finite retry, exponential backoff+jitter, 408/429/5xx handling, HTTPS redirect enforcement, payload validation and attempt ledger.

## Storage
Knowledge, state and network evidence are staged before mutation and rollback together on failure.

## Engine
Outputs factual questions, multiple classical methods, 5 Why, reversal validation and explicit ACTION_HYPOTHESIS status.

## Evidence / Service / UI
Network evidence is machine-readable and hash-bound; Service is the sole UI boundary.

## Validation
Compile -> Unit -> Contract -> Fault Injection -> Integration -> Real Network -> Business/Counterexample/Reversal -> Windows Build -> Exact EXE -> Physical GUI -> Same Hash -> Final Gate.

## Final Gate
Only current-version explicit PASS counts. Missing, warning, pending, skipped, unavailable, unknown or cancelled evidence is FAIL. Independent Updater process, Updater Exact EXE, atomic rollback/restart recovery, real production Release N→N+1, Updater Same Hash and repository independence are mandatory and cannot be inferred from an in-process knowledge refresh.

## Unique Product
One exact EXE, one SHA256 and one final artifact after all hard gates pass.
