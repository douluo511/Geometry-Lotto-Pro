# V4.7 P0-A — verified gate boundary vs SHADOW execution trace

**Scope:** isolated, fail-closed synthetic contract repair only. This is not proof of
official-source authenticity, signed 01/04 authorization, an external RFC 3161 timestamp,
authenticated outcomes, a production Windows scheduler, or improved D2 hit rate.

## Finding

The previous scheduler wrote unverified labels for SYNC/VERIFY/AUTHORIZE/PREDICT/FREEZE/WAIT
into a single workflow table. Ordered stage names and local hashes could be mistaken for
verified gate passage.

## Corrected contract

- `workflow_events` is a gate journal. The current runner can write only a nonpassing SYNC
  event explicitly marked `gate_status=BLOCKED`, `evidence_class=SHADOW`, `formal_A=0`.
- Caller-supplied `PASS` is refused with `INDEPENDENT_GATE_VERIFIER_REQUIRED`. No later gate
  event can be appended after blocked SYNC. Future PASS requires an independent verifier with
  an auditable receipt contract, not a boolean or free-text claim.
- Research execution traces are stored separately in `shadow_trace_events` as
  `SHADOW_UNVERIFIED`. Their schema does not permit official authority fields; they cannot
  promote the gate state. FREEZE trace still checks the complete six-model batch digest.
- Both journals are append-only with update/delete guards and recursive triggers on the writer.
- Scheduler output explicitly reports `gate_status=BLOCKED`,
  `shadow_trace_status=UNVERIFIED_EXECUTION_ONLY`, `formal_A=0`, and `NO_EDGE`.

The change alters the meaning of workflow evidence. Do not interpret older workflow rows as
proof of verified gates. Historical databases and the V4.5 eight formal-slot identities were
not modified.

## Verification

Run `python -m unittest discover -s research/harness_v46/tests -v` in Ubuntu and Windows CI.
Expected tests include forged PASS rejection, blocked upstream stage, SHADOW trace ordering,
tampered batch digest, INSERT OR REPLACE protection, half-hour idempotent retry, cutoff refusal
and atomic rollback.

## Still blocked

P0-B: source-origin and parser provenance; the fetcher preserves raw bytes but does not parse.
P0-C: actual external TSA request/response and cryptographic token verification.
P0-D: authenticated official outcomes and immutable read-only scoring receipt.
P0-E/F: remaining fault injection and real Windows cold boot/scheduler logs.
P0-G: preregistered D2 statistics over independently authenticated prospective observations.
The DLT 69/2880 negative-control anomaly remains unresolved. Formal A=0; NO_EDGE.
