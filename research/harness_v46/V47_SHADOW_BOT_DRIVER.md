# V4.7 SHADOW Bot local driver — NOT an activated unattended deployment

Base PR #450 last checked SHA `664f8b6dc2adf41b47063bb58cd6dd1747c7df6c`. This is an additive, research-only scheduler-compatible CLI that composes #449 forecast and #450 cumulative read-only replay. No `main`, formal V4.5 eight-slot, trained model parameter, prior freeze or NULL seed modified.

## Honest deployment status

**This PR does not turn on a background bot.** GitHub Actions `schedule` is triggered from the repository default branch only; a scheduled workflow in this research branch would not run, and changing `main` is prohibited. Even if scheduled, ephemeral GitHub runners do not supply a durable trusted ledger or independent TSA. The external operator must provision a persistent locked-down host, authenticated dual official-source history + target/cutoff + result inputs, independent external predraw timestamp witness, a durable off-host audit store, and an actual OS scheduler before claiming unattended operation. None is claimed here.

## Invocation on a persistent research host

```sh
# Precreate evidence/ and database parent on the same persistent host.
python -m research.harness_v46.bot_runner forecast --snapshot-bundle vetted-dual-snapshot.json --database /persistent/state/v47.sqlite --evidence-dir /persistent/state/evidence
# When actual target draw has passed; outcome remains CALLER_UNVERIFIED:
python -m research.harness_v46.bot_runner score --run-id V47-<EXACT_RUN_ID_FROM_FORECAST> --result-bundle dual-results.json --evidence-dir /persistent/state/evidence
python -m research.harness_v46.bot_runner cumulative --evidence-dir /persistent/state/evidence
```

`forecast` invokes existing pre-cutoff atomic dual-game 12-row SHADOW freeze, stores output in one local exclusive-create JSON receipt and refuses changes for an old target.
`score` first verifies a saved forecast and read-only original ledger, refuses a phase before the target draw, refuses a claimed draw in the future and uses exactly two supplied game results; no posthoc D2 replacement.
`cumulative` scans all local score receipts, reopens each frozen ledger, refuses duplicate targets / mixed model identities / tampered local receipt, and recomputes all model D2 hit rates against fixed Random NULL. It never trusts the stored totals.
Each JSON receipt bears a checksum but the local filesystem is **not** an external immutable proof and its local clock is **not** a TSA. Host compromise, source forgery and fully recomputed local evidence remain in scope of BLOCKED formal gates.

## Tests and blockers

Nine synthetic tests: idempotent forecast/score and read-only cumulative, early or impossible future draw, conflicting outcome rewrite, forged formal A, locally modified checksum, symlink guard, late forecast, missing/forged run id, and corrupted persisted score record.
Run: `python -m unittest discover -s research/harness_v46/tests -v` against the exact PR commit.

BLOCKED: true official source/history admission and actual next-target calendar; independent cross-source official postdraw origin/time; externally witnessed cutoff-before-draw timestamp; durable off-host WORM; functioning installed unattended timer/Windows P0; DLT negative-control 69/2880; preregistered future trial. These are distinct from synthetic software contract tests.

`ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NO`, `D2_EDGE_CONFIRMED=NO`, `formal_A=0`, `NO_EDGE`.
