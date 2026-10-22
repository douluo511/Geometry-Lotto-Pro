# V4.7 P0-A repair — separate verified admission from SHADOW execution

**Scope: fail-closed guard correction only.** This component does NOT authenticate official
source originals, grant formal authorization, validate external RFC 3161 tokens, certify actual
results, or prove higher D2 hit rates. A=0; decision NO_EDGE. PR #432 remains the parent
integration candidate and its original receipts are unchanged.

## Previous gap

The scheduled SHADOW runner wrote `SYNC`, `VERIFY`, `AUTHORIZE`, `PREDICT`,
`FREEZE`, `WAIT` into the `workflow_events` table with unverified caller labels.
An ordered stage name could be misinterpreted as official gate passage. The
`append_stage()` code did not require evidence of independent source/auth/TSA verification.

## New contract

- `workflow_events` is now reserved for **gate evidence**, with explicit
  `gate_status` and `evidence_class`. The only accepted current event is
  `SYNC` with a nonpassing `gate_status` (`NOT_RUN`, `BLOCKED`, `FAIL`).
- A generic caller cannot assert `PASS`; the system raises
  `INDEPENDENT_GATE_VERIFIER_REQUIRED`. A future implementation must add a
  trusted independent verifier and signed receipt contract, not a JSON flag.
- No `VERIFY`, `AUTHORIZE`, `PREDICT`, `FREEZE`, etc. *gate* record is
  written or permitted merely because an unverified prior stage was logged.
- The six research-only execution observations instead go to a distinct,
  append-only `shadow_trace_events` table, with evidence class `SHADOW`
  and status `SHADOW_UNVERIFIED`. They cannot promote any official gate.
  Its `FREEZE` trace still verifies the complete six-model batch hash.
- The scheduler may continue an **explicitly unverified research SHADOW**
  computation after logging its blocked gate, because this does not issue a
  formal or prospective-verified forecast. The runner returns
  `gate_status=BLOCKED`, `evidence_class=SHADOW` and
  `shadow_trace_status=UNVERIFIED_EXECUTION_ONLY`.
- All stage and trace entries retain idempotent hashes and immutability triggers.
  SQLite/local SHA is NOT external trusted pre-draw sealing.

This change **intentionally changes the audit schema meaning**, so the active
branch must not silently reuse previous V4.7 receipts or import previously
recorded stage names as proof of acceptance. New run identities are derived
from orchestration source hashes. Existing historical databases are not edited.

## Tests and follow-up

Run `python -m unittest discover -s research/harness_v46/tests -v` on
Windows Server 2022 and Ubuntu CI. Specific regression cases cover missing
official gate evidence, forged `PASS`, SHADOW trace ordering, wrong batch hash,
`INSERT OR REPLACE`, half-hour retries, cutoff refusal and cross-game rollback.

**Still BLOCKED:** independently parsed official raw sources, 01/04 authorization
signature verification, third-party TSA response checking, official-result
authentication, real Windows cold boot tests, the nine full P0 faults, and
DLT 69/2880 negative-control root-cause audit. The prior formal eight
identities M04, M05-1..5, M06, M07 are not touched.
