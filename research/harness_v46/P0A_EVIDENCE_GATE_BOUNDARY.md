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
issues between the two primaries, plus Gansu's recent official history with at least 10 matching
overlapping issues. Gansu is a third corroborator only; it cannot substitute for either missing
primary history. Any issue mismatch blocks cross-check admission.

Even when this history check passes, the result is `SHADOW_HISTORY_ONLY`; publication-time
authenticity, target/cutoff admission, external TSA verification and formal-A eligibility remain
blocked.

## Verification

GitHub Actions run `39757108803` passed the deterministic harness suite on both
`ubuntu-latest` and `windows-2022`: 93 tests per platform, one platform-specific PowerShell
parser test skipped on Ubuntu. The run tested commit `696feec0c9c948c0cc7a2aa6b8b599d01fdb2c92`,
including the gate/trace split and the first DLT three-source validation tests. The latest docs and
workflow-marker commits do not change the tested Python contract; still re-check CI on the latest
head before final acceptance.

Live one-shot run `39757369719` executed the current three-source contract at code commit
`1635a7ea5580fefb5d5077cd8ab6f3cf05053806`. It failed closed with DLT `SOURCE_FETCH_PARTIAL`
because the national endpoint returned HTTP 567, and SSQ `SOURCE_FETCH_PARTIAL` because its
national endpoint returned HTTP 403. The manifest reported `official_target_admission=BLOCKED`,
`formal_A=0`, `external_tsa=NOT_RUN`, `decision=NO_EDGE`. The raw evidence bundle is artifact
`12416731323` (`v47-official-intake-39757369719`). This run does not establish a three-source
DLT pass or an SSQ history cross-check; failed HTTP bodies are transport diagnostics, never draw data.

DLT 69/2880 negative-control anomaly remains unresolved. Formal A=0; NO_EDGE.
