# V4.7 independent audit round 2 — failure custody and read-only time checks

Parent round: `1d7cd7e423cbe6e92828442b836e371deb727f0e`, Draft PR #447.
This follow-up closes the two code-level gaps reproduced in round 1. The earlier round's report and evidence remain historical records.

## Scope

- Preserve received worker failure output in a separately labelled untrusted diagnostic capture before refusing schema, source-hash, JSON, worker-exit or source-conflict validation. Never treat captured failed claims as admitted HTTP sources or usable model rows.
- Write diagnostic captures once with content-derived paths and verify their byte hashes/path containment independently. Diagnostic integrity is not HTTP/source authenticity or official admission.
- Require the capture envelope for quarantined output even when an adversary deletes that field; never count its added source-like records as HTTP. Reject symlinks and Windows directory junctions at every evidence-path component.
- Normalize Windows physical evidence roots into extended-length paths, including UNC, while keeping manifest paths relative and the returned intake path ordinary. Real files beyond 260 characters exercise writer, CLI audit, write-once protection and tamper detection without changing system settings.
- Read-only batch audit checks stored frozen_at against the registered snapshot as_of and sales_cutoff, including timezone awareness and evidence class. Privileged storage can still replace locally claimed timestamps; this remains consistency checking, not a trusted predraw seal.
- No edits to core model formulas, parameter registrations, main, V4.5 formal identities, prior evidence or official source content.

Worker process termination before it delivers evidence is still an explicit limitation: no raw bytes can be fabricated from missing stdout. Incremental durable journaling would be required to recover fetches never returned by a killed process.

## Nine P0 identities

The original acceptance identities were re-read directly from [Issue #428](https://github.com/douluo511/Geometry-Lotto-Pro/issues/428), rather than inferred from the number of test methods.

| P0 | Existing synthetic evidence | Physical / qualified acceptance still required |
| --- | --- | --- |
| 1 time travel | future publication/cutoff tests; stored-freeze-time audit regressions | trusted clock skew/rollback and actual pre-cutoff authority |
| 2 holdout tamper | snapshot preimage immutability and deterministic replay | independent holdout custody against privileged replacement |
| 3 forged authorization | forged PASS/A/TSA claims rejected; gate/trace separation | role 01/controller authorization and independent verifier |
| 4 TSA / SHA failure | raw/body/source mutation, diagnostic hash tamper, local TSA-request tests | actual signed external TSA response, trusted anchors and outage test |
| 5 official conflict | source mismatch and preservation of failed worker output | authenticated official originals; Jiangsu dates remain conflicting |
| 6 duplicate/missing issues | duplicate/order checks and complete six-model batch guards | holiday/gap-aware official continuous history |
| 7 formal slot omission/substitution | model completeness and deterministic legal-ticket tamper tests | actual separate V4.5 eight-slot identity and process-isolation acceptance |
| 8 selection/metric bias | single immutable D2, fixed NULL, large-sample inference and explicit Holm family arithmetic | verified 12-hypothesis preregistration, fixed stopping rule, prospective evidence |
| 9 network/power recovery | idempotent retry, atomic rollback, child launch/timeout/encoding faults | Windows cold boot, deliberate offline window and real 30-minute recovery logs |

No row above is promoted to completed physical P0 acceptance merely because synthetic CI passes.

## Validation and outcome

Windows 10 / Python 3.11.9 full local discovery ran 188 tests, all passed. The final exact commit SHA, Ubuntu/Windows CI job logs and fresh live historical collection are recorded in the external round-2 delivery report after execution. Remote results are not claimed in advance here.

Reproduce the full contract suite:

```sh
python -m pip install requests==2.34.2
python -m unittest discover -s research/harness_v46/tests -v
```

ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NO; D2_EDGE_CONFIRMED=NO.
Formal_A=0; NO_EDGE. No retrospective prediction, fabricated predraw record or lottery purchase.
