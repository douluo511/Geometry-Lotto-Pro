# Fixed D2 chronological research study

This extends draft #411, head `bee406fe44fa080b672f946c48466f9dbdace1fb`,
without changing any original producer, primary D2, model seed, application,
operational prediction database or formal eight-slot registry.

The complete archive already existed before this study. Its chronological final
slice is a **locked historical audit-test**, not genuinely unseen independent
prospective evidence. Per-row historical public availability is missing. Local
SQLite/SHA/current-clock records cannot create historical pre-draw freezing.
All outputs retain `formal_A=0`, `NO_EDGE`, `Final=FAIL` and BLOCKED next target.

## Frozen design

- Five existing producers: Hot60, EWMA, ShrinkMix, Pairwise-D2, Random NULL.
- One separate candidate: R45-PAIR-RESIDUAL, window 60; maximize
  `pair_count - count_a * count_b / 60`, ties by raw pair count, marginal sum,
  then ascending pair. The engine compares an exact integer numerator.
- One two-number forecast per model per draw, seed 20261018, no search grid.
- First 120 observed draws are warmup; remaining draws split chronologically
  60% development / 20% validation / remainder locked historical audit-test.
- Ten primary hypothesis identities: five non-NULL candidates x two games.
  Single one-sided exact paired comparison and Holm across that complete family.
- Validation nomination uses largest positive paired delta with fixed roster
  ties. It never automatically replaces the original primary Pairwise-D2.
- Main meaningful effect is an absolute 0.01 (one percentage point), 80% planned
  power, family alpha .05. Sample-size scenarios include .005/.01/.02 and
  independent-success / maximum-discordance assumptions. These are normal
  approximations, not exact-power guarantees or evidence that any edge exists.
- Wilson rate CIs, conservative paired-difference CIs from four one-sided
  Clopper-Pearson bounds and Bonferroni, and conditional paired p values assume
  IID observations. Adaptive forecast pair dependence is not established.
- A separate pre-fixed secondary fair-null e-process uses overlaps and equal
  mixing of lambdas .05/.1/.2/.4/.8. Its ten p bounds receive their own Holm
  adjustment. It cannot be used to select another winner or manufacture as-of
  integrity. It requires genuinely predictable forecasts and fair draws.
- Direct residual-versus-original rate difference is descriptive, not an extra
  confirmatory hypothesis hidden from the ten-test family.

## Run

Use a new output directory and the existing whole-file pinned history config:

```powershell
python -m research.ssq_dlt_v45.study prepare --config C:\GLP\config.json --output C:\GLP\new-study
python -m research.ssq_dlt_v45.study execute --config C:\GLP\config.json --output C:\GLP\new-study
python -m research.ssq_dlt_v45.study verify --output C:\GLP\new-study
```

Prepare computes planning scenarios, fixes every input issue/split/code SHA and
saves the design in a separate append-only study ledger. Execute claims the
analysis before scoring and refuses a repeated execution. A source/plan/input
change invalidates the registered design; do not tune after the audit-test and
reuse it as a new test. A failed claimed execution requires explicit review,
not an automatic hidden rerun. Exact-code synthetic reproducibility checks are
distinct from a fresh scientific test.

JSON/CSV/HTML and SHA show all periods, each model's fixed denominator and hits,
rate/CI, delta versus theoretical and same-period NULL, paired discordance,
global Holm and the secondary sensitivity. No losing period is removed. The
HTML report is offline and supports game/stage/model/issue filtering.

The engine uses rolling counts but retains the original EWMA addition order.
Synthetic tests compare against original `models.generate` at many prefixes,
mutate current/future outcomes, enumerate fair pair probabilities, check sparse
interval coverage and reject plan/source/artifact changes and repeat analysis.

Any research nomination must undergo new independent registered future periods.
Official issue/deadline/01--04 authority/TSA/formal definitions are still absent,
so a future trial blueprint may specify approximate fixed N and one final look,
but its actual issue list is null and enrollment is BLOCKED, not started.
