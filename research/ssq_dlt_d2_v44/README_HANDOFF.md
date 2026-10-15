# SSQ＋DLT V4.4 — GitHub-first research scoring gate

The descriptions below record the PR #407 baseline at `c6d4de9`. The isolated
local engineering follow-up is documented in [README_LOCAL.md](README_LOCAL.md)
with current limitations and actual evidence. It does not promote any formal gate.

**Scope:** Migration and acceptance workspace only. This is not an official draw
adapter, live prediction service, qualified prospective seal, formal M04–M07
candidate producer, Windows boot service, or release candidate.

Repository governance ([PORTFOLIO_GOVERNANCE.md](../../PORTFOLIO_GOVERNANCE.md))
requires an independent final repository before a product can be called FINAL.

## What is implemented in this branch

- Deterministic SSQ (33 choose 6) and DLT (35 choose 5) front-area
  D1–D5 scored as `hits` and 0/1 `full`.
- D2 theoretical probabilities: SSQ `15/528`; DLT `10/595`.
- Complete rectangular eligibility check against an **externally registered**
  set of expected issues, model IDs and exact versions.
- Same-issue D2 outcomes and model-vs-null discordant-pair one-sided exact
  tests. Ties remain in the effect denominator, but not in the conditional
  exact test.
- Optional, pre-fixed `tau` shrinkage for **research ranking only**.
- Unconditional `RESEARCH_ONLY`, `formal_a_samples=0`, `NO_EDGE`.
- Synthetic negative tests and a Windows 2022 + Linux CI workflow.

Run locally from repository root:

```shell
python -m unittest discover -s research/ssq_dlt_d2_v44/tests -v
```

Input schema for `evaluate_registered`:

```json
{
  "game": "SSQ",
  "issue": "SYNTH-01",
  "draw_front": [1,2,3,4,5,6],
  "models": {
    "PAIRWISE-D2": {"version": "v1", "ranked_front": [1,2,7,8,9]},
    "M07-NULL-SHADOW": {"version": "seed-001", "ranked_front": [1,20,21,22,23]}
  }
}
```

`expected_issues` and `model_versions` are supplied separately and must
be fixed **before** reading results by the independent admission service.
Synthetic fixtures cannot be used as formal prospective evidence.

## Correct scientific interpretation

This scorer does **not** establish when a source became public or when a
prediction existed, cannot replace an external trusted timestamp, and does
not implement formal Holm, the preregistered 12 tests, sequential monitoring
or independent validation. Passing unit tests does not mean a model has
predictive edge. Under a fair independent draw, history-only pair estimators
have no theoretical advantage.

Do not alias the research null to the original registered M07. Do not
substitute a research ranker for the eight original identities:
`M04`, `M05-1..M05-5`, `M06`, `M07`.
M05 must designate its primary D2 in advance.

## Work engineering handoff — 9 P0 gates

| Gate | Required next implementation and fault injection | Current branch |
| --- | --- | --- |
| P0-01 | Verify data publication/as-of time; inject future record | BLOCKED |
| P0-02 | Recompute Dual holdout per issue; corrupt 10/152 to 150/152 | BLOCKED |
| P0-03 | Verify 01/04 asymmetric signatures, expiry, anti-replay | BLOCKED |
| P0-04 | RFC3161 trusted pre-sale deadline timestamp; tamper, expiry | BLOCKED |
| P0-05 | Fetch two whitelisted official source originals; conflicting result | BLOCKED |
| P0-06 | SQLite append-only ledger/unique keys/restart lock/retry | BLOCKED |
| P0-07 | Original 8 formal slots and M05 preselected primary | BLOCKED |
| P0-08 | Preregistered formal 12-family, sequential plan, new challenger trials | BLOCKED |
| P0-09 | Windows boot trigger and 30-minute retry; network outage, restart | NOT_RUN |

Partial **research-scoring** tests are not a substitute for P0-01 through
P0-09 acceptance. No P0 gate is marked PASS by this module.

## Ordered execution for Work, after review

1. Confirm the current source tree. Original SSQ and DLT products under
   `SSQ/` and `DLT/` are different from conversation V4.0 ZIP; reconcile
   hashes and interfaces before integration; never rewrite historic R1.
2. Run CI for this branch. Review and strengthen this scorer using negative
   tests and independent reimplementation, without promoting to formal A.
3. Integrate official source adapters, G00 target handoff and 01 as-of proof.
4. Implement persistent SQLite ledger with expected-issue registration,
   Windows Task Scheduler at startup and every 30 minutes, fail-closed retries,
   Docker Compose **optional**, and official evidence provenance.
5. Implement independent 04 signing authority, external TSA, full eight
   slots and immutable JSON fingerprints.
6. Implement draw fetch, read-only replay, independent 03 calculation,
   D2 paired evaluation, and versioned research challengers.
7. Only after local Windows fault injection and complete endpoint checks,
   propose cloud migration. Never deploy paid cloud resources without approval.

Deliver complete code diffs, actual commands and exit codes, SHA manifest,
Windows Task Scheduler XML/PowerShell/BAT, SQLite, HTML, JSON/CSV, failure
logs, and an exact fresh-extracted acceptance run. Each gate must show
PASS / FAIL / BLOCKED / NOT_RUN with evidence.

**Current admission:** `R2=BLOCKED`, `formal_A=0`, `NO_EDGE`.
Do not call this branch `FINAL`, `AUTOMATION_READY` or `MODEL_EDGE_CONFIRMED`.

## Coordination

One control chat provides the management interface; GitHub PR/commits,
immutable evidence and the runtime database are authoritative. GLP 01 data,
02 prediction, 03 independent audit and 04 scheduler may be separate
responsibilities, but independent chat sessions cannot automatically
share submissions or substitute for audited service boundaries.
