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

Historical databases and the V4.5 eight formal-slot identities are not modified. Older workflow
rows must not be reinterpreted as verified gate receipts.

## Verification

Run `python -m unittest discover -s research/harness_v46/tests -v` in Ubuntu and Windows CI.
Regression coverage includes forged PASS, blocked upstream stage, trace ordering, tampered batch
digest, SQLite INSERT OR REPLACE protection, retry, cutoff refusal, and cross-game rollback.

## Still blocked

- P0-B source-origin/publication-time authenticity: the current intake replays preserved raw
  response bodies and cross-checks two source histories, but correctly stays SHADOW_HISTORY_ONLY.
- P0-C external TSA request/response and cryptographic token verification.
- P0-D authenticated official outcomes and immutable read-only scoring receipt.
- P0-E/F remaining fault injection and real Windows cold-boot/scheduler logs.
- P0-G preregistered D2 statistics over independently authenticated prospective observations.

The live official-source attempt returned HTTP 567 for DLT and a non-200 failure for SSQ in the
GitHub runner. That is a network/source-access block, not an accepted data result. The intake
workflow is being corrected to preserve these transport failures without treating them as draws.
DLT 69/2880 negative-control anomaly remains unresolved. Formal A=0; NO_EDGE.
