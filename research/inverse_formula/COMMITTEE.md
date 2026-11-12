# Multi-role research committee (research-only V1)

This module **does not invoke six independent AI models**. It implements six
deterministic, auditable role stages, suitable as a future orchestration
interface. The roles are mathematician, formula discovery, ensemble researcher,
statistician, skeptical reviewer, and engineer.

## Run

From the repository root, with Python 3.11:

```powershell
python -m research.inverse_formula.committee --out inverse-committee-receipt.json
python -m pytest -q tests/test_inverse_probe.py tests/test_inverse_committee.py
```

The command loads the existing SSQ and DLT fixture files. All results are
**historical research**. Refreshing fixtures requires separate provenance
checks; do not silently treat a past fixture as a fresh live draw.

## Executed protocol

1. Mathematician: names six algebraic candidate families and identifies their
   post-outcome offset fitting as an oracle, not a forecast.
2. Formula discovery: enumerates candidates fit exclusively from already-known
   anchor issues.
3. Ensemble researcher: generates a pre-outcome ticket using the unchanged
   `predict_with_bank` prototype and cites the picked formulas.
4. Statistician: replays both ensemble and single-formula alternatives one
   past period at a time; compares a separately seeded issue-only random NULL
   on the **same** periods.
5. Skeptical reviewer: explicitly vetoes an edge/promotion claim because the
   existing sample has been explored and is not a prospective validation set.
6. Engineer: serializes the meeting record, chosen D2 pair, objection trail,
   candidate SHA256 and final receipt SHA256.

## Safety and interpretation

- Caller passes a prefix ending **before** the unknown target issue. Predictions
  never access target outcomes. Internal replay scores its target only after
  constructing predictions from the strictly earlier prefix.
- Replay statistics are exploratory, not a new untouched holdout. Ranking a
  new strategy based on this history would invalidate its claim to independent
  verification. The committee uses the pre-existing formula-bank ensemble as
  its fixed research candidate; it does **not** select a retrospective winner.
- The research-only control is **not** the official V4.7 fixed Random NULL.
- A SHA256 receipt detects subsequent changes but **does not** prove pre-draw
  timestamping or guarantee that predictions were filed before the draw.
- No formal V4.7 code, weights, seed, forecast producer, or frozen ledger is
  modified. This branch / Draft PR must not be merged solely because tests
  pass. Future deployment requires formal independent review, verified official
  draw data and preregistered prospective tests.
- Mathematical oracle fits and this deterministic simulation do not imply that
  lottery draws are predictable or that there is a positive expected return.
