# Eleven model audit implementation plan

> **For agentic workers:** use superpowers:executing-plans. The user explicitly requested immediate implementation of the attached specification.

**Goal:** repair and execute eleven real models for each game and deliver 22 attributed, frozen records and reproducible evidence.
**Architecture:** retain the existing V47 registry and live ledger. Extend numerical mechanics, model state, evolution genealogy, chronological evaluation, provenance and export boundaries without changing historical freezes.
**Tech stack:** Python 3.11 standard library, pytest/unittest, GitHub Actions.
**Spec:** user attachment pasted-text-1.txt, sections 1–8; acceptance A–V.

## Global constraints
- Exactly 11 models / 22 records. Equal computed numbers are allowed.
- Physics is UNCALIBRATED_PHYSICS_SIMULATION; no accuracy claim.
- Future draws must never enter a training prefix. Official failures must not fabricate results.
- Evidence and frozen outputs are create-only. No main merge in this task.

## Review focus
- Tampered tickets with otherwise valid model IDs must fail freezing.
- Prior champion identity or future cutoff must fail before inheritance.
- Backtest must use the requested simulation and evolution settings.
- HTTP errors must preserve actual status, available response digest and failure receipt.
- Output delivery must not label local runs as GitHub Actions or retrospective scores as predraw.

## Initial audit (base 6b9b2577e8a55945ed5758d97c514c6ad837451f)
1 HOT60: executable; fit lacks full counts/rank evidence and predict refits.
2 EWMA: half life fixed at 30; fit/predict cannot consume overrides.
3 ShrinkMix: recent/EWMA uniform prior, no empirical long-history prior.
4 Pairwise-D2: independent objective exists; observed/expected matrix not exported.
5 Challenger: real crossover exists; lineage omits genes and mutation records.
6 Statistics: independent fit exists; full component evidence missing.
7 ForecastSearch: real search exists; counts and provenance integrity need evidence.
8 Geometry: real transitions exist; full transition matrix/features not exported.
9 ProbabilitySimulation: executable; its own empirical draws capped silently at 500.
10 Physics: numeric contacts exist; mass, restitution, acceleration, trajectories absent.
11 Validation: all models receive chronological audit; M2 lacks uncertainty/correction; audit silently changes generations/trials/steps. Tiny holdout is exploratory only.
Cross cutting: freeze checks IDs/count only, prior report identity unchecked, execution evidence hardcodes GitHub origin.

## Tasks
- [ ] 1. Add behavior regressions, run RED, repair fitted state and numeric physics; test force/impulse/seed contracts.
- [ ] 2. Add lineage/identity/leakage/freeze regressions, run RED, repair evolution and chronological validation.
- [ ] 3. Add provenance/export regressions, run RED, deliver create-only JSON/Markdown artifacts and failure diagnostics.
- [ ] 4. Run complete relevant suite plus repository-wide discovery; generate both games from actual fetched histories, run restart inheritance in another process, score held-out actual draws separately, export A–V evidence.
- [ ] 5. Fresh independent branch review, fix important findings with regressions, publish branch/PR and observe CI; package source, logs, evidence and hashes in outputs.

## Execution ledger
- Isolated clone on codex/eleven-model-audit-20261114; original local repositories untouched.
- Official publisher fetch: HTTP 200 both, 100 SSQ / 10 DLT overlaps; historical seed authenticity outside overlap remains unverified.
- Decision: keep legacy five-family research API for compatibility; the delivered records use the eleven concrete registry classes.
