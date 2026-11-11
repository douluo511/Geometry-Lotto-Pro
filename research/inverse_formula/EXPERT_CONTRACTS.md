# Independent research experts V1 — PR #470 only

This module is a **zero-network, zero-payment, deterministic** research
simulation, not six separate foundation models, six paid requests or
prospective lottery validation. It MUST NOT be merged or promoted without
separate review. Status: **NO_EDGE**.

## Pure service contracts

`research/inverse_formula/independent_experts.py` exports six independently
invokable functions, with explicit input/output dictionaries:

1. `mathematician(prefix, game)` — legal draw spaces, theoretical ticket and
   D2 probabilities, and uniform-null assumptions.
2. `formula_discovery(prefix, game, lookback=24)` — bounded six-family formula
   candidate catalogue, fitted parameters, anchor/validation issue cutoffs,
   vote weights, candidate IDs and content digest. **Retrospective identities
   are not discovered physical laws.**
3. `combination_research(prefix, game, formula_report)` — auditable weighted
   complete ticket, two front D2 numbers, and complementary unselected
   front/back balls. The latter are **not experimentally validated 杀码**.
4. `statistician(prefix, game, math_report, window=5)` — past-only rolling
   internal replay, paired research-only seeded NULL, D2 theoretical baseline,
   descriptive Wilson intervals and per-target decision cutoffs.
5. `skeptical_reviewer(math_report, formula_report, combo_report,
   stats_report)` — cross-expert source/cutoff/anchor checks, explicit
   future-leakage violations and a **binding promotion veto**.
6. `engineer(prefix, game, combo_report, reviewer_report)` — stable simulated
   idempotency key and local SHA256 content seal, recorded non-execution flags
   for scheduling, external predraw freeze, results sync, scoring and restart.
   This contract **does not run or verify those real-world operations**.

`guarded_prefix(history, game, cutoff_issue=...)` rejects any passed-in
future suffix, missing/gapped issues, duplicates or invalid balls. A
caller must pass an explicit cutoff; every expert receives the cutoff-limited
prefix only. The experimental backtest reads a target's actual draw **after**
the candidate has been computed from an earlier slice. This code cannot
independently prove that an upstream historical data source is authentic.

`simulate_experts(history, game, cutoff_issue=...)` invokes each function
separately, preserves all six complete payloads in order, and links the
records by SHA256 of prior record, shared normalized history prefix, payload,
and full record. `verify_evidence(records)` independently checks link order,
payload tampering, targets and hashes. Hashes are **not digital signatures,
trusted timestamps, independent agent attestations or commit evidence**.

## Reproduce locally (no network access needed once repository is checked out)

```powershell
python -m pip install pytest
$env:PYTHONPATH = "."
python -m pytest -q tests/test_inverse_experts.py
python -m research.inverse_formula.independent_experts --limit 34 --out independent-experts-receipt.json
```

The CLI deliberately processes a **historical prefix**, not the latest draw.
It produces full local evidence receipts and prints each game's receipt hash,
the six role names, NO_EDGE and paid model calls = 0. Ubuntu and Windows CI
run the tests and upload receipts; CI evidence must be inspected rather than
assumed. Unit and workflow simulations cannot qualify as a real-world
scheduled run, durable restart recovery, authentic pre-draw sealing or
cross-issue prospective scoring.

## Isolation and future acceptance gates

- Existing V4.7, frozen ledger and **fixed Random NULL** are untouched;
  the research-only random control is a separate identity.
- Existing committee V1 and optional live-model integrations remain separate;
  this module contains **no HTTP client, API key handling or paid model calls**.
- A formula catalog, replay and confidence interval cannot establish a
  statistically significant edge without independently pre-registered future
  tests, clean sources, a valid multiple-comparisons plan and external audit.
- No PR merge, model promotion, official ticket issue or trusted timestamp is
  authorized by this simulation.
- Main-branch P0 remains a separate delivery: only remote schedules plus
  remotely persisted receipts and forced restart tests can advance its
  UNVERIFIED operational gates.
