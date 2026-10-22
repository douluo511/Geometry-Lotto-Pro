# Issue #428 — test10 convergence contract and failure matrix (2026-10-22)

**Scope: synthetic SHADOW engineering only. Formal A=0; scientific decision NO_EDGE.**
No PR merged; main, older V4.5 evidence, and DLT 69/2880 negative-control evidence are untouched. This proposal is NOT an independent release repository.

## Inspected heads and base graphs

| Source | HEAD inspected | Base | Strength | Critical gap |
|---|---|---|---|---|
| #425 | `1cd80efdcf3ad9b33577c9cac5736fdad85a29f9` | main | standalone six-stream, per-game transaction, format + deterministic replay from 2 subsequent commits | no run_context in its HEAD, no official proof |
| #426 | `a258b84a4bc1fa96b964126aa683fc7b10ba9a48` | earlier #425 `86bd2833...` | immutable (run_id, lottery, issue, snapshot hash, as-of, cutoff); rejects legacy row adoption | lacks #425's latest two deterministic-replay hardening commits |
| #427 | `fd11edb01e74515aa1195ff59f0b5ad2f3a660f2` | V4.5 Agent Graph branch | explicit ten-role mapping, V4.5 reuse, six research streams | different JSON snapshot and model APIs; no run_context, no cutoff, no external seal; two-game file written before separate ledger appends |

All three returned successful **synthetic** Ubuntu and Windows GitHub Actions job conclusions at their inspected commits. Neither boot recovery nor external timestamp or official independent source validation was demonstrated.

**Canonical for new V4.6 test10 work:** carry forward #426's `research/harness_v46` API, manually port #425 HEAD deterministic replay hardening, add a single versioned translation contract. Do not import #427 predictions or ledger rows as if they shared the same algorithm/version or release provenance. Preserve #427 as an independent historical SHADOW branch. Reusing its V4.5 model algorithms later requires explicit algorithm equivalence testing, parameter equivalence and new model version registrations.

## Machine contract in this branch

- `core.validate_snapshot(snapshot)`: structural as-of input only, **not official admission**. Current snapshot keys: `lottery, as_of, sales_cutoff, target_draw_at, target_issue, draws, provenance`; a draw has `issue, front, back, drawn_at, published_at`. Issue strictly future and all history published <= as-of.
- `convergence.manifest({"SSQ": snapshot, "DLT": snapshot})`: stable cross-lottery `V46-<32 hex>` RUN_ID from both independently pinned game contexts. A model registry records six immutable parameter digests and ten static role IDs.
- `core.forecast(snapshot, model)`: six SHADOW choices. `primary_d2` is the ordered first two of exactly five. `validate_forecast` deterministically replays ranking and both ticket zones; a valid-looking changed ticket is rejected.
- `core.freeze_shadow(conn, run_id, snapshot, prediction, frozen_at)`: single per-lottery immutable context (from #426), exact retry idempotent, changed input fail-closed. A caller may wrap two games in a single transaction; no automatic trusted timestamp.
- `convergence.handoff(...)`: serializable bytes/identity and restricted producer routes. It **does not transmit to another ChatGPT conversation**, authorize tools, or provide sandbox isolation. The host must enforce tools and process access.
- `convergence.verify_local_source_bytes(...)`: check two actual local byte-file SHA256 values, distinct HTTPS source URL declarations, and publication/fetch time bounds. Does **not** prove either source is genuinely official or that their parsed draws agree. Result is `source_authenticity: NOT_VERIFIED` and admission BLOCKED.
- `convergence.append_stage(...)`: strict monotone ordered append-only checkpoints through all eleven stage names. The FREEZE stage requires six immutable producer records for its game and matching frozen batch SHA. Status never upgrades to formal.
- `convergence.tsa_request(...)`: create append-only outgoing request identity with `NOT_VERIFIED`. There is no RFC3161 TSA client, response cryptographic validation or third-party time proof.
- `convergence.score_readonly(...)`: DB mode=ro, six frozen producers, SHA checks, caller-supplied outcome diagnostics and same-period D2 difference vs NULL. Outcome labelled `CALLER_UNVERIFIED`; no independent official validation or statistical-significance result.

### Contract mismatches vs #427 (migration MUST be explicit)

| Field / interface | #426 canonical | #427 independent research | Decision |
|---|---|---|---|
| lottery identification | `lottery` per-game snapshot | `targets[game]` and `history[game]` | Translate into two validated single-game snapshots; never silently infer cutoff |
| temporal guard | `as_of`, `published_at`, `sales_cutoff`, `target_draw_at` | `asof`, history `draw_at`, target `draw_at` | Missing publication/cutoff is BLOCKED; no fake default |
| predictions | `candidates_1_to_5`, `primary_d2`, `ticket` | `ordered_dan`, `primary_d2`, `d1_d5` | Map only after re-running canonical model; do not transfer original predictions |
| model registry | names `hot60` etc and VERSION + parameter SHA | names prefixed by role; V4.5 algorithms | Do not assume scientific equivalence |
| ledger | `run_context` + `predictions` + `audit_events` | generic `events` | Never migrate history in place; export immutable original evidence |
| scoring | `score` for stored single-model ticket | `score_research` for six-stream bundle | Read-only six-arm aggregation required; outcome still not official |

## P0 failure and execution-evidence matrix

Legend: TESTED = specific synthetic automated assertion committed here (subject to actual test results); NOT_RUN = no real evidence.

| P0 | Synthetic negative test | Real-world acceptance outstanding |
|---|---|---|
| 1 time travel | source published > as-of; history after as-of; prediction after cutoff | external time synchronization and authority, actual clock skew and rollback |
| 2 holdout mutation | prior frozen run_id snapshot switch and deterministic model replay | independent holdout immutability against privileged storage |
| 3 forged authorization | formal_A and `TSA_VERIFIED` claims rejected by workflow | role 01 + controller authorization signatures and independent verifier |
| 4 TSA / SHA | source-file SHA mutation and immutable local TSA-request state | actual external TSA request, response proof validation, outage |
| 5 official source conflict | duplicate source URLs and local source-byte checks | two genuine official full originals with semantic field-level cross-compare |
| 6 missing / duplicate issues | #425/#426 previous duplicate-issue tests, new model batch completeness test | gap/holiday-aware official continuous history |
| 7 slot omission / substitution | six-model batch check, immutable replay, legal-but-changed ticket | independent process boundaries and legacy eight formal slot identities |
| 8 metric bias | only frozen unique prefix D2 scored vs same-period NULL | preregistered family, Holm and stop rule with real prospective data |
| 9 network/power restore | deterministic identical retry / stage monotonicity tests | REAL network failure injection, Windows cold boot log, Task Scheduler 30m retry |

Synthetic unit tests do **not** certify all nine P0 end-to-end. Windows start/30-minute compensation/Mon-Wed-Sat 16:00 JST and external TSA remain **NOT_RUN** until raw host evidence exists.

## Local repro / workflow

```sh
python -m unittest discover -s research/harness_v46/tests -v
```

The workflow must be read with its exact branch commit and raw job logs. `PASS` should refer only to actually observed tests. Existing all-other-products CI, release independence, DLT-negative-control cause, independent 08/01 verification, full statistical preregistration, and trusted-source ingestion remain **BLOCKED/NOT_RUN**.

### Scientific unchanged contract

SSQ D2: 15/528 = 2.8409%; DLT D2: 10/595 = 1.6807%. Target +1 percentage point in each game is a challenge hypothesis only. The new challenger remains EXPLORATORY_UNREGISTERED, not a preregistered competitor. V4.5 M04, M05-1..5, M06, M07 retain their separate formal slot identities. Historical formal A=0, NO_EDGE, no automatic ticket purchase.
