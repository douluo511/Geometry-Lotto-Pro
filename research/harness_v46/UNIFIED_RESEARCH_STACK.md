# SSQ + DLT V4.7 unified research stack (SHADOW only)

This command runs the **existing** registered six V4.7 research arms (five selectors plus the immutable SHA256-sort Random NULL) through M1/M2 checks, invokes the **actual existing** SSQ and DLT `glp.engine` geometry features in **two isolated subprocesses**, samples a fair without-replacement Monte Carlo baseline (M3), and tests a bounded **two-ball uncalibrated** mechanical box with gravity, linear drag, imposed air velocity, sinusoidal forcing, wall reflection and frictionless contact.

This code does **not** integrate a calibrated real lottery machine. It cannot reconstruct the next draw from numbers alone. It deliberately does not output lottery tickets or use model outputs for betting. No real official past/future data is admitted, no trusted timestamp is created, and no model is promoted.

## Run in a clean checkout

Windows PowerShell (from repository root; Python 3.11+):

```powershell
py -3 -m research.harness_v46.research_stack --synthetic --seed 2026 --trials 3000 --steps 12 --full-combinations --report-file out/research/latest-synthetic.json
py -3 -m unittest research.harness_v46.tests.test_unified_stack -v
```

Linux/macOS Python from repository root:

```bash
python -m research.harness_v46.research_stack --synthetic --seed 2026 --trials 3000 --steps 12 --full-combinations --report-file out/research/latest-synthetic.json
python -m unittest research.harness_v46.tests.test_unified_stack -v
```

Run the existing full V4.7 suite and both game suites through GitHub Actions workflow `v46-harness-fixtures.yml`. The integration command is also invoked in that workflow. GitHub CI is **not** an installation on the owner's Windows computer; real host scheduling, reboot recovery, official-source quorum, predraw TSA seal and prospective score verification are outside this isolated stack and still require separate admission.

## Component provenance

| Check | Implementation | Output scope |
| --- | --- | --- |
| M1: formulas and original six models | `physics_audit.audit_model_contracts`, `core.forecast` | synthetic invariant checks, exact D2 math |
| M2: falsification and independent oracle | `physics_audit._independent_pairwise_d2`, SHA256 NULL history-invariance test | adversarial checks, cannot claim predictive advantage |
| M3: baseline Monte Carlo | `research_stack.simulate_fair_d2` | fair fixed-pair null only; Brier score and standard error, not calibration of forecast probabilities |
| Historical selector formulas | `core._model_ranking` | reused, unchanged and not promoted |
| Six-arm synthetic forecast, local freeze, two-step replay and score | `synthetic_pipeline.py` with `core.forecast`, `core.freeze_shadow`, `core.score` | 12 synthetic forecasts per game frozen and scored in MEMORY ONLY; not authenticated future draws |
| Full legal-combination scoring | original `SSQ/SSQ/glp/engine.py` and `DLT/src/glp/engine.py` via `geometry_adapter --complete-space` | opt-in enumeration of legal combinations, expensive, not a predictive edge |
| Geometry: SSQ | `SSQ/SSQ/glp/engine.py` via `geometry_adapter.py` | game-specific geometry features; no physical lottery ball locations |
| Geometry: DLT | `DLT/src/glp/engine.py` via `geometry_adapter.py` | same separate process, avoids shared `glp` module collision |
| Physical toy | `physics_sim.py` and `physics_audit.collide` | two labeled **generic** spheres only, no drawing outlet or true equipment calibration |

## Non-negotiable gates

- Do not run this module with official lottery source data; it only accepts `--synthetic` to prevent accidental evidence promotion.
- Preserve five existing selectors, fixed Random NULL seed, the freeze ledger and all other model source files.
- All Monte Carlo predictions are **fair lottery null samples**, not model performance. There is no authenticated future outcome; reported Brier scores are only for the null simulation.
- The mechanical toy's units are m, kg and seconds, but its coefficients and chamber shape are **illustrative**, not measurements. It omits air turbulence, true device geometry, angular rotation, ball spin, capture gate and sensor uncertainty.
- CI checks for every native Windows-only test on Windows, allowing no unexecuted test across the Ubuntu/Windows matrix. Passing CI certifies test suite execution, **not** machine deployment or physical prediction.
- Always `formal_A=0`, `NO_EDGE`, `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`.

## Verified integration boundaries

The unified command now executes a **two-period synthetic** walk-forward for both games using the original V4.7 six selectors, local immutable prediction freeze in in-memory SQLite, read-back with SHA256 verification, then scoring on *invented* future outcomes generated after freezing. It reports each model and the unchanged SHA256-sort Random NULL. This is not an external predraw TSA timestamp, an official-source ingest, or statistically qualified future sample.

The `--full-combinations` option calls the original full-space search on SSQ front/back (SSQ code exposes actual enumeration count) and DLT front/back (DLT code exposes only selected best combo; displayed total is a theoretical combinatorial count, NOT independently instrumented iterator count). The research CLI runs on synthetic fixtures and never promotes output to a betting recommendation.

## Experimental model integration (separate from registered six-arm baseline)

The `experimental_fusion.py` research adapter is now wired into the **same**
`research_stack.py` CLI. It builds `research_fusion` for both games from the
**existing** V4.7 statistical selectors and **actual original** game-engine
geometry rankings, without mutating `core.MODELS` or the fixed Random NULL.

The fixed, untrained heuristic for **front** positions is:
- 70% equal-weight Borda rank score from the five registered statistical
  arms: HOT60, EWMA, ShrinkMix (Bayesian-style shrinkage *heuristic*, not an
  estimated Bayesian posterior), Pairwise-D2 and Challenger.
- 30% equal-weight Borda rank score from the original engine's
  `geometry_state` and `geometry_transition`.
- When `--full-combinations` is specified, an additional fixed 0.05 rank-score
  bonus for numbers selected by the **original** complete-space search.
  No probability interpretation is attached to the score.

The **back** positions use the two geometry Borda ranks (and optional
full-space membership bonus). No back-ball model advantage is claimed.

**Physical machine contribution = 0.0.** The existing uncalibrated two-ball
experiment runs in the same report only as a mechanical self-test. Its
motion has no measured relationship to the next SSQ or DLT draw, and feeding
it into number ranking would be unjustified.

At each of two **synthetic** future dates, the experimental output is frozen
in a **separate, immutable in-memory SQLite table**, SHA-256 checked and
scored after the independent invented outcome is generated; the original
six V4.7 models and Random NULL remain distinct and unchanged. The
head-to-head comparison explicitly returns
`TOO_FEW_SYNTHETIC_ISSUES_NO_EDGE_CLAIM`; there is **no real prospective
calibration**.

Inspect the `games.SSQ.research_fusion`,
`games.DLT.research_fusion` and
`games.*.walk_forward.experimental_against_random_null` fields of
the printed JSON report. This is **experimental research integration**, not
a new official lottery model slot, certified operational deployment, or
a validated enhanced chance of winning.

### Reviewable CI report artifacts

GitHub Actions now runs the unified experimental model under both
Ubuntu and Windows and publishes a separate
`v47-research-ubuntu-latest` / `v47-research-windows-2022`
create-only JSON report. The `--report-file` option writes and fsyncs
a JSON receipt once; it refuses overwrites. This is reproducible
**synthetic** evidence, not a trusted predraw time seal or authenticated
official source. The workflow verifies exact commit identity before
execution and separately enforces zero unexecuted tests across both OSes.

All synthetic model scores remain `NO_EDGE`; real-world calibration and
Windows owner-machine unattended deployment are still **NOT_VERIFIED**.

### Mandatory independent M1/M2/M3 admission review

Every unified research invocation now invokes
`research_review.review_synthetic_stack` **before** the CLI can return
success or write its create-only JSON artifact. The reviewer separately
recomputes the theoretical D2 rates, verifies the six registered model IDs
and immutable Random NULL inclusion, checks the independent pairwise
oracle/NULL invariance receipts, recalculates the Monte Carlo fair-null
rate and Brier score, verifies each frozen six-model and experimental D2
score against the *same invented* future outcome, and computes exact
Clopper–Pearson synthetic-rate intervals plus paired synthetic NULL
comparison arithmetic.

**Scope:** `review.status=SYNTHETIC_CONTRACT_PASS_NOT_REAL_CALIBRATION`.
The `review.official_prospective_calibration` field must remain
`BLOCKED_NO_AUTHENTICATED_FUTURE`. These intervals and p-values are
unusable as significance or probability calibration evidence for genuine
future lottery outcomes. The reviewer immediately blocks a forged
official-status claim, uncalibrated physical signal, six-model roster
change, null-score manipulation, or incomplete synthetic freeze. Both
`formal_A=0` and `edge=NO_EDGE` remain mandatory.

A real forward calibration layer requires an **independently sealed
pre-sales forecast**, verified original official draw and immutable
hypothesis family; not one of those can be substituted by this synthetic
research command.
