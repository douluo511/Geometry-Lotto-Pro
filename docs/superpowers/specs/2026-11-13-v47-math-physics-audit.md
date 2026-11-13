# V4.7 mathematical adversarial audit + physical collision kernel (research-only)

Date: 2026-11-13. Parent: PR #467 at `27c519ec0ad251a9d86ebc3452277b158930299e`. This is a small stacked Draft PR tracked by issue #468.

## Problem / non-goals
The V4.7 five candidate selectors and SHA256-sort Random NULL have code and synthetic tests. Complex arithmetic and geometry code should not be described as physical prediction. A second independent integer oracle can detect certain pairwise-formula deviations without modifying the preregistered algorithm.

No official source authentication, machine calibration, photogrammetry, air-flow analysis, full drawing machine solver, external TSA, host scheduler, newly registered model, or certified advantage is in scope.

## Design
- M1: Recompute fair D2 probability as exact rational `C(pool-2,picks-2)/C(pool,picks)`, compare with pinned SSQ/DLT rules. Replay all six original V4.7 models twice, retaining SHADOW-only status.
- M2: Independently score the existing 120-draw Pairwise-D2 formula using an integer scaling, retaining deterministic tie breaking; attack with forged pair-score mock. Check that target-bound fixed Random NULL is invariant to a valid alteration of historical draw data. Fail closed for non-synthetic provenance.
- M3: Return the known fair baseline but explicitly mark posterior calibration unavailable without authenticated prospective outcomes. Do not produce evidence labels, a formal A, a new winner, or any edge claim.
- Physics: A **single-contact**, frictionless, three-dimensional rigid-sphere impulse kernel (masses, radii, positions, velocities, restitution). Conservation and non-energy-creation checks only. No physical data were collected. No wall, air-flow, spin, geometry, hydrodynamics, measurement uncertainty or full simulation.
- All additions are isolated in `research/harness_v46/physics_audit.py` and tests. Existing core, fixed NULL, source intakes, ledgers, model IDs and parameters unchanged.

## Acceptance and negative controls
- Exact expected rational D2 baselines for SSQ and DLT.
- All original six model outputs deterministic on both synthetic lottery snapshots.
- Independent integer oracle detects a deliberately tampered Pairwise-D2 score source.
- Fake official provenance cannot be promoted through this synthetic auditor.
- Elastic collision exchanges equal-mass normal velocities and conserves momentum and energy.
- Inelastic collision never creates translational kinetic energy and conserves linear momentum.
- Invalid masses, ambiguous contact normals, restitution outside [0,1], non-finite inputs fail closed.
- Test-first RED evidence and exact-head full Ubuntu and Windows GREEN evidence are required separately. Stacked branch remains draft even if synthetic tests pass.
- Continue `formal_A=0`, `NO_EDGE`, `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`. No merge, lottery purchase, or model promotion.
