# V4.7 P0-A — verified gate boundary vs SHADOW execution trace

**Scope:** isolated fail-closed contract correction. This is not proof of official-source
authenticity, signed 01/04 authorization, an external RFC 3161 timestamp, authenticated outcomes,
a production Windows scheduler, or improved D2 hit rate.

## Finding

The previous scheduler wrote unverified labels for SYNC/VERIFY/AUTHORIZE/PREDICT/FREEZE/WAIT
into one workflow table. Ordered stage names and local hashes could be mistaken for verified
gate passage.

## Corrected contract

- `workflow_events` is a gate journal. The scheduler writes only a nonpassing SYNC event marked
  `gate_status=BLOCKED`, `evidence_class=SHADOW`, `formal_A=0`.
- Caller-supplied `PASS` is refused with `INDEPENDENT_GATE_VERIFIER_REQUIRED`. No later gate
  event can be appended after blocked SYNC. Future PASS requires an independent verifier and
  auditable receipt contract, not a boolean or free-text claim.
- Research execution steps are stored separately in `shadow_trace_events` as
  `SHADOW_UNVERIFIED`. They cannot promote official gate state. FREEZE trace still checks the
  complete six-model batch digest.
- Both journals are append-only with update/delete guards and recursive triggers.
- Scheduler output explicitly reports `gate_status=BLOCKED`,
  `shadow_trace_status=UNVERIFIED_EXECUTION_ONLY`, `formal_A=0`, and `NO_EDGE`.
- The official intake orchestrator is included in the before/after SHA256 lock so the worker
  cannot silently change its own validation logic during collection.

Historical databases and the V4.5 eight formal-slot identities are not modified. Older workflow
rows must not be reinterpreted as verified gate receipts.

## DLT source contract

DLT history admission requires all three source identities to be present in the intake record:
national and Jiangsu primary histories, each with at least 120 valid draws and at least 120 matching
issues between the two primaries, plus Gansu's recent official history with at least 10 matching overlapping issue IDs against
EACH primary source. Gansu is a third corroborator only; it cannot substitute for either missing
primary history. Latest issue, date, and balls must agree; any issue mismatch blocks cross-check admission.

Even when this history check passes, the result is `SHADOW_HISTORY_ONLY`; publication-time
authenticity, target/cutoff admission, external TSA verification and formal-A eligibility remain
blocked.

## Verification

GitHub Actions run `39759416096` passed the deterministic harness suite on both
`ubuntu-latest` and `windows-2022`: 100 tests per platform, one platform-specific PowerShell
parser test skipped on Ubuntu. The run tested code commit `4aaadfdc81f86e90a63c1d57f72b8406f69eb02c`,
including the gate/trace split, source self-hash lock, primary DLT 120+ overlap, and Gansu 10+ exact
corroboration against BOTH primary histories.

Live one-shot run `39757369719` on the earlier branch recorded DLT national HTTP 567 and SSQ national
HTTP 403, both blocked. A second live intake run `39758924010` was started on code commit
`c6500dcfb3213c4a9e84947f092a576f2f22a698`; it uses the latest upstream SSQ Hebei route and the
mandatory DLT three-source collection, but predates the final explicit check that Gansu overlap each
primary. Its result is still pending at the time of this edit. Any live result is source-access
and historical-only evidence, not target/cutoff admission; raw HTTP failures are never draw data.

DLT 69/2880 negative-control anomaly remains unresolved. Formal A=0; NO_EDGE.
